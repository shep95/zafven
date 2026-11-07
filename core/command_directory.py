"""Paginated help generated from actual registered command objects."""
import discord
from discord import app_commands

PAGE_SIZE = 10


def directory_entries(tree, guild=None):
    # Guild definitions shadow globals in Discord; show each effective root once.
    roots = {}
    for scope in (None, guild) if guild is not None else (None,):
        for command in tree.get_commands(guild=scope):
            kind = command.to_dict(tree).get("type", 1)
            roots[(kind, command.name)] = command
    entries = []

    def visit(command, parent_guild_only=False):
        server_only = parent_guild_only or getattr(command, "guild_only", False)
        if guild is None and server_only:
            return
        if isinstance(command, app_commands.Group):
            for child in command.commands:
                visit(child, server_only)
        elif isinstance(command, app_commands.ContextMenu):
            target = "message" if command.type is discord.AppCommandType.message else "user"
            entries.append((f"Apps → {command.name}", f"Right-click a {target} and open Apps."))
        else:
            params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in command.parameters)
            value = (f"`/{command.qualified_name}{' ' + params if params else ''}`\n"
                     f"{command.description}")
            if server_only:
                value += "\nServer command."
            permissions = command.default_permissions
            if permissions and permissions.value:
                names = ", ".join(name.replace("_", " ") for name, enabled in permissions if enabled)
                value += f"\nDefault server permissions: {names}."
            entries.append((f"/{command.qualified_name}", value[:1024]))

    for command in roots.values():
        visit(command)
    return sorted(entries, key=lambda row: row[0].casefold())


class CommandPages(discord.ui.View):
    def __init__(self, entries, user_id, page=1):
        super().__init__(timeout=180)
        self.entries = entries
        self.user_id = user_id
        self.pages = [[]]
        size = 0
        for entry in entries:
            length = len(entry[0]) + len(entry[1])
            if self.pages[-1] and (len(self.pages[-1]) >= PAGE_SIZE or size + length > 5400):
                self.pages.append([])
                size = 0
            self.pages[-1].append(entry)
            size += length
        self.total = len(self.pages)
        self.page = max(1, min(page, self.total))
        self._buttons()

    def _buttons(self):
        self.previous.disabled = self.page <= 1
        self.next_page.disabled = self.page >= self.total

    def embed(self):
        embed = discord.Embed(title="Zafven commands", color=discord.Color.dark_purple(),
            description="The current command list. Required options use <brackets>; optional options use [brackets].\n"
                        "Some commands need server permissions or configured services. Mention Zafven for ordinary chat.")
        for name, description in self.pages[self.page - 1]:
            embed.add_field(name=name, value=description, inline=False)
        if not self.entries:
            embed.description = "No commands are available in this context. Try /commands in a server."
        embed.set_footer(text=f"Page {self.page}/{self.total} · {len(self.entries)} commands · /commands page:<number> · buttons last 3 minutes")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Open your own list with /commands.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(1, self.page - 1)
        self._buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total, self.page + 1)
        self._buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


async def send_directory(bot, interaction, page=1):
    view = CommandPages(directory_entries(bot.tree, interaction.guild), interaction.user.id, page)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
