"""Main entry point - runs Discord bot and FastAPI server concurrently."""
import asyncio
import uvicorn
from app.config import HOST, PORT, validate_config
from app.discord_bot import bot, DISCORD_TOKEN
from app.webhook import app as webhook_app
from app.db import init_db


async def run_discord_bot():
    """Run the Discord bot."""
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN not set in environment variables")
    
    await bot.start(DISCORD_TOKEN)


async def run_fastapi_server():
    """Run the FastAPI server."""
    config = uvicorn.Config(
        app=webhook_app,
        host=HOST,
        port=PORT,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()


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
        # FastAPI server will be stopped by uvicorn


if __name__ == "__main__":
    asyncio.run(main())

