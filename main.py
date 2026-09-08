import discord
from discord.ext import commands
import json
import logging
import asyncio
import os
import sys

from cogs.Namechange import RequestButtonView, NameChange

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

class KOLoungeBot(commands.Bot):
    def __init__(self, config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix=["!", "/"], 
            case_insensitive=True, 
            intents=intents,
            help_command=None
        )
        self.config = config
        self.initial_extensions = [
            'cogs.Tables', 
            'cogs.Updating', 
            'cogs.Namechange',
            'cogs.Stats', 
            'cogs.Penalties', 
            'cogs.Verification',
            'cogs.Restrictions'
            ]

    async def setup_hook(self):
        """This runs before the bot connects to Discord. Ideal for loading cogs."""
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                logger.info(f"Successfully loaded extension: {extension}")
            except Exception as e:
                logger.error(f"Failed to load extension {extension}: {e}")
        
        self.add_view(RequestButtonView(self.cogs["NameChange"]))

        guild = discord.Object(id=self.config["server"])
        synced = await self.tree.sync(guild=guild)
        logger.info(f"Synced {len(synced)} application commands to guild {guild.id}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info("------")

    @commands.command(name="reset")
    @commands.has_any_role("Administrator")
    async def reset(self, ctx):
        """Restart the bot process with a clean runtime state."""
        await ctx.send("Restarting the bot...")
        await self.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    async def on_command_error(self, ctx, error):
        """Global error handler with safe attribute access."""
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingRequiredArgument):
            msg = f"Your command is missing an argument: `{error.param.name}`"
        
        elif isinstance(error, commands.CommandOnCooldown):
            msg = f"This command is on cooldown; try again in {error.retry_after:.0f}s"
        
        elif isinstance(error, commands.MissingAnyRole):
            roles = ", ".join(error.missing_roles)
            msg = f"You need one of these roles: `{roles}`"
        
        elif isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(error.missing_perms)
            msg = f"I need the following permissions: `{perms}`"
        
        elif isinstance(error, commands.BadArgument):
            msg = f"Bad Argument Error: `{error}`"
        
        elif isinstance(error, commands.NoPrivateMessage):
            msg = "You can't use this command in DMs!"
        
        elif isinstance(error, commands.CheckFailure):
            msg = "You do not have permission to run this command."
        
        else:
            logger.error(f"Unhandled error in {ctx.command}: {error}", exc_info=error)
            msg = "An unexpected error occurred."

        await ctx.send(msg, delete_after=10)

async def main():
    try:
        with open('./config.json', 'r') as cjson:
            config = json.load(cjson)
    except FileNotFoundError:
        logger.critical("config.json not found! Please ensure it exists in the root directory.")
        return

    bot = KOLoungeBot(config)
    
    async with bot:
        await bot.start(config["token"])

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
