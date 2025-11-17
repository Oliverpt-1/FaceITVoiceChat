"""Discord bot implementation using discord.py."""
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
import aiohttp
from app.config import DISCORD_TOKEN, DISCORD_GUILD_ID, FACEIT_API_KEY, FACEIT_API_URL, VC_CATEGORY_ID
from app.db import create_player_link, get_player_link_by_discord_id, init_db


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


@bot.tree.command(name="register", description="Register your Faceit nickname with the bot")
@app_commands.describe(faceit_nickname="Your Faceit nickname")
async def register_command(interaction: discord.Interaction, faceit_nickname: str):
    """Register a Discord user with their Faceit nickname."""
    await interaction.response.defer(ephemeral=True)
    
    # Check if user is already registered
    existing = get_player_link_by_discord_id(str(interaction.user.id))
    if existing:
        await interaction.followup.send(
            f"You are already registered as: **{existing['faceit_nickname']}**",
            ephemeral=True
        )
        return
    
    # Search for player on Faceit
    player_data = await search_faceit_player(faceit_nickname)
    
    if not player_data:
        await interaction.followup.send(
            f"Could not find Faceit player: **{faceit_nickname}**",
            ephemeral=True
        )
        return
    
    faceit_id = player_data.get("player_id")
    resolved_nickname = player_data.get("nickname", faceit_nickname)
    
    if not faceit_id:
        await interaction.followup.send(
            "Error: Could not retrieve Faceit ID from API response",
            ephemeral=True
        )
        return
    
    # Create player link
    try:
        create_player_link(
            discord_id=str(interaction.user.id),
            faceit_id=faceit_id,
            faceit_nickname=resolved_nickname
        )
        await interaction.followup.send(
            f"✅ Successfully registered as: **{resolved_nickname}** (ID: {faceit_id})",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error registering: {str(e)}",
            ephemeral=True
        )


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    print(f"Bot logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    await init_db()

