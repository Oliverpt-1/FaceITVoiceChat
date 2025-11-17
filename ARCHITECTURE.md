# Faceit → Discord Integration Bot Architecture

## Single-Process Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Python Process (asyncio)                  │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              asyncio Event Loop                       │  │
│  │                                                        │  │
│  │  ┌────────────────────┐    ┌──────────────────────┐  │  │
│  │  │  Discord Gateway   │    │   FastAPI Server     │  │  │
│  │  │  (discord.py)      │    │   (uvicorn)          │  │  │
│  │  │                    │    │                      │  │  │
│  │  │  - Bot commands    │    │  POST /faceit-webhook│  │  │
│  │  │  - /register       │    │  - Handle events     │  │  │
│  │  │  - VC management   │    │  - Create/delete VC  │  │  │
│  │  │                    │    │                      │  │  │
│  │  └────────┬───────────┘    └──────────┬───────────┘  │  │
│  │           │                            │              │  │
│  │           └────────────┬───────────────┘              │  │
│  │                        │                              │  │
│  │              ┌─────────▼─────────┐                    │  │
│  │              │  Shared Resources │                    │  │
│  │              │                   │                    │  │
│  │              │  - bot instance   │                    │  │
│  │              │  - active_match_  │                    │  │
│  │              │    cache (dict)   │                    │  │
│  │              │  - db client      │                    │  │
│  │              └─────────┬─────────┘                    │  │
│  └────────────────────────┼──────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
        │  Discord  │  │  Supabase │  │  Faceit   │
        │  API      │  │  Postgres │  │  Webhooks │
        └───────────┘  └───────────┘  └───────────┘
```

## Key Components

### 1. **Discord Bot (discord_bot.py)**
- Handles Discord gateway connection
- Manages slash commands (`/register`)
- Creates and manages voice channels
- Moves users between voice channels

### 2. **FastAPI Webhook Server (webhook.py)**
- Listens on `POST /faceit-webhook`
- Processes Faceit webhook events:
  - `match_object_created`: Create VC, move players
  - `match_status_finished`: Delete VC, cleanup

### 3. **Database Layer (db.py)**
- Supabase client for Postgres operations
- Player links table: `discord_id` ↔ `faceit_id`
- Active matches table: `match_id` ↔ `voice_channel_id`

### 4. **In-Memory Cache**
- `active_match_cache: dict[str, str]` = `{match_id: channel_id}`
- Reduces database queries for frequent lookups
- Synced with database on create/delete

### 5. **Main Entry Point (main.py)**
- Initializes database connection
- Starts Discord bot and FastAPI server concurrently
- Uses `asyncio.gather()` to run both in same event loop

## Data Flow

### Registration Flow
1. User runs `/register <faceit_nickname>` in Discord
2. Bot calls Faceit REST API: `GET /search/players?nickname=...`
3. Bot extracts `player_id` from response
4. Bot stores mapping in `player_links` table

### Match Created Flow
1. Faceit sends webhook: `POST /faceit-webhook` (event: `match_object_created`)
2. FastAPI extracts `faction1` players and their `player_id`s
3. Database lookup: `faceit_id` → `discord_id` (batch query)
4. Bot creates private VC with permissions for matched players
5. Bot moves players into VC
6. Store `match_id` + `channel_id` in DB and cache

### Match Finished Flow
1. Faceit sends webhook: `POST /faceit-webhook` (event: `match_status_finished`)
2. FastAPI reads `match_id` from payload
3. Lookup `channel_id` from cache (fallback to DB)
4. Bot moves users out of VC
5. Bot deletes VC
6. Delete from DB and cache

## Deployment

- **Platform**: Railway (single always-on container)
- **Process**: One Python process running both services
- **Port**: FastAPI listens on `PORT` (default: 8000)
- **Environment Variables**: See `.env.example`

