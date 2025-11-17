# Faceit → Discord Integration Bot

A Discord bot that integrates with Faceit to automatically manage voice channels for matches.

## Features

- **Player Registration**: Users register their Faceit nickname via `/register` command
- **Automatic VC Management**: Creates private voice channels when matches start
- **Player Movement**: Automatically moves players into match voice channels
- **Cleanup**: Deletes voice channels when matches finish

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed architecture diagram and design.

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**:
   Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```

3. **Run the bot**:
   ```bash
   python -m app.main
   ```

## Environment Variables

- `DISCORD_TOKEN`: Discord bot token
- `DISCORD_GUILD_ID`: Discord server/guild ID
- `FACEIT_API_KEY`: Faceit API key
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase API key
- `PORT`: FastAPI server port (default: 8000)
- `VC_CATEGORY_ID`: Optional category ID for voice channels

## Database Schema

### player_links
- `discord_id` TEXT PRIMARY KEY
- `faceit_id` TEXT NOT NULL
- `faceit_nickname` TEXT NOT NULL
- `linked_at` TIMESTAMP DEFAULT NOW()

### active_matches
- `match_id` TEXT PRIMARY KEY
- `voice_channel_id` TEXT NOT NULL
- `created_at` TIMESTAMP DEFAULT NOW()

## Webhook Setup

1. In Faceit App Studio → Webhooks
2. Create new subscription:
   - Type: Organizer
   - Events: `match_object_created`, `match_status_finished`
   - Callback URL: `https://your-domain.com/faceit-webhook`

## Deployment (Railway)

1. Connect your repository to Railway
2. Set environment variables in Railway dashboard
3. Railway will automatically deploy and run the container

The bot runs as a single process with both Discord gateway and FastAPI server in the same asyncio event loop.

