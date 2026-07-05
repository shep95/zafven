"""Psychological breakdown of a member from their public messages."""
from __future__ import annotations

import discord

import config
from core import member_messages, vibe
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError


def opted_out(member: discord.Member) -> bool:
    optout = set(config.PROFILE_OPTOUT_ROLES)
    return any(r.name.lower() in optout for r in member.roles)


async def run_breakdown(gateway, guild: discord.Guild, member: discord.Member, *,
                        focus: str = "") -> tuple[discord.Embed | None, str | None]:
    """Return (embed, None) on success or (None, error_message) on failure."""
    if member.bot:
        return None, "Bots don't have a psyche to read."
    if opted_out(member):
        return None, f"🔒 {member.display_name} has opted out of readings."

    messages = await member_messages.collect(guild, member)
    if len(messages) < 10:
        return None, (
            f"I couldn't find enough of {member.display_name}'s recent messages "
            "(need ~10 public posts)."
        )

    result = vibe.analyze(messages)
    s = result.stats
    facts = (
        f"Member: {member.display_name}\n"
        f"Archetype (surface): {result.archetype}\n"
        f"Messages analyzed: {s.messages} | avg words/msg: {s.words / max(s.messages, 1):.1f}\n"
        f"Emoji: {s.emoji} (top: {', '.join(e for e, _ in s.top_emoji[:3]) or 'none'})\n"
        f"Questions: {s.questions} | exclamations: {s.exclamations} | links: {s.links}\n"
        f"Favorite words: {', '.join(w for w, _ in s.top_words[:5]) or 'n/a'}"
    )
    samples = "\n".join(f"- {m[:220]}" for m in messages[:30])
    focus_line = f"\nThe asker wants you to focus on: {focus.strip()}\n" if focus.strip() else ""
    user_prompt = (
        f"Psychological breakdown of {member.display_name} from their public Discord messages.\n"
        f"{focus_line}\n"
        f"STATS:\n{facts}\n\n"
        f"SAMPLE MESSAGES (their own words, recent):\n{samples}\n\n"
        "Give the full psychological breakdown per your rules."
    )

    try:
        reading = await gateway.narrate(
            persona_system_prompt("profile"), user_prompt, web_search=False, max_tokens=1400)
    except GatewayError:
        return None, "🔌 The reading engine is unreachable right now. Try again shortly."

    embed = discord.Embed(
        title=f"🧠 Psychological Breakdown — {member.display_name}",
        description=reading[:4000],
        color=discord.Color.dark_purple(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="From public messages only • opt out: no-readings role")
    return embed, None
