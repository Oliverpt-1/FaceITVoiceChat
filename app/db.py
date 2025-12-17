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


# Matches Operations (Unified matches table)
def create_match(
    match_id: str,
    entity_name: Optional[str] = None,
    faction1_name: Optional[str] = None,
    faction2_name: Optional[str] = None,
    faction1_players: Optional[List[str]] = None,
    faction2_players: Optional[List[str]] = None,
    map_picked: Optional[str] = None,
    status: str = "created"
) -> Dict:
    """Create a new match record in the matches table."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    data = {
        "match_id": match_id,
        "status": status,
        "entity_name": entity_name,
        "faction1_name": faction1_name,
        "faction2_name": faction2_name,
        "faction1_players": faction1_players or [],
        "faction2_players": faction2_players or [],
        "map_picked": map_picked,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    result = supabase.table("matches").insert(data).execute()
    return result.data[0] if result.data else {}


def get_match(match_id: str) -> Optional[Dict]:
    """Get match by match_id."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    result = supabase.table("matches").select("*").eq("match_id", match_id).execute()
    return result.data[0] if result.data else None


def update_match_status(match_id: str, status: str, finished_at: Optional[str] = None) -> Dict:
    """Update match status and optionally set finished_at timestamp."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    data = {
        "status": status,
        "updated_at": datetime.utcnow().isoformat()
    }
    if finished_at:
        data["finished_at"] = finished_at
    elif status in ["finished", "aborted", "cancelled", "closed"]:
        data["finished_at"] = datetime.utcnow().isoformat()
    
    result = supabase.table("matches").update(data).eq("match_id", match_id).execute()
    return result.data[0] if result.data else {}


def update_match_vc_ids(match_id: str, faction1_vc_id: Optional[str] = None, faction2_vc_id: Optional[str] = None) -> Dict:
    """Update match voice channel IDs."""
    if not supabase:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    
    data = {
        "updated_at": datetime.utcnow().isoformat()
    }
    if faction1_vc_id:
        data["faction1_vc_id"] = faction1_vc_id
    if faction2_vc_id:
        data["faction2_vc_id"] = faction2_vc_id
    
    result = supabase.table("matches").update(data).eq("match_id", match_id).execute()
    return result.data[0] if result.data else {}

