"""Database operations using Supabase client."""
from typing import Optional, Dict, List
from datetime import datetime
from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY

# Initialize Supabase client
supabase: Optional[Client] = None

def init_db() -> None:
    """Initialize the Supabase client."""
    global supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase URL and KEY must be set in environment variables")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Player Links Operations
def create_player_link(discord_id: str, faceit_id: str, faceit_nickname: str, verified_method: str = 'oauth') -> Dict:
    """Create or update a player link mapping."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    data = {
        "discord_id": discord_id,
        "faceit_id": faceit_id,
        "faceit_nickname": faceit_nickname,
        "linked_at": datetime.utcnow().isoformat(),
        "verified_method": verified_method
    }
    result = supabase.table("player_links").upsert(data, on_conflict="discord_id").execute()
    return result.data[0] if result.data else {}


def get_player_link_by_faceit_id(faceit_id: str) -> Optional[Dict]:
    """Get player link by Faceit ID."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    result = supabase.table("player_links").select("*").eq("faceit_id", faceit_id).execute()
    return result.data[0] if result.data else None


def get_player_links_by_faceit_ids(faceit_ids: List[str]) -> Dict[str, Dict]:
    """Get multiple player links by Faceit IDs. Returns dict mapping faceit_id -> player_data."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    result = supabase.table("player_links").select("*").in_("faceit_id", faceit_ids).execute()
    return {row["faceit_id"]: row for row in result.data} if result.data else {}


def get_player_link_by_discord_id(discord_id: str) -> Optional[Dict]:
    """Get player link by Discord ID."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    result = supabase.table("player_links").select("*").eq("discord_id", discord_id).execute()
    return result.data[0] if result.data else None


# Active Matches Operations
def create_active_match(match_id: str, faction: str, voice_channel_id: str) -> Dict:
    """Create a new active match record for a specific faction."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    data = {
        "match_id": match_id,
        "faction": faction,
        "voice_channel_id": voice_channel_id,
        "created_at": datetime.utcnow().isoformat()
    }
    result = supabase.table("active_matches").insert(data).execute()
    return result.data[0] if result.data else {}


def get_active_match(match_id: str, faction: Optional[str] = None) -> Optional[Dict]:
    """Get active match by match_id and optional faction."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    query = supabase.table("active_matches").select("*").eq("match_id", match_id)
    if faction:
        query = query.eq("faction", faction)
    
    result = query.execute()
    return result.data[0] if result.data else None

def get_active_matches_by_match_id(match_id: str) -> List[Dict]:
    """Get all active match records for a given match_id."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    result = supabase.table("active_matches").select("*").eq("match_id", match_id).execute()
    return result.data if result.data else []


def delete_active_match(match_id: str, faction: Optional[str] = None) -> None:
    """Delete active match record(s) by match_id and optional faction."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    query = supabase.table("active_matches").delete().eq("match_id", match_id)
    if faction:
        query = query.eq("faction", faction)
    
    query.execute()

