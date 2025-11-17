# Technical Specification

## 1. Architecture Diagram

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full architecture diagram.

**Key Points:**
- Single Python process running both Discord gateway and FastAPI server
- Shared asyncio event loop for concurrent execution
- In-memory cache (`active_match_cache`) shared between Discord bot and FastAPI
- Both services access the same Supabase database client

## 2. FastAPI Route Signature

### POST /faceit-webhook

**Location:** `app/webhook.py`

```python
@app.post("/faceit-webhook")
async def faceit_webhook(
    request: Request,
    x_faceit_signature: Optional[str] = Header(None, alias="X-Faceit-Signature")
) -> JSONResponse:
```

**Request:**
- Method: `POST`
- Path: `/faceit-webhook`
- Headers: 
  - `Content-Type: application/json`
  - `X-Faceit-Signature` (optional, for webhook verification)
- Body: JSON payload with event type and match data

**Expected Payload Structure:**
```json
{
  "event": "match_object_created" | "match_status_finished",
  "match_id": "string",
  "organizer_id": "string",
  "entity": {
    "teams": {
      "faction1": {
        "roster": [
          {
            "player_id": "string",
            "nickname": "string"
          }
        ]
      }
    }
  }
}
```

**Response:**
- Status: `200 OK`
- Body: `{"status": "success", "event": "event_type"}`

## 3. Discord Slash Command Definition

### /register

**Location:** `app/discord_bot.py`

```python
@bot.tree.command(name="register", description="Register your Faceit nickname with the bot")
@app_commands.describe(faceit_nickname="Your Faceit nickname")
async def register_command(interaction: discord.Interaction, faceit_nickname: str):
```

**Command Details:**
- Name: `register`
- Description: "Register your Faceit nickname with the bot"
- Parameter: `faceit_nickname` (string, required)
- Response: Ephemeral (only visible to user)

**Flow:**
1. Check if user is already registered
2. Call Faceit API: `GET /search/players?nickname={faceit_nickname}`
3. Extract `player_id` from response
4. Store mapping in `player_links` table
5. Send confirmation message

## 4. Helper Function: Create Private VC + Move Users

**Location:** `app/discord_bot.py`

```python
async def create_private_vc_and_move_users(
    guild: discord.Guild,
    user_ids: List[int],
    match_id: str,
    category_id: Optional[int] = None
) -> Optional[discord.VoiceChannel]:
```

**Functionality:**
1. Creates a private voice channel (hidden from @everyone)
2. Sets permissions for specified users (view, connect, speak)
3. Moves users into the channel (if they're already in a VC)
4. Returns the created `VoiceChannel` object

**Key Features:**
- Private channel (default role cannot view)
- Permissions granted only to match participants
- Automatic user movement (if they're in a voice channel)
- Channel naming: `Match {match_id[:8]}`

## 5. In-Memory Cache

**Location:** `app/discord_bot.py`

```python
# In-memory cache for active matches (match_id -> voice_channel_id)
active_match_cache: dict[str, str] = {}
```

**Usage:**
- Cache lookup before database query
- Updated on match creation: `active_match_cache[match_id] = channel_id`
- Removed on match finish: `active_match_cache.pop(match_id, None)`
- Shared between Discord bot and FastAPI webhook handler

**Cache Strategy:**
1. Check cache first (fast)
2. Fallback to database if cache miss
3. Update cache on create/delete operations

## 6. Concurrent Execution (Discord + FastAPI)

**Location:** `app/main.py`

```python
async def main():
    """Main function - runs both Discord bot and FastAPI server concurrently."""
    # Validate configuration
    if not validate_config():
        raise ValueError("Invalid configuration. Check environment variables.")
    
    # Initialize database
    init_db()
    
    # Create tasks for concurrent execution
    discord_task = asyncio.create_task(run_discord_bot())
    fastapi_task = asyncio.create_task(run_fastapi_server())
    
    # Run both concurrently
    try:
        await asyncio.gather(discord_task, fastapi_task)
    except KeyboardInterrupt:
        print("Shutting down...")
        await bot.close()
```

**Key Implementation:**
- `asyncio.create_task()` creates concurrent tasks
- `asyncio.gather()` runs both tasks in the same event loop
- `uvicorn.Server()` runs FastAPI asynchronously
- `bot.start()` runs Discord gateway asynchronously
- Both share the same event loop and can access shared resources

**Starting the Application:**
```bash
python -m app.main
```

## Event Mapping

| Faceit Event | Bot Action |
|-------------|------------|
| `match_object_created` | 1. Parse `faction1` players<br>2. Map Faceit IDs → Discord IDs<br>3. Create private VC<br>4. Move 5 users into VC<br>5. Store `match_id` + `channel_id` in `active_matches` (DB + cache) |
| `match_status_finished` | 1. Read `match_id` from payload<br>2. Fetch `voice_channel_id` from cache/DB<br>3. Delete VC<br>4. Delete row from `active_matches`<br>5. Remove from cache |

