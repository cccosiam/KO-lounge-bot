import discord
from discord import app_commands
from discord.ext import commands

import aiosqlite
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials

import urllib
import re
import io
import aiohttp
import json
import random
from typing import Optional

from constants import (stats_cell, channels, ranks, num_players, SH_KEY, LOOKUP_KEY)

def get_creds():
    return ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json",
        [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    )
agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('./config.json', 'r') as cjson:
            self.config = json.load(cjson)

    def ordinal(self, n) -> str:
        try:
            n = round(float(n))
        except (ValueError, TypeError):
            return "-"
        
        remainder_100 = int(n) % 100
        remainder_10 = int(n) % 10
        if remainder_100 in (11, 12, 13):
            suffix = "th"
        elif remainder_10 == 1:
            suffix = "st"
        elif remainder_10 == 2:
            suffix = "nd"
        elif remainder_10 == 3:
            suffix = "rd"
        else:
            suffix = "th"

        return f"{n}{suffix}"

    @app_commands.command(name="stats", description="Displays player stats about the current season.")
    @app_commands.describe(player="Optional player name; defaults to you")
    @app_commands.checks.has_any_role("Administrator", "Updater", "Lounge Staff", "Player")
    async def stats(self, interaction: discord.Interaction, player: Optional[str] = None):
        """Displays stats about the current season."""
        # Placeholder for actual stats logic
        await interaction.response.defer()

        if interaction.guild is None or interaction.guild.id != self.config["server"]:
            await interaction.followup.send("You cannot use this command in this server!")
            return

        lookup_name = (player or interaction.user.display_name or interaction.user.name).strip()
        lookup_key = lookup_name.casefold()
        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("stats bot sheet")

        await botSheet.update_acell("B1", lookup_name)
        stat_cell = await botSheet.acell(stats_cell)
        raw_data = stat_cell.value
        if not raw_data or "," not in raw_data:
            await interaction.followup.send(f"Could not find stats for '{lookup_name}'.")
            return

        raw_split = raw_data.split(",")
        data = [item.strip() if item.strip() != "" else "-" for item in raw_split]

        if len(data) < 12:
            await interaction.followup.send("Error: Data incomplete.")
            return
        if data[0] == "error" and data[1] == "error":
            await interaction.followup.send(f"No stats found for '{lookup_name}'.")
            return

        name, mmr, peak, wr, rank, events, l10_diff, l10_wl, gain, loss, avg_place, l10_avg = data
        gain = f"+{gain}" if gain != "-" else "-"
        avg_place = f"{self.ordinal(avg_place)}" if avg_place != "-" else "-"
        #avg_place = "-"
        #l10_avg = "-"
        l10_avg = f"{self.ordinal(l10_avg)}" if l10_avg != "-" else "-"
        embed = discord.Embed(
            title="KO Lounge Preseason Stats",
            color=discord.Color.green(),
            description=f"**{name}**"
        )
        embed.add_field(name="MMR", value=mmr, inline=True)
        embed.add_field(name="Peak MMR", value=peak, inline=True)
        embed.add_field(name="Events Played", value=events, inline=True)
        embed.add_field(name="Win Rate", value=wr, inline=True)
        embed.add_field(name="Last 10 W/L", value=l10_wl, inline=True)
        embed.add_field(name="Last 10 +/-", value=l10_diff, inline=True)
        # embed.add_field(name="Avg. Placement", value=avg_place, inline=True)
        # embed.add_field(name="Last 10 Avg.", value=l10_avg, inline=True)
        # embed.add_field(name="", value="\u200b", inline=True)
        embed.add_field(name="Largest Gain", value=gain, inline=True)
        embed.add_field(name="Largest Loss", value=loss, inline=True)
        # embed.add_field(name="", value="\u200b", inline=True)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mmr", description="Look up a player's MMR from the bot sheet.")
    @app_commands.describe(player="Optional player name; defaults to you")
    @app_commands.checks.has_any_role("Administrator", "Updater", "Lounge Staff", "Player")
    async def mmr(self, interaction: discord.Interaction, player: Optional[str] = None):
        """Displays the MMR for the invoking player or a named player."""
        await interaction.response.defer()

        if interaction.guild is None or interaction.guild.id != self.config["server"]:
            await interaction.followup.send("You cannot use this command in this server!")
            return

        lookup_name = (player or interaction.user.display_name or interaction.user.name).strip()
        lookup_key = lookup_name.casefold()
        agc = await agcm.authorize()
        sh = await agc.open_by_key(LOOKUP_KEY)
        botSheet = await sh.worksheet("MMR")

        sheet_values = await botSheet.batch_get(["A:B"])
        for row in sheet_values[0]:
            if len(row) < 2:
                continue
            sheet_name = row[0].strip()
            if sheet_name.casefold() == lookup_key:
                embed = discord.Embed(title="MMR", color=discord.Color.blue())
                embed.add_field(name=sheet_name, value=row[1], inline=True)
                await interaction.followup.send(embed=embed)
                return

        embed = discord.Embed(title="MMR Lookup", color=discord.Color.red())
        embed.description = f"Could not find {lookup_name} in the MMR sheet."
        await interaction.followup.send(embed=embed)

async def setup(bot):
    cog = Stats(bot)
    guild = discord.Object(id=cog.config["server"])
    await bot.add_cog(cog, guild=guild)