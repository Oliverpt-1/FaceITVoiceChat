# Webhook Implementation Notes

## What Was Made Up (and Removed)

### ❌ Removed Pydantic Models
The Pydantic models (`FaceitPlayer`, `FaceitFaction`, `MatchObjectCreatedPayload`, etc.) were **assumptions** about the payload structure. They've been removed since we don't know the actual Faceit webhook payload format.

### ⚠️ Unknown Payload Structure
The webhook handler now:
- Logs the **full payload** for debugging
- Tries multiple patterns to extract `match_id` and player IDs
- Handles gracefully if structure doesn't match expectations

## What's Needed

### 1. `search_faceit_player` Function
**Status: ✅ NEEDED**

This function is **required** for the `/register` command:
- User runs `/register <faceit_nickname>`
- Bot calls Faceit API to search for that nickname
- Gets the `player_id` (Faceit ID)
- Stores mapping: `discord_id` → `faceit_id` in database

**Without this function, users cannot register!**

### 2. Webhook Payload Discovery
**Status: ⚠️ NEEDS TESTING**

Once you set up the Faceit webhook and receive your first webhook:
1. Check the logs - the full payload will be printed
2. Update `handle_match_created()` to match the actual structure
3. The current code tries multiple patterns but may need adjustment

### 3. Player ID Extraction
The current code tries these patterns:
- `entity.teams.faction1.roster[].player_id`
- `entity.players[].player_id`
- `payload.players[].player_id`

**You'll need to verify which pattern (if any) matches the actual payload.**

## Next Steps

1. **Deploy the bot** and set up the Faceit webhook
2. **Trigger a test match** in your Faceit Hub
3. **Check the logs** for the webhook payload structure
4. **Update the payload parsing** in `handle_match_created()` based on actual structure
5. **Test the flow**: Match created → VC created → Users moved → Match finished → VC deleted

## Logging

The webhook handler now logs:
- Full payload received (for debugging)
- Event type extracted
- Match ID extracted
- Player IDs found
- Discord users mapped
- VC creation/deletion

Use these logs to debug and adjust the payload parsing.

