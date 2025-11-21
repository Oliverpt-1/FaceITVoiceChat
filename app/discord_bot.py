"""Discord bot implementation using discord.py."""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
import aiohttp
from app.config import (
    DISCORD_TOKEN, DISCORD_GUILD_ID, FACEIT_API_KEY, FACEIT_API_URL, VC_CATEGORY_ID,
    FACEIT_CLIENT_ID, FACEIT_REDIRECT_URI
)
from app.db import create_player_link, get_player_link_by_discord_id, init_db
from app.auth_faceit import (
    generate_code_verifier, generate_code_challenge, generate_state,
    store_oauth_state, build_oauth_url
)


# In-memory cache for active matches (match_id -> voice_channel_id)
active_match_cache: dict[str, str] = {}


class FaceitBot(commands.Bot):
    """Custom bot class for Faceit integration."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Sync commands to guild (faster than global)
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            # Global sync (slower, up to 1 hour to propagate)
            await self.tree.sync()


bot = FaceitBot()


async def search_faceit_player(nickname: str) -> Optional[dict]:
    """
    Search for a Faceit player by nickname using Faceit REST API.
    
    Returns player data including player_id, or None if not found.
    """
    if not FACEIT_API_KEY:
        return None
    
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    url = f"{FACEIT_API_URL}/search/players"
    params = {"nickname": nickname, "limit": 1}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                items = data.get("items", [])
                if items:
                    return items[0]  # Returns player object with player_id
            return None


async def create_private_vc_and_move_users(
    guild: discord.Guild,
    user_ids: List[int],
    match_id: str,
    faction: str,
    category_id: Optional[int] = None
) -> Optional[discord.VoiceChannel]:
    """
    Create a private voice channel for a specific faction and move users into it.
    
    Args:
        guild: Discord guild/server
        user_ids: List of Discord user IDs to move
        match_id: Match ID for channel naming
        faction: The faction (e.g., 'faction1', 'faction2') for channel naming.
        category_id: Optional category ID to create channel in
    
    Returns:
        Created VoiceChannel or None if failed
    """
    try:
        # Get category if provided
        category = None
        if category_id:
            category = guild.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                category = None
        
        # Create private voice channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        
        # Allow all users in the match to see the channel
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True
                )
        
        channel_name = f"Match {match_id[:8]}-{faction}" # Updated channel naming
        vc = await guild.create_voice_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )
        
        # Move users into the voice channel
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member and member.voice:
                try:
                    await member.move_to(vc)
                except discord.HTTPException:
                    # User might not be in a voice channel, skip
                    pass
        
        return vc
    
    except Exception as e:
        print(f"Error creating VC: {e}")
        return None


async def cleanup_vc(guild: discord.Guild, voice_channel_id: str) -> None:
    """Deletes a voice channel and moves any remaining users out."""
    try:
        channel = guild.get_channel(int(voice_channel_id))
        if channel and isinstance(channel, discord.VoiceChannel):
            # Move users out of VC before deleting (optional)
            for member in channel.members:
                try:
                    await member.move_to(None)  # Disconnect
                except Exception as move_error:
                    print(f"Could not move user {member.id} from VC {voice_channel_id}: {move_error}")
            
            # Delete VC
            await channel.delete()
            print(f"Deleted VC {voice_channel_id}")
    except Exception as e:
        print(f"Error cleaning up VC {voice_channel_id}: {e}")


@bot.tree.command(name="verify", description="Verify your FaceIT account using OAuth2")
async def verify_command(interaction: discord.Interaction):
    """Generate OAuth2 URL for FaceIT account verification."""
    await interaction.response.defer(ephemeral=True)
    
    # Check if OAuth config is available
    if not FACEIT_CLIENT_ID or not FACEIT_REDIRECT_URI:
        await interaction.followup.send(
            "❌ OAuth configuration is missing. Please contact the bot administrator.",
            ephemeral=True
        )
        return
    
    # Check if user is already registered
    existing = get_player_link_by_discord_id(str(interaction.user.id))
    if existing:
        await interaction.followup.send(
            f"You are already verified as: **{existing['faceit_nickname']}**\n"
            f"If you want to link a different account, please contact an administrator.",
            ephemeral=True
        )
        return
    
    try:
        # Generate PKCE values
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        
        # Generate state for CSRF protection
        state = generate_state()
        
        # Store state with Discord ID and code verifier
        store_oauth_state(state, str(interaction.user.id), code_verifier)
        
        # Build OAuth URL
        print(f"[VERIFY] Building OAuth URL with redirect_uri: {FACEIT_REDIRECT_URI}")
        oauth_url = build_oauth_url(
            client_id=FACEIT_CLIENT_ID,
            redirect_uri=FACEIT_REDIRECT_URI,
            code_challenge=code_challenge,
            state=state
        )
        print(f"[VERIFY] Generated OAuth URL: {oauth_url}")
        
        # Send OAuth URL to user
        await interaction.followup.send(
            f"✅ Click the link below to verify your FaceIT account:\n\n"
            f"🔗 [**Verify with FaceIT**]({oauth_url})\n\n"
            f"⚠️ This link will expire in 10 minutes.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error generating verification link: {str(e)}",
            ephemeral=True
        )


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    print(f"Bot logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    await init_db()

