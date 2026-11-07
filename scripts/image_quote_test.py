"""Offline vision routing and local quote-card rendering checks."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from PIL import Image
from core.brain_loader import load
from core.chat_images import image_from_message
from core.quote_images import render_quote, vision_image, QuoteImageError, MAX_IMAGE_BYTES
from cogs.quote_cog import QuoteCog
from cogs.chat_cog import ChatCog
from core.user_memory import empty_state


def png(color=(25, 145, 115), size=(250, 250)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


class ImageQuoteTests(unittest.IsolatedAsyncioTestCase):
    def attachment(self, data=None):
        data = data if data is not None else png()
        item = MagicMock(size=len(data), content_type="image/png")
        item.read = AsyncMock(return_value=data)
        return item

    def interaction(self):
        item = MagicMock()
        item.guild.id = 10
        item.user.display_name = "Caller"
        item.user.display_avatar.with_size.return_value.with_format.return_value.read = AsyncMock(return_value=png())
        item.response.defer = AsyncMock()
        item.followup.send = AsyncMock()
        return item

    def cog(self):
        bot = MagicMock()
        bot.gateway.narrate = AsyncMock(return_value="Small steps still move you forward.")
        return QuoteCog(bot)

    def test_simple_answer_and_fresh_expression_in_loaded_personality(self):
        for name in ("persona", "companion"):
            text = load(name).lower()
            self.assertIn("simple question, simple answer", text)
            self.assertIn("street", text)
            self.assertIn("creative", text if name == "persona" else text.replace("creativity", "creative"))
        self.assertIn("freshness of expression never justifies changing facts", load("persona"))

    def test_valid_image_is_normalized_for_vision(self):
        data = vision_image(png(size=(2200, 1000)))
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(max(image.size), 2000)

    def test_invalid_image_bytes_are_rejected(self):
        with self.assertRaises(QuoteImageError):
            vision_image(b"not an image")

    def test_oversized_upload_is_rejected(self):
        with self.assertRaises(QuoteImageError):
            vision_image(b"x" * (MAX_IMAGE_BYTES + 1))

    def test_pixel_limit_is_enforced(self):
        with patch("core.quote_images.MAX_PIXELS", 100):
            with self.assertRaises(QuoteImageError):
                vision_image(png())

    def test_render_produces_real_png_with_avatar(self):
        data = render_quote("Simple question. Simple answer.", "Sample User", png())
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1200, 900))
            self.assertEqual(image.getpixel((155, 765)), (25, 145, 115))

    def test_background_image_is_used(self):
        without = render_quote("Keep moving.", "User", png())
        with_image = render_quote("Keep moving.", "User", png(), png((220, 80, 20)))
        self.assertNotEqual(without, with_image)

    def test_quote_text_is_not_silently_truncated(self):
        with self.assertRaises(QuoteImageError):
            render_quote("x" * 701, "User")
        with self.assertRaises(QuoteImageError):
            render_quote("  ", "User")

    async def test_direct_chat_image_attachment_reaches_vision(self):
        message = MagicMock()
        message.attachments = [self.attachment()]
        data = await image_from_message(message)
        self.assertEqual(data[:2], b"\xff\xd8")

    async def test_chat_reply_can_read_referenced_image(self):
        message = MagicMock()
        message.attachments = []
        message.reference.message_id = 45
        message.reference.resolved = None
        message.channel.fetch_message = AsyncMock(return_value=MagicMock(attachments=[self.attachment()]))
        data = await image_from_message(message)
        self.assertIsNotNone(data)
        message.channel.fetch_message.assert_awaited_once_with(45)

    async def test_no_image_preserves_text_only_path(self):
        message = MagicMock(attachments=[], reference=None)
        self.assertIsNone(await image_from_message(message))

    async def test_image_only_chat_reply_passes_image_to_model(self):
        bot = MagicMock()
        bot.user.id = 1
        bot.gateway.narrate = AsyncMock(return_value="A green image.")
        bot.get_cog.return_value = None
        cog = ChatCog(bot)
        cog._context = AsyncMock(return_value="User uploaded an image")
        cog._send = AsyncMock()
        message = MagicMock()
        message.content = ""
        message.author.bot = False
        message.author.id = 2
        message.author.display_name = "User"
        message.guild.id = 10
        message.channel.id = 20
        message.channel.name = "general"
        message.channel.category = None
        message.channel.parent = None
        message.channel.permissions_for.return_value.send_messages = True
        message.mentions = []
        prior = MagicMock(spec=discord.Message)
        prior.author.id = 1
        message.reference.resolved = prior
        message.attachments = [self.attachment()]
        @asynccontextmanager
        async def typing():
            yield
        message.channel.typing = typing
        with patch("cogs.chat_cog.chat_memory.get_notes", AsyncMock(return_value=[])), \
             patch("cogs.chat_cog.user_memory.load", AsyncMock(return_value=empty_state())), \
             patch("cogs.chat_cog.user_memory.exchange", AsyncMock()), \
             patch("cogs.chat_cog.persona.get_directive", AsyncMock(return_value="")), \
             patch("cogs.chat_cog.culture.get_digest", AsyncMock(return_value="")), \
             patch("cogs.chat_cog.custombrain.get_text", AsyncMock(return_value="")), \
             patch("cogs.chat_cog.learned.relevant", AsyncMock(return_value=[])):
            await cog.on_message(message)
        kwargs = bot.gateway.narrate.call_args.kwargs
        self.assertTrue(kwargs["image_bytes"])
        self.assertEqual(kwargs["image_mime"], "image/jpeg")
        cog._send.assert_awaited_once()

    async def test_supplied_text_uses_callers_avatar_without_model_call(self):
        cog, interaction = self.cog(), self.interaction()
        await cog.make_card(interaction, "My exact words.", self.attachment())
        cog.bot.gateway.narrate.assert_not_awaited()
        self.assertIn("file", interaction.followup.send.call_args.kwargs)
        interaction.user.display_avatar.with_size.assert_called_once_with(256)

    async def test_image_only_quote_uses_vision_and_is_labeled(self):
        cog, interaction = self.cog(), self.interaction()
        await cog.make_card(interaction, image=self.attachment())
        kwargs = cog.bot.gateway.narrate.call_args.kwargs
        self.assertTrue(kwargs["image_bytes"])
        self.assertEqual(kwargs["image_mime"], "image/jpeg")
        file = interaction.followup.send.call_args.kwargs["file"]
        with Image.open(file.fp) as card:
            self.assertEqual(card.size, (1200, 900))

    async def test_real_message_quote_uses_original_authors_avatar(self):
        cog, interaction = self.cog(), self.interaction()
        source = MagicMock()
        source.author.display_name = "Original author"
        source.author.display_avatar.with_size.return_value.with_format.return_value.read = AsyncMock(return_value=png())
        await cog.make_card(interaction, "Original words.", source=source)
        source.author.display_avatar.with_size.assert_called_once_with(256)
        interaction.user.display_avatar.with_size.assert_not_called()

    async def test_inaccessible_source_channel_is_rejected(self):
        cog, interaction = self.cog(), self.interaction()
        channel = MagicMock()
        channel.permissions_for.return_value.view_channel = False
        interaction.guild.get_channel_or_thread.return_value = channel
        with self.assertRaises(QuoteImageError):
            await cog.source_message(interaction, "https://discord.com/channels/10/20/30")

    async def test_link_does_not_bypass_requesters_history_permissions(self):
        cog, interaction = self.cog(), self.interaction()
        channel = MagicMock()
        channel.permissions_for.return_value.view_channel = True
        channel.permissions_for.return_value.read_message_history = False
        interaction.guild.get_channel_or_thread.return_value = channel
        with self.assertRaises(QuoteImageError):
            await cog.source_message(interaction, "https://discord.com/channels/10/20/30")

    async def test_latest_question_is_preserved_when_history_exceeds_budget(self):
        bot = MagicMock()
        bot.user.id = 1
        cog = ChatCog(bot)
        cog._referenced = AsyncMock(return_value="")
        cog._cross_channel_sources = AsyncMock(return_value=[])
        message = MagicMock()
        message.content = "CURRENT UNIQUE QUESTION " + "q" * 3500
        message.author.display_name = "Asker"
        message.channel.name = "general"
        async def history(**kwargs):
            for i in range(12):
                item = MagicMock()
                item.content = f"Previous topic {i}: " + "old context " * 180
                item.author.id = 2
                item.author.display_name = "Member"
                yield item
        message.channel.history = history
        prompt = await cog._context(message)
        self.assertIn(message.content, prompt)
        self.assertEqual(prompt.count("CURRENT UNIQUE QUESTION"), 1)
        self.assertIn("Previous topic 0:", prompt)
        self.assertNotIn("Previous topic 11:", prompt)

    async def test_other_server_message_link_is_rejected(self):
        with self.assertRaises(QuoteImageError):
            await self.cog().source_message(self.interaction(), "https://discord.com/channels/11/20/30")

    async def test_custom_text_cannot_be_attributed_to_source_author(self):
        cog, interaction = self.cog(), self.interaction()
        await QuoteCog.quote.callback(cog, interaction, text="Invented words", message_link="https://discord.com/channels/10/20/30")
        self.assertNotIn("file", interaction.followup.send.call_args.kwargs)
        cog.bot.gateway.narrate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
