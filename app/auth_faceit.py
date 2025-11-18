"""OAuth2 PKCE helper functions for FaceIT authentication."""
import secrets
import hashlib
import base64
import time
from typing import Optional, Dict
from urllib.parse import urlencode

# In-memory state storage: {state: {discord_id, code_verifier, timestamp}}
oauth_states: Dict[str, Dict] = {}


def generate_code_verifier() -> str:
    """Generate a cryptographically random code verifier (43-128 chars, URL-safe)."""
    # Generate 32 random bytes, encode to base64url, remove padding
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')


def generate_code_challenge(verifier: str) -> str:
    """Generate code challenge from verifier using S256 method."""
    # SHA256 hash, then base64url encode
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')


def generate_state() -> str:
    """Generate a random state token for CSRF protection."""
    return secrets.token_urlsafe(32)


def store_oauth_state(state: str, discord_id: str, code_verifier: str) -> None:
    """Store OAuth state with Discord ID and code verifier."""
    oauth_states[state] = {
        "discord_id": discord_id,
        "code_verifier": code_verifier,
        "timestamp": time.time()
    }


def get_oauth_state(state: str) -> Optional[Dict]:
    """Retrieve OAuth state if valid and not expired (10 minute TTL)."""
    if state not in oauth_states:
        return None
    
    state_data = oauth_states[state]
    # Check if expired (10 minutes = 600 seconds)
    if time.time() - state_data["timestamp"] > 600:
        del oauth_states[state]
        return None
    
    return state_data


def delete_oauth_state(state: str) -> None:
    """Delete OAuth state after use."""
    oauth_states.pop(state, None)


def cleanup_expired_states() -> None:
    """Remove expired states (older than 10 minutes)."""
    current_time = time.time()
    expired = [
        state for state, data in oauth_states.items()
        if current_time - data["timestamp"] > 600
    ]
    for state in expired:
        del oauth_states[state]


def build_oauth_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scope: str = "openid profile"
) -> str:
    """Build FaceIT OAuth2 authorization URL with PKCE."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    
    base_url = "https://accounts.faceit.com"
    return f"{base_url}?{urlencode(params)}"

