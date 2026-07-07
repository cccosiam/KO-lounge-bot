import discord
from discord.ext import commands
import json
import re
 
from constants import key_roles
 
# ── Configuration ─────────────────────────────────────────────────────────────
CHAT_RESTRICTED_ROLE_ID = key_roles["chat_restricted"]
MUTED_ROLE_ID = key_roles["muted"]
 
# Allowed phrases for restricted users (case-insensitive, stripped of whitespace)
# Add or remove entries as needed.
ALLOWED_PHRASES = {
    "/c",
    "/can",
    "/d",
    "/l",
    "gg",
    "wp",
    "glhf",
    "gl hf",
}
 
 
class Restrictions(commands.Cog):
 
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        with open('./config.json', 'r') as f:
            self.config = json.load(f)
 
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DMs, bots, and messages from other servers
        if not message.guild:
            return
        if message.author.bot:
            return
        if message.guild.id != self.config["server"]:
            return
 
        member = message.guild.get_member(message.author.id)
        if member is None:
            return
 
        role_ids = {r.id for r in member.roles}
 
        # Muted: no messages allowed at all
        if MUTED_ROLE_ID in role_ids:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            return
 
        # Chat Restricted: only allowed phrases permitted
        if CHAT_RESTRICTED_ROLE_ID in role_ids:
            content = message.content.strip().lower()
            if content not in ALLOWED_PHRASES:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass

 
 
async def setup(bot: commands.Bot):
    await bot.add_cog(Restrictions(bot))