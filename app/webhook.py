"""FastAPI webhook server for Faceit events."""
from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Optional, Dict, List, Any
import json
import base64
import discord
import httpx # Import httpx
from app.config import (
    WEBHOOK_SECRET, DISCORD_GUILD_ID, FACEIT_API_KEY, VC_CATEGORY_ID, LOBBY_VC_ID,
    FACEIT_CLIENT_ID, FACEIT_CLIENT_SECRET, FACEIT_REDIRECT_URI, FACEIT_TOKEN_URL, FACEIT_USERINFO_URL
)
from app.db import (
    get_player_links_by_faceit_ids, create_player_link,
    create_match, get_match, update_match_status, update_match_vc_ids
)
from app.discord_bot import bot, create_private_vc_and_move_users, cleanup_vc
from app.auth_faceit import get_oauth_state, delete_oauth_state


app = FastAPI(title="Faceit Webhook Server")


@app.get("/faceit/callback")
async def faceit_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None)
):
    """
    OAuth2 callback endpoint for FaceIT account verification.
    
    FaceIT redirects here after user authorization with:
    - code: Authorization code (if successful)
    - state: State token for CSRF protection
    - error: Error code (if failed)
    - error_description: Error description (if failed)
    """
    print(f"[CALLBACK] ===== OAuth callback received =====")
    print(f"[CALLBACK] Code present: {code is not None}, State present: {state is not None}")
    print(f"[CALLBACK] Error: {error}, Error description: {error_description}")
    
    # Handle OAuth errors
    if error:
        print(f"[CALLBACK] OAuth error received: {error} - {error_description}")
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>FaceIT Verification Failed</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>❌ Verification Failed</h1>
            <p>{error_description or error}</p>
            <p>Please try again using the /verify command in Discord.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=400)
    
    # Validate required parameters
    if not code or not state:
        print(f"[CALLBACK] Missing required parameters - code: {code is not None}, state: {state is not None}")
        error_html = """
        <!DOCTYPE html>
        <html>
        <head><title>FaceIT Verification Failed</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>❌ Invalid Request</h1>
            <p>Missing authorization code or state parameter.</p>
            <p>Please try again using the /verify command in Discord.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=400)
    
    # Validate state
    print(f"[CALLBACK] Validating state: {state[:20]}...")
    state_data = get_oauth_state(state)
    if not state_data:
        print(f"[CALLBACK] State validation failed - state not found or expired")
        error_html = """
        <!DOCTYPE html>
        <html>
        <head><title>FaceIT Verification Failed</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>❌ Invalid or Expired Link</h1>
            <p>The verification link has expired or is invalid.</p>
            <p>Please try again using the /verify command in Discord.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=400)
    
    discord_id = state_data["discord_id"]
    code_verifier = state_data["code_verifier"]
    print(f"[CALLBACK] State validated successfully - Discord ID: {discord_id}")
    
    try:
        # Exchange authorization code for access token
        print(f"[CALLBACK] Attempting token exchange...")
        print(f"[CALLBACK] Token endpoint: {FACEIT_TOKEN_URL}")
        print(f"[CALLBACK] Client ID: {FACEIT_CLIENT_ID}")
        print(f"[CALLBACK] Redirect URI: {FACEIT_REDIRECT_URI}")
        print(f"[CALLBACK] Code: {code}")
        print(f"[CALLBACK] Code verifier (first 10 chars): {code_verifier[:10]}...")
        
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": FACEIT_REDIRECT_URI,
            "client_id": FACEIT_CLIENT_ID,
            "code_verifier": code_verifier
        }
        
        print(f"[CALLBACK] Token request data: {token_data}")
        
        # Prepare HTTP Basic Authentication
        if not FACEIT_CLIENT_SECRET:
            print(f"[CALLBACK] ERROR: FACEIT_CLIENT_SECRET not configured!")
            error_html = """
            <!DOCTYPE html>
            <html>
            <head><title>FaceIT Verification Failed</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Configuration Error</h1>
                <p>Client Secret is not configured. Please contact the administrator.</p>
            </body>
            </html>
            """
            return HTMLResponse(content=error_html, status_code=500)
        
        # Create Basic Auth header: base64(client_id:client_secret)
        credentials = f"{FACEIT_CLIENT_ID}:{FACEIT_CLIENT_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        auth_header = f"Basic {encoded_credentials}"
        
        async with httpx.AsyncClient() as client:
            # POST to token endpoint with HTTP Basic Auth (per FaceIT documentation)
            # Body includes code_verifier for PKCE
            token_response = await client.post(
                FACEIT_TOKEN_URL,
                data=token_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": auth_header
                }
            )
            
            print(f"[CALLBACK] Token exchange response status: {token_response.status_code}")
            print(f"[CALLBACK] Token exchange response headers: {dict(token_response.headers)}")
            if token_response.status_code != 200:
                print(f"[CALLBACK] Token exchange failed: {token_response.status_code} - {token_response.text}")
                error_html = """
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Failed</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>❌ Verification Failed</h1>
                    <p>Failed to exchange authorization code for token.</p>
                    <p>Please try again using the /verify command in Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=error_html, status_code=500)
            
            token_json = token_response.json()
            access_token = token_json.get("access_token")
            print(f"[CALLBACK] Token exchange successful - Access token received: {access_token is not None}")
            
            if not access_token:
                print(f"No access token in response: {token_json}")
                error_html = """
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Failed</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>❌ Verification Failed</h1>
                    <p>No access token received from FaceIT.</p>
                    <p>Please try again using the /verify command in Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=error_html, status_code=500)
            
            # Fetch user info
            print(f"[CALLBACK] Fetching userinfo from: {FACEIT_USERINFO_URL}")
            userinfo_response = await client.get(
                FACEIT_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            print(f"[CALLBACK] Userinfo response status: {userinfo_response.status_code}")
            if userinfo_response.status_code != 200:
                print(f"Userinfo fetch failed: {userinfo_response.status_code} - {userinfo_response.text}")
                error_html = """
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Failed</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>❌ Verification Failed</h1>
                    <p>Failed to fetch user information from FaceIT.</p>
                    <p>Please try again using the /verify command in Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=error_html, status_code=500)
            
            userinfo = userinfo_response.json()
            print(f"[CALLBACK] Userinfo received: {json.dumps(userinfo, indent=2)}")
            
            # Extract FaceIT user ID and nickname
            # FaceIT userinfo returns 'guid' as the user ID
            faceit_id = userinfo.get("guid") or userinfo.get("id") or userinfo.get("sub")
            faceit_nickname = userinfo.get("nickname") or userinfo.get("name")
            print(f"[CALLBACK] Extracted - FaceIT ID: {faceit_id}, Nickname: {faceit_nickname}")
            
            if not faceit_id:
                print(f"No FaceIT ID in userinfo: {userinfo}")
                error_html = """
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Failed</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>❌ Verification Failed</h1>
                    <p>Could not retrieve FaceIT user ID.</p>
                    <p>Please try again using the /verify command in Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=error_html, status_code=500)
            
            # Store in database
            print(f"[CALLBACK] Attempting to store in database - Discord ID: {discord_id}, FaceIT ID: {faceit_id}, Nickname: {faceit_nickname}")
            try:
                result = create_player_link(
                    discord_id=discord_id,
                    faceit_id=faceit_id,
                    faceit_nickname=faceit_nickname or "Unknown",
                    verified_method="oauth"
                )
                print(f"[CALLBACK] Database insertion successful: {result}")
                
                # Delete state after successful verification
                delete_oauth_state(state)
                print(f"[CALLBACK] OAuth state deleted, returning success page")
                
                # Success page
                success_html = f"""
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Success</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>✅ Verification Successful!</h1>
                    <p>Your FaceIT account <strong>{faceit_nickname or 'Unknown'}</strong> has been linked to your Discord account.</p>
                    <p>You can close this window and return to Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=success_html)
                
            except Exception as db_error:
                print(f"[CALLBACK] Database error: {db_error}")
                import traceback
                traceback.print_exc()
                error_html = """
                <!DOCTYPE html>
                <html>
                <head><title>FaceIT Verification Failed</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>❌ Verification Failed</h1>
                    <p>Failed to save verification to database.</p>
                    <p>Please try again using the /verify command in Discord.</p>
                </body>
                </html>
                """
                return HTMLResponse(content=error_html, status_code=500)
                
    except Exception as e:
        print(f"[CALLBACK] OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        error_html = """
        <!DOCTYPE html>
        <html>
        <head><title>FaceIT Verification Failed</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>❌ Verification Failed</h1>
            <p>An unexpected error occurred during verification.</p>
            <p>Please try again using the /verify command in Discord.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=500)


@app.post("/faceit-webhook")
async def faceit_webhook(
    request: Request,
    x_faceit_signature: Optional[str] = Header(None, alias="X-Faceit-Signature")
) -> JSONResponse:
    """
    FastAPI route to handle Faceit webhook events.
    
    Expected events:
    - match_object_created: Store match data in DB (status=created)
    - match_status_configuring: Update match status (status=configuring)
    - match_status_ready: Create VCs, move players from lobby, update status (status=ready)
    - match_status_finished/aborted/cancelled: Delete VCs, update status (status=closed)
    
    Route signature:
    POST /faceit-webhook
    Headers: X-Faceit-Signature (optional, for webhook verification)
    Body: JSON payload with event type and match data
    """
    try:
        # Parse request body
        payload = await request.json()
        
        # Log the full payload for debugging (remove in production or make it configurable)
        print(f"Received webhook payload: {json.dumps(payload, indent=2)}")
        
        # Extract event type - Faceit webhook structure unknown, try common patterns
        event_type = (
            payload.get("event") or 
            payload.get("type") or 
            payload.get("event_type") or
            payload.get("payload", {}).get("event")
        )
        
        if not event_type:
            print("Warning: Could not determine event type from payload")
            return JSONResponse(
                status_code=200,
                content={"status": "ignored", "reason": "no_event_type"}
            )
        
        # Optional: Verify webhook signature if WEBHOOK_SECRET is set
        if WEBHOOK_SECRET and x_faceit_signature:
            # TODO: Implement signature verification based on Faceit's method
            pass
        
        match_id = payload.get("payload", {}).get("id")
        if not match_id:
            print(f"Warning: No match_id found in payload for event {event_type}. Payload keys: {list(payload.keys())}")
            return JSONResponse(
                status_code=200,
                content={"status": "ignored", "reason": "no_match_id"}
            )

        # Handle different event types
        if event_type == "match_object_created":
            print(f"Processing match_object_created for match_id: {match_id}")
            await handle_match_created(match_id, payload)
        elif event_type == "match_status_configuring":
            print(f"Processing match_status_configuring for match_id: {match_id}")
            await handle_match_configuring(match_id, payload)
        elif event_type == "match_status_ready":
            print(f"Processing match_status_ready for match_id: {match_id}")
            await handle_match_ready(match_id, payload)
        elif event_type in ["match_status_finished", "match_status_aborted", "match_status_cancelled"]:
            print(f"Processing {event_type} for match_id: {match_id}")
            await handle_match_cleanup(match_id, payload)
        else:
            print(f"Ignoring unknown or unhandled event type: {event_type}")
            return JSONResponse(
                status_code=200,
                content={"status": "ignored", "event": event_type}
            )
        
        return JSONResponse(
            status_code=200,
            content={"status": "success", "event": event_type}
        )
    
    except Exception as e:
        print(f"Webhook error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def fetch_match_data(match_id: str) -> Optional[Dict[str, Any]]:
    """Fetches detailed match data from the Faceit API."""
    if not FACEIT_API_KEY:
        print("Error: FACEIT_API_KEY not set. Cannot fetch match data.")
        return None
    
    url = f"https://open.faceit.com/data/v4/matches/{match_id}"
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status() # Raise an exception for HTTP errors
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"HTTP error fetching match {match_id}: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"Request error fetching match {match_id}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while fetching match {match_id}: {e}")
    return None


async def handle_match_created(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match_object_created event.
    
    Actions:
    1. Fetch detailed match data from Faceit API.
    2. Extract teams, players, entity name, map.
    3. Store match data in matches table with status = "created".
    """
    print(f"Handling match_object_created for match {match_id}")
    
    # Check if match already exists (idempotency)
    existing_match = get_match(match_id)
    if existing_match:
        print(f"Match {match_id} already exists in database, skipping creation")
        return
    
    match_data = await fetch_match_data(match_id)
    if not match_data:
        print(f"Could not fetch detailed match data for {match_id}")
        return
    
    # Extract match information
    entity_name = match_data.get("entity", {}).get("name")
    teams_data = match_data.get("teams", {})
    
    faction1_data = teams_data.get("faction1", {})
    faction1_name = faction1_data.get("name")
    faction1_players = [player.get("player_id") for player in faction1_data.get("roster", []) if player.get("player_id")]
    
    faction2_data = teams_data.get("faction2", {})
    faction2_name = faction2_data.get("name")
    faction2_players = [player.get("player_id") for player in faction2_data.get("roster", []) if player.get("player_id")]
    
    map_picked = None
    if match_data.get("voting", {}).get("map", {}).get("pick"):
        map_picked = match_data["voting"]["map"]["pick"][0]
    
    # Store match in database
    create_match(
        match_id=match_id,
        entity_name=entity_name,
        faction1_name=faction1_name,
        faction2_name=faction2_name,
        faction1_players=faction1_players,
        faction2_players=faction2_players,
        map_picked=map_picked,
        status="created"
    )
    print(f"Stored match {match_id} in database with status=created")


async def handle_match_configuring(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match_status_configuring event.
    
    Actions:
    1. Update match status to "configuring".
    """
    print(f"Handling match_status_configuring for match {match_id}")
    
    match = get_match(match_id)
    if not match:
        print(f"Match {match_id} not found in database, ignoring configuring event")
        return
    
    update_match_status(match_id, "configuring")
    print(f"Updated match {match_id} status to configuring")


async def handle_match_ready(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match_status_ready event.
    
    Actions:
    1. Verify match exists in database.
    2. Create voice channels for both factions.
    3. Move users from lobby VC to their team VC.
    4. Update matches table with VC IDs and status = "ready".
    """
    print(f"Handling match_status_ready for match {match_id}")
    
    # Check if match exists in database
    match = get_match(match_id)
    if not match:
        print(f"Match {match_id} not found in database, fetching from API and creating record")
        # If match doesn't exist, create it first
        await handle_match_created(match_id, payload)
        match = get_match(match_id)
        if not match:
            print(f"Failed to create match {match_id}")
            return

    guild = bot.get_guild(DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
    if not guild:
        print(f"Guild not found: {DISCORD_GUILD_ID}")
        return

    # Get lobby VC
    lobby_vc = guild.get_channel(LOBBY_VC_ID) if LOBBY_VC_ID else None
    if not lobby_vc:
        print(f"Lobby VC {LOBBY_VC_ID} not found")

    # Get player Faceit IDs from match record
    faction1_players = match.get("faction1_players", [])
    faction2_players = match.get("faction2_players", [])
    
    faction1_vc_id = None
    faction2_vc_id = None

    # Process faction1
    if faction1_players:
        player_links = get_player_links_by_faceit_ids(faction1_players)
        discord_user_ids: List[int] = [
            int(link["discord_id"])
            for faceit_id, link in player_links.items()
            if link.get("discord_id")
        ]
        
        vc = await create_private_vc_and_move_users(
            guild, discord_user_ids, match_id, "faction1", VC_CATEGORY_ID, LOBBY_VC_ID
        )
        if vc:
            faction1_vc_id = str(vc.id)
            print(f"Created VC {vc.id} for match {match_id} faction1")
    else:
        print(f"Warning: No players found for faction1 in match {match_id}")

    # Process faction2
    if faction2_players:
        player_links = get_player_links_by_faceit_ids(faction2_players)
        discord_user_ids: List[int] = [
            int(link["discord_id"])
            for faceit_id, link in player_links.items()
            if link.get("discord_id")
        ]
        
        vc = await create_private_vc_and_move_users(
            guild, discord_user_ids, match_id, "faction2", VC_CATEGORY_ID, LOBBY_VC_ID
        )
        if vc:
            faction2_vc_id = str(vc.id)
            print(f"Created VC {vc.id} for match {match_id} faction2")
    else:
        print(f"Warning: No players found for faction2 in match {match_id}")

    # Update matches table with VC IDs and status
    if faction1_vc_id or faction2_vc_id:
        update_match_vc_ids(match_id, faction1_vc_id, faction2_vc_id)
        update_match_status(match_id, "ready")
        print(f"Updated match {match_id} with VC IDs and status=ready")


async def handle_match_cleanup(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match cleanup events (finished, aborted, cancelled).
    
    Actions:
    1. Get match from database.
    2. Delete both voice channels (faction1_vc_id and faction2_vc_id).
    3. Update match status to "closed" and set finished_at timestamp.
    """
    print(f"Handling match cleanup for match {match_id}")
    
    match = get_match(match_id)
    if not match:
        print(f"Match {match_id} not found in database, nothing to clean up")
        return

    guild = bot.get_guild(DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
    if not guild:
        print(f"Guild not found: {DISCORD_GUILD_ID}")
        return

    # Delete faction1 VC if it exists
    faction1_vc_id = match.get("faction1_vc_id")
    if faction1_vc_id:
        await cleanup_vc(guild, faction1_vc_id)
        print(f"Deleted VC {faction1_vc_id} for match {match_id} faction1")

    # Delete faction2 VC if it exists
    faction2_vc_id = match.get("faction2_vc_id")
    if faction2_vc_id:
        await cleanup_vc(guild, faction2_vc_id)
        print(f"Deleted VC {faction2_vc_id} for match {match_id} faction2")

    # Update match status to closed
    update_match_status(match_id, "closed")
    print(f"Updated match {match_id} status to closed")

