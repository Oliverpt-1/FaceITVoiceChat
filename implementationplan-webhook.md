# Implementation Plan: Webhook Optimization and OAuth2 PKCE

## Webhook Object Data Structure (as observed from provided JavaScript)

The incoming webhook payload from Faceit generally follows this structure:

```json
{
  "event": "match_object_created" | "match_status_aborted" | "match_status_cancelled" | "match_status_configuring" | "match_status_finished" | "match_status_ready" | "match_demo_ready",
  "timestamp": "ISO 8601 timestamp string",
  "payload": {
    "id": "string", // This is the match_id
    // ... other payload details ...
  }
  // ... other top-level fields ...
}
```

When fetching detailed match information using `GET https://open.faceit.com/data/v4/matches/{matchId}` (as shown in the JavaScript), the response structure will contain:

```json
{
  "entity": {
    "name": "string"
    // ...
  },
  "teams": {
    "faction1": {
      "name": "string",
      "roster": [
        {
          "player_id": "string",      // This is the faceit_id
          "nickname": "string",
          "game_skill_level": "integer"
          // ...
        }
      ]
    },
    "faction2": {
      "name": "string",
      "roster": [
        {
          "player_id": "string",
          "nickname": "string",
          "game_skill_level": "integer"
          // ...
        }
      ]
    }
  },
  "voting": {
    "map": {
      "pick": ["string"] // e.g., ["de_inferno"]
    }
  }
  // ... other match data fields ...
}
```

## Current State Analysis

### ✅ Already Implemented

1.  **Concurrent Execution (main.py)**
    *   Discord bot and FastAPI server run concurrently on the same asyncio event loop.
    *   **No changes needed** for concurrent execution.

2.  **FastAPI Webhook Server (webhook.py)**
    *   Exists and handles `/faceit-webhook` POST endpoint.
    *   Handles `match_object_created` and `match_status_finished` events.
    *   ⚠️ **Needs update**: Currently only processes `faction1`, needs to handle both `faction1` AND `faction2`.

3.  **Discord Bot (discord_bot.py)**
    *   Bot setup with slash commands.
    *   Has `/register` command (manual nickname search).
    *   ❌ **Missing**: `/link` command for OAuth2 PKCE flow.

4.  **Database Layer (db.py)**
    *   Supabase client initialized.
    *   Player links operations exist.
    *   ⚠️ **Needs update**: `active_matches` table operations do not support the `faction` column.
    *   Current `active_matches` schema: `(match_id, voice_channel_id)` - needs to be `(match_id, faction, voice_channel_id)`.

5.  **Dependencies (requirements.txt)**
    *   `aiohttp` already included (can use for OAuth HTTP calls and Faceit API calls).
    *   `fastapi`, `discord.py`, `supabase` all present.
    *   All built-in Python libraries needed for PKCE (secrets, hashlib, base64, urllib.parse) are available.

---

## ❌ Missing Components

### 1. OAuth2 PKCE Flow

**Missing Files:**
*   `app/auth_faceit.py` - OAuth helper functions.

**Missing Functionality:**
*   PKCE `code_verifier`/`code_challenge` generation.
*   State generation and storage (temporary, keyed to Discord user).
*   `/link` slash command in Discord bot to initiate the OAuth flow.
*   `GET /faceit/callback` route in FastAPI to handle the Faceit redirect.
*   Token exchange (code → `access_token`).
*   Userinfo API call to get `player_id` and `nickname`.
*   UPSERT `player_links` with `verified_method='oauth'`.

**Configuration Needed:**
*   `FACEIT_CLIENT_ID` environment variable.
*   `FACEIT_REDIRECT_URI` environment variable (e.g., `https://your-domain.com/faceit/callback`).
*   `FACEIT_AUTH_URL` = `https://accounts.faceit.com` (constant).
*   `FACEIT_TOKEN_URL` = `https://api.faceit.com/auth/v1/oauth/token` (constant).
*   `FACEIT_USERINFO_URL` = `https://api.faceit.com/auth/v1/resources/userinfo` (constant).

**State Storage:**
*   **Recommendation**: Use an in-memory dictionary with TTL cleanup (states expire after 10 minutes) for `{state: {discord_id, code_verifier, timestamp}}`. This is acceptable for a single-process Railway deployment.

### 2. Database Schema Updates

**Current `active_matches` table:**
```sql
match_id TEXT PRIMARY KEY
voice_channel_id TEXT
created_at TIMESTAMP
```

**Required `active_matches` table:**
```sql
match_id TEXT
faction TEXT  -- 'faction1' or 'faction2'
voice_channel_id TEXT
created_at TIMESTAMP DEFAULT NOW()
PRIMARY KEY(match_id, faction)
```

**Required `player_links` table update:**
*   Add `verified_method TEXT DEFAULT 'oauth'` column.

**Database Operations Needed in `app/db.py`:**
*   Update `create_player_link()` to support `verified_method` parameter and use UPSERT logic.
*   Update `create_active_match(match_id, faction, voice_channel_id)`.
*   Update `get_active_match(match_id, faction=None)` to retrieve either a specific faction's data or all factions for a match.
*   Update `delete_active_match(match_id, faction=None)` to delete records for a specific faction or all factions for a match.
*   Add `get_active_matches_by_match_id(match_id)` to fetch all factions for a match.

### 3. Webhook Handler Updates (in `app/webhook.py`)

**Current Implementation:**
*   Only processes `faction1` players.
*   Creates a single VC per match.
*   Stores a single `(match_id, voice_channel_id)` entry.

**Required Implementation:**
*   **For `match_object_created` events:**
    1.  Extract `match_id` from `payload.id`.
    2.  Fetch detailed match data from Faceit API: `GET https://open.faceit.com/data/v4/matches/{match_id}` using `FACEIT_API_KEY`.
    3.  Extract players from **both** `faction1` and `faction2` from the fetched match data.
    4.  For each faction (`faction1` and `faction2`):
        *   Map Faceit player IDs (`player_id`) to Discord user IDs via the database.
        *   Create a separate private voice channel named `match-<match_id_short>-<faction>` (e.g., `match-abcde123-faction1`).
        *   Move the mapped Discord users into that voice channel.
        *   UPSERT the `(match_id, faction, voice_channel_id)` into the `active_matches` table.
*   **For `match_status_finished` events:**
    1.  Extract `match_id` from `payload.id`.
    2.  Fetch all active match records for that `match_id` (which will now include both `faction1` and `faction2` entries).
    3.  For each faction's entry:
        *   Delete the corresponding voice channel from Discord.
        *   Delete the record from the `active_matches` table.

**Cache Update:**
*   Current: `active_match_cache: dict[str, str]` = `{match_id: channel_id}`.
*   Needed: `active_match_cache: dict[str, dict[str, str]]` = `{match_id: {'faction1': channel_id_1, 'faction2': channel_id_2}}` or adapt `active_match_cache` to store a list of channel IDs per match ID, or simply rely on the database for fetching all factions when needed. For now, relying on the DB to fetch all factions for a match during cleanup is simpler.

### 4. Configuration Updates

**Required Environment Variables (in `.env` and `app/config.py`):**
```bash
# OAuth2 Configuration
FACEIT_CLIENT_ID=your_client_id
FACEIT_REDIRECT_URI=https://your-domain.com/faceit/callback

# Existing (keep)
DISCORD_TOKEN=...
DISCORD_GUILD_ID=...
FACEIT_API_KEY=...
SUPABASE_URL=...
SUPABASE_KEY=...
PORT=8000
VC_CATEGORY_ID=...  # Optional
```

**`app/config.py` Updates:**
*   Add `FACEIT_CLIENT_ID`.
*   Add `FACEIT_REDIRECT_URI`.
*   Add OAuth URL constants.
*   Update `validate_config()` to include OAuth variables.

---

## Code Structure

```
app/
├── __init__.py
├── main.py              # ✅ Already runs both concurrently
├── config.py            # ⚠️ Needs OAuth config
├── db.py                # ⚠️ Needs faction support and verified_method
├── discord_bot.py       # ⚠️ Needs /link command
├── webhook.py           # ⚠️ Needs /callback route + faction handling + Faceit API call
└── auth_faceit.py       # ❌ NEW - OAuth helpers
```

---

## Key Implementation Details

### PKCE Code Verifier/Challenge

```python
import secrets
import hashlib
import base64
import urllib.parse
import time # For state cleanup

def generate_code_verifier() -> str:
    """Generate a cryptographically random code verifier (43-128 chars)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

def generate_code_challenge(verifier: str) -> str:
    """Generate code challenge from verifier (S256 method)."""
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')
```

### State Storage

```python
# In-memory storage with cleanup
oauth_states: dict[str, dict] = {}  # {state: {discord_id, code_verifier, timestamp}}

# Cleanup expired states (run periodically, e.g., via a background task or on access)
def cleanup_expired_states():
    current_time = time.time()
    # States expire after 10 minutes (600 seconds)
    expired = [s for s, data in oauth_states.items() if current_time - data['timestamp'] > 600]
    for state in expired:
        del oauth_states[state]
```

### OAuth Callback Flow

1.  User clicks authorize URL from `/link` command.
2.  Faceit redirects to `GET /faceit/callback?code=xxx&state=yyy`.
3.  FastAPI route (`GET /faceit/callback`):
    *   Verify `state` exists in `oauth_states`.
    *   Retrieve `discord_id` and `code_verifier` from state storage.
    *   Exchange `code` + `code_verifier` for `access_token` (POST to `FACEIT_TOKEN_URL`).
    *   Call `GET FACEIT_USERINFO_URL` with `access_token`.
    *   Extract `player_id` (from `sub` or `guid` field) and `nickname` (from `nickname` or `name` in userinfo response).
    *   UPSERT `player_links` table with `discord_id`, `player_id`, `nickname`, and `verified_method='oauth'`.
    *   Delete state from `oauth_states`.
    *   Redirect user to a success page or send a Discord DM.

### Webhook Faction Handling (Refined)

**For `match_object_created` in `app/webhook.py`:**

1.  Extract `match_id` from `payload.id`.
2.  Make a `GET` request to `https://open.faceit.com/data/v4/matches/{match_id}` with `Authorization: Bearer FACEIT_API_KEY`.
3.  From the response, extract player lists for `matchData.teams.faction1.roster` and `matchData.teams.faction2.roster`.
4.  For each `faction` (e.g., `'faction1'`, `'faction2'`):
    *   Collect all `player_id`s from the `roster`.
    *   Map these `player_id`s to Discord `discord_id`s using `db.get_player_links_by_faceit_ids()`.
    *   Call `discord_bot.create_private_vc_and_move_users()` with the `guild`, mapped `discord_ids`, `match_id`, and `faction` (for naming the VC: `match-{match_id_short}-{faction}`).
    *   Store the created `voice_channel_id` along with `match_id` and `faction` in `db.create_active_match()`.

**On `match_status_finished` in `app/webhook.py`:**

1.  Extract `match_id` from `payload.id`.
2.  Call `db.get_active_matches_by_match_id(match_id)` to retrieve all active match entries (both factions) for that `match_id`.
3.  For each returned entry:
    *   Retrieve the `voice_channel_id`.
    *   Get the Discord `guild` and `VoiceChannel` object.
    *   Move users out of the VC (optional, but good practice).
    *   Delete the voice channel.
    *   Delete the corresponding record from `active_matches` using `db.delete_active_match(match_id, faction)`.

---

## Next Steps

1.  **Review this plan** - confirm explicit data structures and proposed steps.
2.  **Set up Faceit OAuth app** - get `CLIENT_ID` and configure `REDIRECT_URI`.
3.  **Update database schema** - add `faction` column to `active_matches`, add `verified_method` to `player_links`.
4.  **Implement OAuth flow** - create `auth_faceit.py`, add `/link` command, add `/faceit/callback` route.
5.  **Update webhook handlers** - support both factions.
6.  **Test end-to-end** - OAuth flow + webhook flow.

---

## Notes

*   **State storage**: Using in-memory dict is acceptable for Railway single-process deployment.
*   **OAuth vs API Key**: OAuth is required for identity binding. The `FACEIT_API_KEY` is still needed for fetching detailed match data (as seen in the JS example).
*   **Error handling**: Add robust error handling for API calls, database operations, and Discord interactions.
*   **User experience**: After OAuth callback, consider sending a Discord DM to the user confirming a successful link.
*   **Environment Variables**: Ensure all new environment variables are added to `.env` and handled in `app/config.py`.
