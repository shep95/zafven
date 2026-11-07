"""One requested invitation DM, with actionable and non-sensitive failures."""
import io

import discord

import config


def dm_failure(error):
    code = getattr(error, "code", 0)
    status = getattr(error, "status", 0)
    label = f"Discord {code}" if code else f"HTTP {status}"
    if code in (50007, 50278) or isinstance(error, discord.Forbidden):
        reason = ("Discord refused this DM. Privacy settings, blocks, or Discord's delivery rules can prevent it. "
                  "The recipient can check DM settings for a server they share with Zafven; the bot cannot override them.")
    elif code == 50035:
        reason = "Discord rejected the message format. The bot owner should check the invitation configuration."
    elif status == 429 or status >= 500:
        reason = "Discord could not complete the DM request right now. Try again later."
    else:
        reason = "Discord could not complete this DM request. The bot owner can use this code to investigate."
    return f"{label}: {reason}"


async def send_invitation(user, body):
    """Keep long custom invitations intact without exceeding message content limits."""
    if len(body.encode("utf-16-le")) // 2 <= 2000:
        await user.send(body, allowed_mentions=discord.AllowedMentions.none())
        return
    with io.BytesIO(body.encode("utf-8")) as data:
        file = discord.File(data, filename="houseofasher-invitation.txt")
        try:
            await user.send("Your Houseofasher invitation is attached in full. Join here: " + config.HOUSEOFASHER_INVITE_URL,
                            file=file, allowed_mentions=discord.AllowedMentions.none())
        finally:
            file.close()
