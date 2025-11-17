"""FastAPI webhook server for Faceit events."""
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional, Dict, List, Any
import json
import discord
import httpx # Import httpx
from app.config import WEBHOOK_SECRET, DISCORD_GUILD_ID, FACEIT_API_KEY, VC_CATEGORY_ID # Import VC_CATEGORY_ID
from app.db import get_player_links_by_faceit_ids, create_active_match, delete_active_match, get_active_matches_by_match_id # Add get_active_matches_by_match_id
from app.discord_bot import bot, active_match_cache, create_private_vc_and_move_users, cleanup_vc # Add cleanup_vc


app = FastAPI(title="Faceit Webhook Server")


@app.post("/faceit-webhook")
async def faceit_webhook(
    request: Request,
    x_faceit_signature: Optional[str] = Header(None, alias="X-Faceit-Signature")
) -> JSONResponse:
    """
    FastAPI route to handle Faceit webhook events.
    
    Expected events:
    - match_object_created: Create VC, move players
    - match_status_finished: Delete VC, clean up
    
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
        if event_type == "match_status_ready":
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


async def handle_match_ready(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match_status_ready event.
    
    Actions:
    1. Fetch detailed match data from Faceit API.
    2. Extract player Faceit IDs for both factions.
    3. For each faction: Map Faceit IDs -> Discord IDs, create private VC, move users, store in DB.
    """
    print(f"Handling match_status_ready for match {match_id}")
    
    match_data = await fetch_match_data(match_id)
    if not match_data:
        print(f"Could not fetch detailed match data for {match_id}")
        return

    guild = bot.get_guild(DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
    if not guild:
        print(f"Guild not found: {DISCORD_GUILD_ID}")
        return

    teams_data = match_data.get("teams", {})
    factions = ["faction1", "faction2"]

    for faction_name in factions:
        faction_data = teams_data.get(faction_name, {})
        roster = faction_data.get("roster", [])
        
        faceit_player_ids: List[str] = [player["player_id"] for player in roster if "player_id" in player]
        
        if not faceit_player_ids:
            print(f"Warning: No Faceit player IDs found for {faction_name} in match {match_id}")
            continue

        player_links = get_player_links_by_faceit_ids(faceit_player_ids)
        discord_user_ids: List[int] = [
            int(link["discord_id"])
            for faceit_id, link in player_links.items()
            if link.get("discord_id")
        ]
        
        if not discord_user_ids:
            print(f"No linked Discord users found for {faction_name} in match {match_id}")
            # Still create VC even if no users, as per previous logic

        vc = await create_private_vc_and_move_users(guild, discord_user_ids, match_id, faction_name, VC_CATEGORY_ID)
        if vc:
            create_active_match(match_id, faction_name, str(vc.id))
            print(f"Created VC {vc.id} for match {match_id} faction {faction_name}")


async def handle_match_cleanup(match_id: str, payload: Dict[str, Any]) -> None:
    """
    Handle match cleanup events (finished, aborted, cancelled).
    
    Actions:
    1. Fetch all voice channel IDs for the match from the DB.
    2. Delete each voice channel.
    3. Delete all active match records for the match from the DB.
    """
    print(f"Handling match cleanup for match {match_id}")
    
    active_matches = get_active_matches_by_match_id(match_id)
    if not active_matches:
        print(f"No active matches found for {match_id} to clean up.")
        return

    guild = bot.get_guild(DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None
    if not guild:
        print(f"Guild not found: {DISCORD_GUILD_ID}")
        return

    for match_record in active_matches:
        voice_channel_id = match_record.get("voice_channel_id")
        faction_name = match_record.get("faction")

        if voice_channel_id:
            await cleanup_vc(guild, voice_channel_id)
        
        # Delete from database for this specific faction
        delete_active_match(match_id, faction_name)
        print(f"Deleted active match record for {match_id} faction {faction_name}")

    # The cache for active_match_cache is currently designed for single VC per match_id. 
    # With faction support, it should ideally be updated to store {match_id: {faction: channel_id}}.
    # For now, relying on DB for cleanup. If cache is still used, it needs adjustment.
    # active_match_cache.pop(match_id, None) # This would remove all, but not ideal if we intend to manage per-faction in cache

