"""Public bot installation, server-approved delegation, and promotion consent."""
import json

import discord

import config
from core.community_db import database
from core.welcome import render_invitation


def installation_url(application_id):
    # Administrative permissions are granted separately by each server as needed.
    permissions = discord.Permissions(view_channel=True, send_messages=True,
        read_message_history=True, embed_links=True, attach_files=True, connect=True, speak=True)
    return discord.utils.oauth_url(application_id, permissions=permissions,
                                   scopes=("bot", "applications.commands"))


def personalized_invitation(user):
    name = discord.utils.escape_markdown(user.display_name[:80]).replace("@", "＠")
    return (f"hey {name}, here's your invitation to #houseofasher, sent at your request.\n\n"
            + render_invitation(config.HOUSEOFASHER_INVITE_URL))


class PublicSettings:
    def __init__(self, db=database):
        self.db = db

    async def get(self, guild_id):
        def read(c):
            row = c.execute("SELECT payload FROM guild_settings WHERE guild_id=?", (str(guild_id),)).fetchone()
            return json.loads(row[0]) if row else {"promotion_channel": None, "owner_roles": []}
        return await self.db._call(read)

    async def change(self, guild_id, update):
        def write(c):
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT payload FROM guild_settings WHERE guild_id=?", (str(guild_id),)).fetchone()
            state = json.loads(row[0]) if row else {"promotion_channel": None, "owner_roles": []}
            update(state)
            c.execute("INSERT INTO guild_settings VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET payload=excluded.payload",
                      (str(guild_id), json.dumps(state)))
            return state
        return await self.db._call(write)

    async def consent(self, user_id, enabled):
        await self.db._call(lambda c: c.execute(
            "INSERT INTO promotion_consent VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET allowed=excluded.allowed",
            (str(user_id), int(enabled))))

    async def subscribed(self, user_id):
        def read(c):
            row = c.execute("SELECT allowed FROM promotion_consent WHERE user_id=?", (str(user_id),)).fetchone()
            return bool(row and row[0])
        return await self.db._call(read)

    async def subscribers(self):
        return await self.db._call(lambda c: {int(r[0]) for r in c.execute(
            "SELECT user_id FROM promotion_consent WHERE allowed=1")})


settings = PublicSettings()
