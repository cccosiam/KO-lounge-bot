import discord
from discord import app_commands
from discord.ext import commands

import asyncio
import aiosqlite
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials

import io
import aiohttp
import json
from datetime import date
from typing import Optional

from constants import (
    key_channels, key_roles, channels, ranks,
    num_players, SH_KEY, LOOKUP_KEY,
    rowcol_to_a1, get_strike_info,
    pen_row, pen_cols, pen_channel,
)

import logging
logger = logging.getLogger('discord')

# ── Configuration ─────────────────────────────────────────────────────────────
PENALTY_AMOUNT  = 50          # Fixed MMR penalty amount
STAFF_ROLES     = ("Administrator", "Lounge Staff")

# ── Google Sheets ─────────────────────────────────────────────────────────────
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


# ── Shared sheet helpers ──────────────────────────────────────────────────────

async def _lookup_player(playername: str) -> Optional[dict]:
    """
    Looks up a player by name using the Bot sheet's pen_row/pen_cols mechanism.
    Returns a dict with player data or None if not found.
    """
    agc = await agcm.authorize()
    sh  = await agc.open_by_key(SH_KEY)
    bot_sheet = await sh.worksheet("Bot")

    await bot_sheet.batch_update([
        {'range': rowcol_to_a1(pen_row, pen_cols[0]), 'values': [[playername]]},
        {'range': rowcol_to_a1(pen_row, pen_cols[1]), 'values': [[PENALTY_AMOUNT]]},
    ])

    info = await bot_sheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
    data = info[0][0]

    if data[2] == "#N/A":
        return None

    return {
        "bot_sheet":  bot_sheet,
        "sh":         sh,
        "data":       data,
        "pHrow":      data[2],
        "strikeRow":  data[1],
        "newRow":     data[0],
        "goodName":   data[8],
        "pens":       int(data[3]),
        "mmr":        data[7],
        "strikes":    data[4:7],
    }


async def _apply_penalty(playername: str, reason: str = "") -> dict:
    """
    Applies a fixed MMR penalty to a player.
    Returns a result dict with keys: success, goodName, old_mmr, new_mmr, error.
    """
    result = {"success": False, "goodName": playername, "old_mmr": 0, "new_mmr": 0, "error": ""}

    player = await _lookup_player(playername)
    if player is None:
        result["error"] = f"Player `{playername}` not found on the sheet."
        return result

    mmr = player["mmr"]
    if mmr == "Placement":
        result["error"] = f"Player `{player['goodName']}` needs Placement MMR before receiving a penalty."
        return result

    agc   = await agcm.authorize()
    sh    = await agc.open_by_key(SH_KEY)
    p_history = await sh.worksheet("Player History")

    amount  = PENALTY_AMOUNT
    old_mmr = int(mmr)
    while old_mmr - amount < 0:
        amount -= 1

    new_pens = player["pens"] + amount
    await p_history.update_cell(int(player["pHrow"]), 4, new_pens)

    result.update({
        "success":  True,
        "goodName": player["goodName"],
        "old_mmr":  old_mmr,
        "new_mmr":  old_mmr - amount,
        "amount":   amount,
    })
    return result


async def _apply_strike(playername: str, reason: str = "") -> dict:
    """
    Applies a fixed MMR penalty AND a strike to a player.
    Returns a result dict.
    """
    result = {
        "success": False, "goodName": playername,
        "old_mmr": 0, "new_mmr": 0,
        "strike_count": 0, "expire_date": "",
        "error": "",
    }

    player = await _lookup_player(playername)
    if player is None:
        result["error"] = f"Player `{playername}` not found on the sheet."
        return result

    mmr     = player["mmr"]
    strikes = player["strikes"]

    offset = sum(1 for s in strikes if s != "")
    if offset >= 3:
        result["error"] = f"Player `{player['goodName']}` already has 3 strikes."
        return result

    agc          = await agcm.authorize()
    sh           = await agc.open_by_key(SH_KEY)
    p_history    = await sh.worksheet("Player History")
    strike_sheet = await sh.worksheet("Strikes")

    amount  = PENALTY_AMOUNT
    old_mmr = int(mmr)
    while old_mmr - amount < 0:
        amount -= 1

    new_pens = player["pens"] + amount
    await p_history.update_cell(int(player["pHrow"]), 4, new_pens)

    # Compute strike expiry (1 month from today)
    today = date.today()
    date_str = today.strftime("%m/%d/%y")
    m, d, y = map(int, date_str.split("/"))
    m += 1
    if m > 12:
        m -= 12
        y += 1
    expire_date = f"{m}/{d}/{y}"

    strike_updates = []
    strike_row = player["strikeRow"]
    if strike_row == "Not found":
        row_update = int(player["newRow"])
        strike_updates.append({'range': f"A{row_update}", 'values': [[player["goodName"]]]})
    else:
        row_update = int(strike_row)

    strike_updates.append({
        'range': rowcol_to_a1(row_update, 4 + offset),
        'values': [[date_str]],
    })
    await strike_sheet.batch_update(strike_updates)

    result.update({
        "success":      True,
        "goodName":     player["goodName"],
        "old_mmr":      old_mmr,
        "new_mmr":      old_mmr - amount,
        "amount":       amount,
        "strike_count": offset + 1,
        "expire_date":  expire_date,
        "strikes":      strikes,
    })
    return result


# ── Views ─────────────────────────────────────────────────────────────────────

class PenaltyRequestView(discord.ui.View):
    """
    Shown on penalty request embeds in the log channel.
    Buttons: Penalty | Strike | Pen + Strike | Deny | Resolved
    """

    def __init__(self, player_name: str, reporter_id: int, table_id: str,
                 penalty_type: str, reason: str):
        super().__init__(timeout=None)
        self.player_name  = player_name
        self.reporter_id  = reporter_id
        self.table_id     = table_id
        self.penalty_type = penalty_type
        self.reason       = reason

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        return any(r.name in STAFF_ROLES for r in interaction.user.roles)

    async def _send_reporter_dm(
        self,
        guild: discord.Guild,
        outcome: str,          # "penalty", "strike", "both", "denied"
        reason: str = "",
    ):
        """DM the reporter with the outcome of their request."""
        reporter = guild.get_member(self.reporter_id)
        if reporter is None:
            return
        try:
            if outcome == "denied":
                e = discord.Embed(
                    title="❌ Penalty Request Denied",
                    description=(
                        f"Your penalty request against **{self.player_name}** "
                        f"(Table `{self.table_id}`) has been denied by staff."
                        + (f"\n\n**Reason:** {reason}" if reason else "No reason specified.")
                    ),
                    color=discord.Color.red(),
                )
            else:
                labels = {
                    "penalty": "a **-50 MMR penalty**",
                    "strike":  "a **-50 MMR penalty + strike**",
                }
                e = discord.Embed(
                    title="✅ Penalty Request Approved",
                    description=(
                        f"Your penalty request against **{self.player_name}** "
                        f"(Table `{self.table_id}`) has been approved. "
                        f"They have received {labels.get(outcome, 'a penalty')}."
                    ),
                    color=discord.Color.green(),
                )
            await reporter.send(embed=e)
        except discord.Forbidden:
            pass

    async def _send_player_dm(
        self,
        player: discord.Member,
        outcome: str,          # "penalty" or "strike"
        amount: int,
    ):
        """DM the player who received the penalty."""

        try:
            if outcome == "penalty":
                title = "⚠️ Penalty Received"
                action = f"You have received a **-{amount} MMR penalty**."

            elif outcome == "strike":
                title = "🔴 Strike Received"
                action = (
                    f"You have received a **-{amount} MMR penalty** "
                    "and **1 strike**."
                )

            else:
                title = "Warning Received"
                action = "A disciplinary action has been taken against your account."

            embed = discord.Embed(
                title=title,
                description=(
                    f"{action}\n\n"
                    f"**Table ID:** `{self.table_id}`\n"
                    f"**Reason:** {self.penalty_type}\n\n"
                    "If you believe this penalty was applied in error, "
                    "you may appeal it using the `/refuse_penalty` command."
                ),
                color=discord.Color.orange(),
            )

            await player.send(embed=embed)

        except discord.Forbidden:
            pass

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    # ── Apply Penalty ─────────────────────────────────────────────────────────

    @discord.ui.button(label="Penalty", style=discord.ButtonStyle.primary,
                       custom_id="pen_apply_penalty")
    async def apply_penalty(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to do this.", ephemeral=True
            )
            return 

        await interaction.response.defer()
        # result = await _apply_penalty(self.player_name, self.reason)

        embed = interaction.message.embeds[0]
        player = next(f.value for f in embed.fields if f.name == "Reported Player")
        result = await _apply_penalty(player, self.reason)
        if result["success"]:
            embed.color = discord.Color.red()
            embed.add_field(
                name="✅ Penalty Applied",
                value=(
                    f"**-{result['amount']} MMR** applied to **{result['goodName']}**\n"
                    f"{result['old_mmr']} → {result['new_mmr']}\n"
                    f"Approved by {interaction.user.mention}"
                ),
                inline=False,
            )
            pen_ch = interaction.guild.get_channel(pen_channel)
            if pen_ch:
                e = discord.Embed(title="Penalty Added", color=discord.Color.orange())
                e.add_field(name="Player",  value=result["goodName"], inline=False)
                e.add_field(name="Table ID", value=self.table_id, inline=True)
                e.add_field(name="Penalty", value=f"-{result['amount']} MMR:\n{result['old_mmr']} → {result['new_mmr']}", inline=False)
                e.add_field(name="Reason",  value=self.penalty_type, inline=False)
                await pen_ch.send(embed=e)
            await self._send_reporter_dm(interaction.guild, "penalty")
            member = discord.utils.find(
                lambda m: m.display_name.lower() == result["goodName"].lower(),
                interaction.guild.members,
            )
            if member:
                await self._send_player_dm(member, "penalty", result["amount"])
        else:
            embed.add_field(name="❌ Error", value=result["error"], inline=False)

        self._disable_all()
        await interaction.message.edit(embed=embed, view=self)

    # ── Apply Strike ──────────────────────────────────────────────────────────

    @discord.ui.button(label="Strike", style=discord.ButtonStyle.primary,
                       custom_id="pen_apply_strike")
    async def apply_strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to do this.", ephemeral=True
            )
            return

        await interaction.response.defer()
        result = await _apply_strike(self.player_name, self.reason)

        embed = interaction.message.embeds[0]
        if result["success"]:
            embed.color = discord.Color.red()

            # Build strike info string
            strike_data = ""
            for i in range(3):
                s = result["strikes"][i]
                if s == "":
                    continue
                sm, sd, sy = map(int, str(s).split("/"))
                sm += 1
                if sm > 12:
                    sm -= 12
                    sy += 1
                strike_data += f"\nStrike {i+1}: expires {sm}/{sd}/{sy}"
            strike_data += f"\nStrike {result['strike_count']}: expires {result['expire_date']}"
            strike_data = f"{result['strike_count']}/3 strikes{strike_data}"

            embed.add_field(
                name="✅ Strike + Penalty Applied",
                value=(
                    f"**-{result['amount']} MMR + Strike** applied to **{result['goodName']}**\n"
                    f"{result['old_mmr']} → {result['new_mmr']}\n"
                    f"Approved by {interaction.user.mention}"
                ),
                inline=False,
            )
            embed.add_field(name="Strike Info", value=strike_data, inline=False)

            pen_ch = interaction.guild.get_channel(pen_channel)
            if pen_ch:
                e = discord.Embed(title="Strike + Penalty Added", color=discord.Color.red())
                e.add_field(name="Player",      value=result["goodName"], inline=False)
                e.add_field(name="Table ID",    value=self.table_id, inline=True)
                e.add_field(name="Penalty",     value=f"-{result['amount']} MMR:\n{result['old_mmr']} → {result['new_mmr']}", inline=False)
                e.add_field(name="Strike Info", value=strike_data, inline=False)
                e.add_field(name="Reason",      value=self.penalty_type, inline=False)
                content = ""
                if result["strike_count"] == 3:
                    content = f"⚠️ **{result['goodName']}** has reached 3 strikes and should be muted."
                await pen_ch.send(content=content, embed=e)
            await self._send_reporter_dm(interaction.guild, "strike")
            member = discord.utils.find(
                lambda m: m.display_name.lower() == result["goodName"].lower(),
                interaction.guild.members,
            )
            if member:
                await self._send_player_dm(member, "strike", result["amount"])
        else:
            embed.add_field(name="❌ Error", value=result["error"], inline=False)

        self._disable_all()
        await interaction.message.edit(embed=embed, view=self)

    # ── Deny ──────────────────────────────────────────────────────────────────

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary,
                       custom_id="pen_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to do this.", ephemeral=True
            )
            return

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_gray()
        embed.add_field(
            name="❌ Denied",
            value=f"Denied by {interaction.user.mention}",
            inline=False,
        )
        self._disable_all()
        await interaction.response.edit_message(embed=embed, view=self)
        await self._send_reporter_dm(interaction.guild, "denied")

    # ── Resolved ──────────────────────────────────────────────────────────────

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary,
                       custom_id="pen_resolved")
    async def resolved(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You do not have permission to resolve this request.", ephemeral=True
            )
            return
        await interaction.message.delete()


class MMRReductionView(discord.ui.View):
    """Shown on MMR reduction request embeds."""

    def __init__(self, player_name: str, reporter_id: int, table_id: str, reason: str):
        super().__init__(timeout=None)
        self.player_name = player_name
        self.reporter_id = reporter_id
        self.table_id    = table_id
        self.reason      = reason

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        return any(r.name in STAFF_ROLES for r in interaction.user.roles)

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success,
                       custom_id="mmr_red_approve", emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to do this.", ephemeral=True
            )
            return

        await interaction.response.defer()
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.add_field(
            name="✅ Approved",
            value=f"Approved by {interaction.user.mention}\nUse `!update reduceloss <table_id> {self.player_name}` to apply.",
            inline=False,
        )
        self._disable_all()
        await interaction.message.edit(embed=embed, view=self)

        reporter = interaction.guild.get_member(self.reporter_id)
        if reporter:
            try:
                e = discord.Embed(
                    title="✅ MMR Reduction Approved",
                    description=(
                        f"Your MMR reduction request for table `{self.table_id}` "
                        "has been approved by staff."
                    ),
                    color=discord.Color.green(),
                )
                await reporter.send(embed=e)
            except discord.Forbidden:
                pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary,
                       custom_id="mmr_red_deny", emoji="🚫")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to do this.", ephemeral=True
            )
            return

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.dark_gray()
        embed.add_field(
            name="❌ Denied",
            value=f"Denied by {interaction.user.mention}",
            inline=False,
        )
        self._disable_all()
        await interaction.response.edit_message(embed=embed, view=self)

        reporter = interaction.guild.get_member(self.reporter_id)
        if reporter:
            try:
                e = discord.Embed(
                    title="❌ MMR Reduction Denied",
                    description=(
                        f"Your MMR reduction request for table `{self.table_id}` "
                        "has been denied by staff."
                    ),
                    color=discord.Color.red(),
                )
                await reporter.send(embed=e)
            except discord.Forbidden:
                pass

    @discord.ui.button(label="Resolved", style=discord.ButtonStyle.primary,
                       custom_id="mmr_red_resolved", emoji="✅")
    async def resolved(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "You do not have permission to resolve this request.", ephemeral=True
            )
            return
        await interaction.message.delete()


# ── Cog ───────────────────────────────────────────────────────────────────────

class Penalties(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('./config.json', 'r') as cjson:
            self.config = json.load(cjson)

    async def _get_table_status(self, table_id: int) -> Optional[str]:
        status = None
        db = await aiosqlite.connect('updating.db')
        try:
            async with db.execute(
                "SELECT 1 FROM tables WHERE tableid = ? LIMIT 1", (table_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    status = "Pending approval"
            if not status:
                async with db.execute(
                    "SELECT 1 FROM updated WHERE tableid = ? LIMIT 1", (table_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        status = "Already updated"
        finally:
            await db.close()
        return status

    # ── /request_penalty ──────────────────────────────────────────────────────

    @app_commands.command(
        name="request_penalty",
        description="Report a player for a penalty (Staff will review).",
    )
    @app_commands.describe(
        penalty_type="Type of penalty you want to report someone for",
        player="The name of the player you are reporting",
        table_id="The ID of the table/match where this occurred",
        reason="Additional context you would like to provide to staff (optional)",
    )
    @app_commands.choices(penalty_type=[
        app_commands.Choice(name="Late",                  value="Late"),
        app_commands.Choice(name="No show",               value="No show"),
        app_commands.Choice(name="Repick",               value="Repick"),
        app_commands.Choice(name="Host issues",           value="Host issues"),
        app_commands.Choice(name="No host",               value="No host"),
        app_commands.Choice(name="Inappropriate name",    value="Inappropriate name"),
        app_commands.Choice(name="FFA name violation",    value="FFA name violation"),
        app_commands.Choice(name="No video proof",        value="No video proof"),
    ])
    @app_commands.checks.has_any_role("Administrator", "Updater", "Lounge Staff", "Reporter")

    async def request_penalty(
        self,
        interaction: discord.Interaction,
        penalty_type: app_commands.Choice[str],
        player: str,
        table_id: str,
        reason: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            table_id_value = int(table_id)
        except ValueError:
            await interaction.followup.send("Table ID must be a whole number.", ephemeral=True)
            return

        table_status = await self._get_table_status(table_id_value)
        if not table_status:
            await interaction.followup.send(
                f"Table ID {table_id_value} does not exist.", ephemeral=True
            )
            return

        log_channel = interaction.guild.get_channel(key_channels["penalty_log"])
        if not log_channel:
            await interaction.followup.send(
                "Error: Penalty log channel not configured.", ephemeral=True
            )
            return

        reason_str = reason or "No additional info provided."

        embed = discord.Embed(title="Penalty Request", color=discord.Color.orange())
        embed.add_field(name="Reporter",        value=interaction.user.mention, inline=True)
        embed.add_field(name="Reported Player", value=player,                   inline=True)
        embed.add_field(name="Table ID",        value=str(table_id_value),      inline=True)
        embed.add_field(name="Table Status",    value=table_status,             inline=True)
        embed.add_field(name="Penalty Type",    value=penalty_type.name,        inline=False)
        embed.add_field(name="Reason/Info",     value=reason_str,               inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        view = PenaltyRequestView(
            player_name=player,
            reporter_id=interaction.user.id,
            table_id=str(table_id_value),
            penalty_type=penalty_type.value,
            reason=reason_str,
        )

        try:
            await log_channel.send(embed=embed, view=view)
            await interaction.followup.send(
                "✅ Your penalty request has been submitted for staff review.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to post in the log channel.", ephemeral=True
            )

    # # ── /refuse_penalty ───────────────────────────────────────────────────────

    # @app_commands.command(
    #     name="refuse_penalty",
    #     description="Appeal a penalty you have received.",
    # )
    # @app_commands.describe(reason="Explain why you believe this penalty should be reverted")
    # async def refuse_penalty(self, interaction: discord.Interaction, reason: str):
    #     await interaction.response.defer(ephemeral=True)

    #     log_channel = interaction.guild.get_channel(key_channels["penalty_log"])
    #     if not log_channel:
    #         await interaction.followup.send(
    #             "Error: Penalty log channel not found.", ephemeral=True
    #         )
    #         return

    #     embed = discord.Embed(title="Penalty Appeal", color=discord.Color.blue())
    #     embed.add_field(name="Player", value=interaction.user.mention, inline=True)
    #     embed.add_field(name="Reason", value=reason,                   inline=False)
    #     embed.set_footer(text=f"User ID: {interaction.user.id}")

    #     # Simple resolved-only view for appeals
    #     class AppealView(discord.ui.View):
    #         def __init__(self):
    #             super().__init__(timeout=None)

    #         @discord.ui.button(label="Resolved", style=discord.ButtonStyle.primary,
    #                            custom_id="appeal_resolved")
    #         async def resolved(self, interaction: discord.Interaction, button: discord.ui.Button):
    #             if not interaction.user.guild_permissions.manage_messages:
    #                 await interaction.response.send_message(
    #                     "You do not have permission to resolve this.", ephemeral=True
    #                 )
    #                 return
    #             await interaction.message.delete()

    #     try:
    #         await log_channel.send(embed=embed, view=AppealView())
    #         await interaction.followup.send(
    #             "✅ Your appeal has been submitted and will be reviewed by staff.",
    #             ephemeral=True,
    #         )
    #     except discord.Forbidden:
    #         await interaction.followup.send(
    #             "❌ I don't have permission to post in the log channel.", ephemeral=True
    #         )

    # ── /request_mmr_reduction ────────────────────────────────────────────────

    @app_commands.command(
        name="request_mmr_reduction",
        description="Request MMR loss reduction from a match (Staff will review).",
    )
    @app_commands.describe(
        table_id="The ID of the table/match where this occurred",
        reason="Additional context you would like to provide to staff (optional)",
    )
    @app_commands.choices(reduction_reason=[
        app_commands.Choice(name="Disconnect before start", value="Disconnect before start"),
    ])
    async def request_mmr_reduction(
        self,
        interaction: discord.Interaction,
        reduction_reason: app_commands.Choice[str],
        table_id: str,
        reason: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            table_id_value = int(table_id)
        except ValueError:
            await interaction.followup.send("Table ID must be a whole number.", ephemeral=True)
            return

        table_status = await self._get_table_status(table_id_value)
        if not table_status:
            await interaction.followup.send(
                f"Table ID {table_id_value} does not exist.", ephemeral=True
            )
            return

        log_channel = interaction.guild.get_channel(key_channels["mmr_reduction_log"])
        if not log_channel:
            await interaction.followup.send(
                "Error: MMR reduction log channel not configured.", ephemeral=True
            )
            return

        # ── Prompt for proof upload ───────────────────────────────────────────
        prompt = await interaction.followup.send(
            "📎 Please upload your **photo or video proof** as a file attachment "
            "in this channel within **60 seconds**. "
            "Your request will not be submitted without it.",
            ephemeral=False,
            wait=True,
        )

        def is_proof(m: discord.Message) -> bool:
            return (
                m.author.id == interaction.user.id
                and m.channel.id == interaction.channel_id
                and len(m.attachments) > 0
            )

        try:
            proof_msg = await self.bot.wait_for("message", check=is_proof, timeout=60.0)
        except asyncio.TimeoutError:
            await prompt.edit(
                content="⏰ You didn't upload proof in time. Please run the command again."
            )
            return

        attachment = proof_msg.attachments[0]

        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    await prompt.edit(
                        content="❌ Could not download your attachment. Please try again."
                    )
                    await proof_msg.delete()
                    return
                file_bytes = await resp.read()

        proof_file = discord.File(io.BytesIO(file_bytes), filename=attachment.filename)

        try:
            await proof_msg.delete()
            await prompt.delete()
        except discord.HTTPException:
            pass

        # ── Build and post the log embed ──────────────────────────────────────
        embed = discord.Embed(title="MMR Reduction Request", color=discord.Color.orange())
        embed.add_field(name="Reporter",             value=interaction.user.mention,          inline=True)
        embed.add_field(name="Table ID",             value=str(table_id_value),               inline=True)
        embed.add_field(name="Table Status",         value=table_status,                      inline=True)
        embed.add_field(name="Reason for Reduction", value=reduction_reason.name,             inline=False)
        embed.add_field(name="Additional Info",      value=reason or "No additional info.",   inline=False)
        embed.set_image(url=f"attachment://{attachment.filename}")
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        view = MMRReductionView(
            player_name=interaction.user.display_name,
            reporter_id=interaction.user.id,
            table_id=str(table_id_value),
            reason=reason or "",
        )

        try:
            await log_channel.send(embed=embed, file=proof_file, view=view)
            await interaction.followup.send(
                "✅ Your MMR reduction request has been submitted for staff review.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to post in the log channel.", ephemeral=True
            )


async def setup(bot):
    cog = Penalties(bot)
    guild = discord.Object(id=cog.config["server"])
    await bot.add_cog(cog, guild=guild)