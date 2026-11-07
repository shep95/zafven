"""Read a bounded uploaded image from a chat message or the message it replies to."""
import asyncio

import discord

from core.quote_images import MAX_IMAGE_BYTES, QuoteImageError, vision_image


async def image_from_message(message):
    candidates = list(message.attachments)
    if not candidates and message.reference and message.reference.message_id:
        source = message.reference.resolved
        if not isinstance(source, discord.Message):
            try:
                source = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                source = None
        if source is not None:
            candidates = list(source.attachments)
    image = next((a for a in candidates if (a.content_type or "").startswith("image/")), None)
    if image is None:
        return None
    if image.size > MAX_IMAGE_BYTES:
        raise QuoteImageError("That image is over 8 MB. Send a smaller image and I'll take a look.")
    return await asyncio.to_thread(vision_image, await image.read())
