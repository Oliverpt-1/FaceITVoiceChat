"""Configuration management for the Faceit Discord bot."""
import os
from typing import Optional

# Discord Configuration
DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD_ID: Optional[int] = int(os.getenv("DISCORD_GUILD_ID", "0")) if os.getenv("DISCORD_GUILD_ID") else None

# Faceit API Configuration
FACEIT_API_KEY: Optional[str] = os.getenv("FACEIT_API_KEY")
FACEIT_API_URL: str = "https://open.faceit.com/data/v4"

# Supabase Configuration
SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
SUPABASE_KEY: Optional[str] = os.getenv("SUPABASE_KEY")

# FastAPI Configuration
WEBHOOK_SECRET: Optional[str] = os.getenv("WEBHOOK_SECRET")  # Optional webhook verification
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# Discord VC Configuration
VC_CATEGORY_ID: Optional[int] = int(os.getenv("VC_CATEGORY_ID", "0")) if os.getenv("VC_CATEGORY_ID") else None

def validate_config() -> bool:
    """Validate that all required configuration is present."""
    required = [
        DISCORD_TOKEN,
        SUPABASE_URL,
        SUPABASE_KEY,
        FACEIT_API_KEY,
    ]
    return all(required)

