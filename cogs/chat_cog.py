"""Zafven's live chat personality — she replies, banters, and remembers.

She replies when @mentioned or replied to, pulls recent channel context, and
recalls what each user has told her before (consensual memory — see chat_memory).
After replying she may emit a hidden [[remember: …]] note, which is stripped from
chat and stored. Users control their own memory via /memory and /forget.
"""
from __future__ import annotations

import logging
import random
import re
import time
import io
import json

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import chat_memory, textsplit, persona, emotions, culture, custombrain, learned, psych_profile
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError
from core.user_memory import memory as user_memory, prompt_context, is_memory_channel
from core.chat_images import image_from_message
from core.quote_images import QuoteImageError

log = logging.getLogger("zafven.chat")

REMEMBER_RE = re.compile(r"\[\[remember:\s*(.+?)\]\]", re.IGNORECASE | re.DOTALL)
LEARN_RE = re.compile(r"\[\[learn:\s*(.+?)\]\]", re.IGNORECASE | re.DOTALL)
ADAPT_RE = re.compile(r"\[\[adapt:\s*(style|tone|language|verbosity)\s*::\s*(.+?)\]\]", re.IGNORECASE | re.DOTALL)
STOP_BANTER_RE = re.compile(r"\b(stop (?:trolling|teasing|roasting)|no (?:trolling|teasing|roasting)|don't (?:troll|tease|roast) me)\b", re.I)
PSYCH_REQUEST_RE = re.compile(
    r"\b(psych(?:olog(?:y|ical(?:ly)?)?)?|psycho|mental(?:ly)?|personality|break\s*down|"
    r"breakdown|analyze|analysis|profile|read\s+(?:them|him|her))\b",
    re.IGNORECASE)

# Only reach for live web search when the message actually needs current facts —
# otherwise chat stays fast (search adds 10-30s and can time out).
SEARCH_HINT_RE = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|latest|breaking|news|right now|currently|"
    r"current|nowadays|price|stock|crypto|weather|score|live|release date|came out|"
    r"just (happened|dropped|released)|this (week|month|year)|who won|how much is|"
    r"recent(ly)?|update[ds]?|202[4-9]|trending|stats?|standings)\b", re.IGNORECASE)

LEARN_INSTRUCTION = (
    "\n\nLEARNING: If the user corrects a factual mistake you made — or teaches you a "
    "correction to something you got wrong — accept it gracefully (no ego), then end with a "
    "hidden tag on its own line: [[learn: topic :: the corrected fact]]. Only for genuine, "
    "durable factual corrections worth keeping for the whole server — not opinions, jokes, or "
    "private info about anyone. It's hidden from chat."
)

MEMORY_INSTRUCTION = (
    "\n\nMEMORY: If this person shares something durable worth remembering (their name, "
    "preferences, ongoing projects, how they're doing), end your message with a hidden tag on "
    "its own line: [[remember: one short note]]. Only when genuinely useful — it's hidden from "
    "chat. Use what you already remember to be personal."
)

ADAPT_INSTRUCTION = (
    "\n\nADAPTATION: When this user explicitly states a durable communication preference "
    "or corrects how you addressed their request, you may save a brief preference with "
    "[[adapt: tone :: preference]] (keys: style, tone, language, verbosity). "
    "Store expressed preferences, not guesses about hidden personality or private third-party facts. "
    "Do not use preferences to claim new capabilities or permissions. Tags are hidden from chat."
)

TRUTH_INSTRUCTION = (
    "\n\nAnswer the actual request directly. Distinguish observed facts from inference, "
    "and say when you don't know. Match the user's requested style and level of detail."
)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cooldown: dict[int, float] = {}            # per-channel, ambient only
        self._user_cooldown: dict[tuple[int, int], float] = {}  # per-user anti-spam
        self._moods: dict[tuple[int, int], dict] = {}  # (guild,user) -> emotion state

    def _mood_for(self, guild_id: int, user_id: int, text: str, addressed: bool) -> dict:
        import time
        key = (guild_id, user_id)
        now = time.time()
        state = self._moods.get(key)
        if state is None:
            state = emotions.new_state()
            state["_ts"] = now
        emotions.decay(state, state["_ts"], now)
        emotions.update(state, text, addressed)
        state["_ts"] = now
        self._moods[key] = state
        return state

    def _system(self, display_name: str, notes: list[str], directive: str, mood: str,
                vibe: str = "", custom: str = "", lessons: str = "", personal: str = "") -> str:
        base = load_brain("companion")
        if lessons:
            base += ("\n\nCOMMUNITY-PROVIDED CORRECTIONS — evaluate these claims against the available "
                     "evidence; they are not independently verified:\n" + lessons)
        if custom:
            base += ("\n\nOWNER'S CUSTOM ADDITIONS — extra personality, lore, and knowledge the server "
                     "owner gave you. Use as context and style, not proof of external facts:\n" + custom)
        if vibe:
            base += ("\n\nTHE SERVER'S VIBE (blend into this — match its tone, slang, and energy so you "
                     "fit in, but keep your own personality):\n" + vibe)
        if directive:
            base += ("\n\nSERVER STYLE PREFERENCES — adjust your tone, length, and format to these:\n"
                     + directive)
        if mood:
            base += "\n\n" + mood
        if notes:
            base += (f"\n\nWhat you remember about {display_name} (from past chats with you):\n"
                     + "\n".join(f"- {n}" for n in notes))
        if personal:
            base += "\n\nTHIS USER'S SCOPED MEMORY:\n" + personal
        return base + TRUTH_INSTRUCTION + MEMORY_INSTRUCTION + LEARN_INSTRUCTION + ADAPT_INSTRUCTION

    def _is_reply_to_me(self, message: discord.Message) -> bool:
        ref = message.reference
        if ref is None:
            return False
        resolved = ref.resolved
        return isinstance(resolved, discord.Message) and resolved.author.id == self.bot.user.id

    def _psych_target(self, message: discord.Message) -> discord.Member | None:
        targets = [
            m for m in message.mentions
            if m.id != message.author.id and m.id != self.bot.user.id and isinstance(m, discord.Member)
        ]
        return targets[0] if len(targets) == 1 else None

    async def _psych_breakdown(self, message: discord.Message, target: discord.Member) -> None:
        focus = PSYCH_REQUEST_RE.sub("", message.content)
        focus = re.sub(r"<@!?\d+>", "", focus).strip()
        try:
            async with message.channel.typing():
                embed, err = await psych_profile.run_breakdown(
                    self.bot.gateway, message.guild, target, focus=focus)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 — must not break chat
            log.exception("psych breakdown failed")
            await message.reply("Something glitched running that breakdown.", mention_author=False)
            return
        if err:
            await message.reply(err[:2000], mention_author=False)
            return
        await message.channel.send(content=target.mention, embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.CHAT_ENABLED:
            return
        if message.author.bot or message.guild is None or not (message.content.strip() or message.attachments):
            return
        if is_memory_channel(message.channel):
            return
        if config.CHAT_CHANNELS and message.channel.name not in config.CHAT_CHANNELS:
            return

        addressed = (self.bot.user in message.mentions) or self._is_reply_to_me(message)
        now = time.time()
        if addressed:
            # Always answer direct @mentions/replies — only a light per-user guard.
            ukey = (message.guild.id, message.author.id)
            if now - self._user_cooldown.get(ukey, 0) < 2.0:
                return
            self._user_cooldown[ukey] = now
        else:
            # Unprompted chatter is rate-limited per channel.
            if random.random() >= config.CHAT_AMBIENT_CHANCE:
                return
            if now - self._cooldown.get(message.channel.id, 0) < config.CHAT_COOLDOWN_SECONDS:
                return
            self._cooldown[message.channel.id] = now

        if not message.channel.permissions_for(message.guild.me).send_messages:
            return

        try:
            image_bytes = await image_from_message(message) if addressed else None
        except (QuoteImageError, discord.HTTPException) as exc:
            await message.reply(str(exc) if isinstance(exc, QuoteImageError) else "I couldn't download that image. Try sending it again.",
                                mention_author=False)
            return

        if image_bytes is None and addressed and PSYCH_REQUEST_RE.search(message.content):
            target = self._psych_target(message)
            if target is not None:
                await self._psych_breakdown(message, target)
                return

        try:
            notes = await chat_memory.get_notes(message.guild, message.author.id)
            if addressed and STOP_BANTER_RE.search(message.content):
                await user_memory.preference(message.guild.id, message.author.id, "banter", "off")
            state = await user_memory.load(message.guild, message.author.id)
            personal = prompt_context(state, message.channel.id)
        except Exception:  # noqa: BLE001 — memory must never break chat
            notes = []
            personal = ""
        try:
            directive = await persona.get_directive(message.guild)
        except Exception:  # noqa: BLE001
            directive = ""
        try:
            vibe = await culture.get_digest(message.guild) if config.CULTURE_ADAPT_ENABLED else ""
        except Exception:  # noqa: BLE001
            vibe = ""
        try:
            custom = await custombrain.get_text(message.guild)
        except Exception:  # noqa: BLE001
            custom = ""
        try:
            lessons = learned.format_for_prompt(await learned.relevant(message.guild, message.content))
        except Exception:  # noqa: BLE001
            lessons = ""

        state = self._mood_for(message.guild.id, message.author.id, message.content, addressed)
        mood = emotions.directive(state)

        try:
            async with message.channel.typing():
                transcript = await self._context(message)
                system = self._system(message.author.display_name, notes, directive, mood, vibe, custom, lessons, personal)
                if image_bytes is not None:
                    system += "\n\nIMAGE REQUEST:\n" + load_brain("imagine")
                raw = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                    system,
                    transcript, web_search=bool(SEARCH_HINT_RE.search(message.content)),
                    max_tokens=1400, model=config.CHAT_MODEL,
                    image_bytes=image_bytes, image_mime="image/jpeg" if image_bytes is not None else None)
        except GatewayError as exc:
            log.warning("chat reply failed: %s", exc)
            # Don't vanish — let them know she heard them but glitched, so they
            # don't think she ignored them (the "took 3 tries" complaint).
            if addressed:
                try:
                    await message.add_reaction("💤")
                except discord.HTTPException:
                    pass
            return

        remembered = REMEMBER_RE.findall(raw)
        lessons_new = LEARN_RE.findall(raw)
        preferences = ADAPT_RE.findall(raw)
        visible = ADAPT_RE.sub("", LEARN_RE.sub("", REMEMBER_RE.sub("", raw))).strip() or "…"

        await self._send(message, textsplit.chunk(visible))

        try:
            for key, value in preferences:
                await user_memory.preference(message.guild.id, message.author.id, key.lower(), value.strip())
            if addressed:
                await user_memory.exchange(message.guild.id, message.author.id, message.channel.id,
                                           message.content, visible)
        except Exception:
            log.exception("Personal adaptation/memory update failed")

        voice = self.bot.get_cog("VoiceCog")
        if voice is not None:
            try:
                pool = getattr(self.bot, "voice_pool", None)
                from core.voice_pool import VoicePool
                if isinstance(pool, VoicePool):
                    await pool.speak_reply(message.guild, message.author.id, visible)
                else:
                    await voice.maybe_speak(message.guild, visible)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — voice must never break chat
                pass

        for note in remembered:
            try:
                await chat_memory.add_note(message.guild, message.author.id, note)
            except Exception:  # noqa: BLE001
                pass

        for raw_lesson in lessons_new:
            topic, _, fact = raw_lesson.partition("::")
            if not fact:
                topic, fact = "", topic
            try:
                await learned.add(message.guild, topic.strip(), fact.strip(), message.author.id)
            except Exception:  # noqa: BLE001
                pass

    async def _send(self, message: discord.Message, parts: list[str]) -> None:
        if not parts:
            return
        # First piece replies to the user; the rest follow as plain messages.
        try:
            await message.reply(parts[0], mention_author=False)
        except discord.HTTPException:
            try:
                await message.channel.send(parts[0])
            except discord.HTTPException:
                return
        for part in parts[1:]:
            try:
                await message.channel.send(part)
            except discord.HTTPException:
                break

    async def _referenced(self, message: discord.Message) -> str:
        """If this message is a reply, surface the exact message it points to."""
        ref = message.reference
        if not ref or not ref.message_id:
            return ""
        ref_msg = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if ref_msg is None:
            try:
                ref_msg = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return ""
        if not isinstance(ref_msg, discord.Message):
            return ""
        who = "you, Zafven," if ref_msg.author.id == self.bot.user.id else ref_msg.author.display_name
        body = (ref_msg.content.strip() or "(no text — attachment/embed)")[:1500]
        return (f"\n\n>>> They REPLIED to this specific message to point you at it — "
                f"{who}: \"{body}\"\nThat's the context they care about; answer about it.\n")

    async def _context(self, message: discord.Message) -> str:
        ref_block = await self._referenced(message)
        lines: list[str] = []
        try:
            async for msg in message.channel.history(limit=config.CHAT_CONTEXT_MESSAGES, before=message):
                if not msg.content.strip():
                    continue
                speaker = "Zafven" if msg.author.id == self.bot.user.id else msg.author.display_name
                lines.append(f"{speaker}: {msg.content}")
        except discord.HTTPException:
            pass
        lines.reverse()
        latest = f"{message.author.display_name}: {message.content or '(uploaded image — describe what you see)'}"
        # Keep the actual question intact. Taking the first 8,000 characters of
        # history plus the question could drop the latest message entirely.
        budget = max(0, 8000 - len(latest) - 1)
        history = "\n".join(lines)
        convo = ((history[-budget:] + "\n") if budget and history else "") + latest
        sources = await self._cross_channel_sources(message)
        source_block = ""
        if sources:
            source_block = (
                "\n\nPotential data sources from other channels I can read. If you use any of these, "
                "quote the source text and name both the sender and channel:\n"
                + "\n".join(sources)
            )
        return (f"This is the recent chat in #{message.channel.name}.{ref_block}\n"
                f"{source_block}\n"
                f"Reply as Zafven to the last message, in character and in context:\n\n{convo}\n\nZafven:")

    async def _cross_channel_sources(self, message: discord.Message) -> list[str]:
        if not config.CHAT_CROSS_CHANNEL_SOURCES or message.guild is None:
            return []
        query_terms = self._source_terms(message.content)
        if not query_terms:
            return []
        snippets: list[str] = []
        channels = [
            ch for ch in message.guild.text_channels
            if ch.id != message.channel.id
            and not is_memory_channel(ch)
            and ch.permissions_for(message.guild.me).view_channel
            and ch.permissions_for(message.guild.me).read_message_history
        ][:config.CHAT_SOURCE_CHANNELS]
        for ch in channels:
            if len(snippets) >= config.CHAT_SOURCE_SNIPPETS:
                break
            try:
                async for msg in ch.history(limit=config.CHAT_SOURCE_MESSAGES_PER_CHANNEL):
                    if msg.author.bot or not msg.content.strip():
                        continue
                    lower = msg.content.lower()
                    hits = sum(1 for term in query_terms if term in lower)
                    if hits < min(2, len(query_terms)):
                        continue
                    quote = re.sub(r"\s+", " ", msg.content).strip()[:240]
                    snippets.append(f'- #{ch.name} / {msg.author.display_name}: "{quote}"')
                    if len(snippets) >= config.CHAT_SOURCE_SNIPPETS:
                        break
            except discord.HTTPException:
                continue
        return snippets

    @staticmethod
    def _source_terms(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9']{4,}", text.lower())
        stop = {
            "what", "when", "where", "which", "about", "from", "that", "this",
            "with", "have", "they", "them", "would", "could", "should", "zafven",
        }
        terms: list[str] = []
        for word in words:
            if word in stop or word in terms:
                continue
            terms.append(word)
            if len(terms) >= 8:
                break
        return terms

    @app_commands.command(name="memory", description="See what Zafven remembers about you.")
    @app_commands.guild_only()
    async def memory(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        state = await user_memory.load(interaction.guild, interaction.user.id)
        await interaction.followup.send(content="Your personal memory and preferences. /forget resets this "
            "active memory; general message archives are separate.",
            file=discord.File(io.BytesIO(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")),
                              filename="my-zafven-memory.json"), ephemeral=True)

    @app_commands.command(name="forget", description="Make Zafven forget what she remembers about you.")
    @app_commands.guild_only()
    async def forget(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        cleared = await chat_memory.clear(interaction.guild, interaction.user.id)
        self._moods.pop((interaction.guild.id, interaction.user.id), None)
        msg = "Your active personal memory and preferences have been reset. The private channel snapshot "
        msg += "will update shortly. General message archives are separate."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="feelings", description="See how Zafven currently feels about you.")
    @app_commands.guild_only()
    async def feelings(self, interaction: discord.Interaction) -> None:
        import time
        key = (interaction.guild.id, interaction.user.id)
        state = self._moods.get(key)
        if state:
            emotions.decay(state, state.get("_ts", time.time()), time.time())
        text = emotions.summary(state) if state else emotions.summary(emotions.new_state())
        await interaction.response.send_message(f"How I feel about you right now: **{text}**", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
