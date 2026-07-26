import discord
from discord.ext import commands
from discord import app_commands
 
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials
 
import re
import json
from datetime import datetime, timezone
from typing import Optional
 
from constants import SH_KEY, key_channels
 
NAME_CHANGE_REQUEST_CHANNEL_ID = key_channels["name_change_request"]
NAME_CHANGE_LOG_CHANNEL_ID     = key_channels["name_change_log"]
 
STAFF_ROLES        = ("Administrator", "Lounge Staff")
NICKNAME_REGEX     = re.compile(r"^(?=.*[A-Za-z])(?=.{2,16})[A-Za-z0-9]+( [A-Za-z0-9]+)*$")
COOLDOWN_DAYS      = 60
SHEET_NAME_CHANGES = "Name Changes"   # tab that tracks cooldowns & history
 
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
 
def _embed(title, description, color):
    return discord.Embed(title=title, description=description, color=color)
 
def info_embed(title, description):
    return _embed(title, description, discord.Color.blurple())
 
def success_embed(title, description):
    return _embed(title, description, discord.Color.green())
 
def error_embed(title, description):
    return _embed(title, description, discord.Color.red())
 
def warning_embed(title, description):
    return _embed(title, description, discord.Color.orange())
 
async def get_sheet():
    agc = await agcm.authorize()
    sh  = await agc.open_by_key(SH_KEY)
    return await sh.worksheet(SHEET_NAME_CHANGES)
 
async def get_name_change_row(ws, discord_id: int) -> Optional[int]:
    """Return the 1-based row index for a discord_id in col A, or None."""
    id_col = await ws.col_values(1)
    try:
        return id_col.index(str(discord_id)) + 1
    except ValueError:
        return None
 
async def get_player_nc_data(discord_id: int) -> Optional[dict]:
    """
    Fetch name-change data for a player from the sheet.
    Columns: A=discord_id  B=free_used (TRUE/FALSE)  C=last_change_date (ISO)
    Returns None if the player has no row yet (treat as first-time).
    """
    try:
        ws  = await get_sheet()
        row = await get_name_change_row(ws, discord_id)
        if row is None:
            return None
        vals = await ws.row_values(row)
        return {
            "row":        row,
            "discord_id": vals[0] if len(vals) > 0 else "",
            "free_used":  vals[1].upper() == "TRUE" if len(vals) > 1 else False,
            "last_date":  vals[2] if len(vals) > 2 else "",
        }
    except Exception:
        return None
 
async def set_player_nc_data(discord_id: int, free_used: bool, last_date: str):
    """Write or update the name-change row for a player."""
    ws  = await get_sheet()
    row = await get_name_change_row(ws, discord_id)
    if row is None:
        # Append new row
        await ws.append_row([str(discord_id), str(free_used).upper(), last_date])
    else:
        await ws.update(f"A{row}:C{row}", [[str(discord_id), str(free_used).upper(), last_date]])
 
async def update_player_name_in_history(old_name: str, new_name: str) -> bool:
    """Update the player's name in column A of Player History."""
    try:
        agc = await agcm.authorize()
        sh  = await agc.open_by_key(SH_KEY)
        ws  = await sh.worksheet("Player History")
        name_col = await ws.col_values(1)
        names_lower = [v.strip().lower() for v in name_col]
        try:
            row = names_lower.index(old_name.strip().lower()) + 1
        except ValueError:
            return False
        await ws.update(f"A{row}", [[new_name]])
        return True
    except Exception:
        return False
 
def cooldown_remaining(last_date_str: str) -> Optional[int]:
    """
    Returns the number of days remaining on the cooldown,
    or None if the cooldown has passed / there is no cooldown.
    """
    if not last_date_str:
        return None
    try:
        last = datetime.fromisoformat(last_date_str).replace(tzinfo=timezone.utc)
        now  = datetime.now(timezone.utc)
        delta = (now - last).days
        remaining = COOLDOWN_DAYS - delta
        return remaining if remaining > 0 else None
    except ValueError:
        return None
 
class NameChangeModal(discord.ui.Modal, title="Name Change Request"):
    new_name = discord.ui.TextInput(
        label="New Nickname",
        placeholder="e.g. Kusaan",
        min_length=2,
        max_length=16,
    )
 
    def __init__(self, cog: "NameChange"):
        super().__init__()
        self.cog = cog
 
    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_request(interaction, self.new_name.value)
 
 
class DenyReasonModal(discord.ui.Modal, title="Deny Name Change Request"):
    reason = discord.ui.TextInput(
        label="Reason for denial",
        placeholder="e.g. Name contains inappropriate language.",
        style=discord.TextStyle.paragraph,
        max_length=300,
    )
 
    def __init__(self, cog: "NameChange", request_id: int, requester_id: int,
                 old_name: str, new_name: str, log_msg: discord.Message):
        super().__init__()
        self.cog          = cog
        self.request_id   = request_id
        self.requester_id = requester_id
        self.old_name     = old_name
        self.new_name     = new_name
        self.log_msg      = log_msg
 
    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.deny_request(
            interaction,
            self.request_id,
            self.requester_id,
            self.old_name,
            self.new_name,
            self.log_msg,
            self.reason.value,
        )
 
class RequestButtonView(discord.ui.View):
    """Persistent view shown in #name-change-request with the Request button."""
 
    def __init__(self, cog: "NameChange"):
        super().__init__(timeout=None)
        self.cog = cog
 
    @discord.ui.button(
        label="Request",
        style=discord.ButtonStyle.primary,
        custom_id="nc_request_button",
    )
    async def request(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NameChangeModal(self.cog))
 
 
class StaffActionView(discord.ui.View):
    """Accept / Deny buttons shown on each request in #name-change-log."""
 
    def __init__(self, cog: "NameChange", request_id: int, requester_id: int,
                 old_name: str, new_name: str):
        super().__init__(timeout=None)
        self.cog          = cog
        self.request_id   = request_id
        self.requester_id = requester_id
        self.old_name     = old_name
        self.new_name     = new_name
 
        # Add buttons dynamically so each gets a unique custom_id per request
        accept_btn = discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id=f"nc_accept_{request_id}",
        )
        deny_btn = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
            custom_id=f"nc_deny_{request_id}",
        )
        accept_btn.callback = self._accept_callback
        deny_btn.callback   = self._deny_callback
        self.add_item(accept_btn)
        self.add_item(deny_btn)
 
    def _is_staff(self, interaction: discord.Interaction) -> bool:
        return any(r.name in STAFF_ROLES for r in interaction.user.roles)
 
    async def _accept_callback(self, interaction: discord.Interaction):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to accept name change requests.", ephemeral=True
            )
            return
        await self.cog.accept_request(
            interaction,
            self.request_id,
            self.requester_id,
            self.old_name,
            self.new_name,
            interaction.message,
        )
 
    async def _deny_callback(self, interaction: discord.Interaction):
        if not self._is_staff(interaction):
            await interaction.response.send_message(
                "You don't have permission to deny name change requests.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            DenyReasonModal(
                self.cog,
                self.request_id,
                self.requester_id,
                self.old_name,
                self.new_name,
                interaction.message,
            )
        )
 

class NameChange(commands.Cog):
 
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        with open('./config.json', 'r') as f:
            self.config = json.load(f)
        self._next_id   = 1      # simple in-memory counter; reset on restart
        self._pending: dict[int, dict] = {}   # request_id → request data
 
    @commands.command(name="setup_namechange")
    @commands.has_any_role(*STAFF_ROLES)
    async def setup_namechange(self, ctx):
        """Posts the name-change info embed with the Request button. Run once."""
        if ctx.guild.id != self.config["server"]:
            return
 
        channel = ctx.guild.get_channel(NAME_CHANGE_REQUEST_CHANNEL_ID)
        if channel is None:
            await ctx.send("Name-change request channel not found.", ephemeral=True)
            return
 
        e = discord.Embed(
            title="Name Change Request",
            description=(
                "Please read the guidelines before making a request."
            ),
            color=discord.Color.blurple(),
        )
 
        await channel.send(embed=e, view=RequestButtonView(self))
        await ctx.send(f"Info embed posted in {channel.mention}.", ephemeral=True)
 
    async def process_request(self, interaction: discord.Interaction, raw_name: str):
        member   = interaction.user
        new_name = raw_name.strip()
 
        if not NICKNAME_REGEX.match(new_name):
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Invalid Name",
                    "Your new name must contain only **letters and numbers** "
                    "and be between **2 and 16 characters**. Please try again.",
                ),
                ephemeral=True,
            )
            return
 
        old_name = member.display_name
        if old_name is None:
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Not Verified",
                    "You don't appear to have a server nickname. "
                    "Make sure you are verified before requesting a name change.",
                ),
                ephemeral=True,
            )
            return
 
        if new_name.lower() == old_name.lower():
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Same Name",
                    "Your new name is the same as your current name.",
                ),
                ephemeral=True,
            )
            return
 
        await interaction.response.defer(ephemeral=True)
 
        nc_data = await get_player_nc_data(member.id)
 
        if nc_data is not None:
            if nc_data["free_used"]:
                remaining = cooldown_remaining(nc_data["last_date"])
                if remaining is not None:
                    await interaction.followup.send(
                        embed=error_embed(
                            "⏳ Cooldown Active",
                            f"You can request a name change in **{remaining} day(s)**.",
                        ),
                        ephemeral=True,
                    )
                    return
 
        if any(r["requester_id"] == member.id for r in self._pending.values()):
            await interaction.followup.send(
                embed=warning_embed(
                    "Request Already Pending",
                    "You already have a name change request pending review. "
                    "Please wait for staff to process it before submitting another.",
                ),
                ephemeral=True,
            )
            return
 
        log_channel = interaction.guild.get_channel(NAME_CHANGE_LOG_CHANNEL_ID)
        if log_channel is None:
            await interaction.followup.send(
                embed=error_embed("❌ Configuration Error",
                                  "Name change log channel not found. Contact an admin."),
                ephemeral=True,
            )
            return
 
        request_id = self._next_id
        self._next_id += 1
 
        is_free = nc_data is None or not nc_data["free_used"]
 
        e = discord.Embed(
            title=f"Name Change Request #{request_id}",
            color=discord.Color.orange(),
        )
        e.add_field(name="Player",    value=f"{member.mention} (`{member.id}`)", inline=False)
        e.add_field(name="Old Name",  value=old_name,  inline=True)
        e.add_field(name="New Name",  value=new_name,  inline=True)
        e.add_field(name="Free Change", value="Yes" if is_free else "No", inline=True)
        e.set_thumbnail(url=member.display_avatar.url)
        e.timestamp = discord.utils.utcnow()
 
        view = StaffActionView(self, request_id, member.id, old_name, new_name)
        log_msg = await log_channel.send(embed=e, view=view)
 
        # Store pending request
        self._pending[request_id] = {
            "requester_id": member.id,
            "old_name":     old_name,
            "new_name":     new_name,
            "log_msg_id":   log_msg.id,
            "is_free":      is_free,
        }
 
        await interaction.followup.send(
            embed=success_embed(
                "Request Submitted",
                f"Your name change request from **{old_name}** → **{new_name}** "
                "has been submitted and is pending staff review.",
            ),
            ephemeral=True,
        )
 
    async def accept_request(
        self,
        interaction: discord.Interaction,
        request_id: int,
        requester_id: int,
        old_name: str,
        new_name: str,
        log_msg: discord.Message,
    ):
        await interaction.response.defer(ephemeral=True)
 
        if request_id not in self._pending:
            await interaction.followup.send(
                "This request has already been processed.", ephemeral=True
            )
            return
 
        guild  = interaction.guild
        member = guild.get_member(requester_id)
 
        errors = []
 
        sheet_ok = await update_player_name_in_history(old_name, new_name)
        if not sheet_ok:
            errors.append(f"Could not find **{old_name}** in Player History.")
 
        if member is not None:
            try:
                await member.edit(nick=new_name, reason=f"Name change #{request_id} approved by {interaction.user}")
            except discord.Forbidden:
                errors.append("Could not update server nickname (insufficient permissions).")
            except discord.HTTPException as exc:
                errors.append(f"Nickname update failed: `{exc}`")
        else:
            errors.append("Player is no longer in the server — sheet updated but nickname not changed.")
 
        req = self._pending[request_id]
        now_str = datetime.now(timezone.utc).isoformat()
        await set_player_nc_data(requester_id, free_used=True, last_date=now_str)
 
        del self._pending[request_id]
 
        e = log_msg.embeds[0] if log_msg.embeds else discord.Embed()
        e.color = discord.Color.green()
        e.title = f"Name Change Request #{request_id} — ✅ Accepted"
        e.add_field(
            name="Reviewed by",
            value=f"{interaction.user.mention} at {discord.utils.format_dt(discord.utils.utcnow(), 'F')}",
            inline=False,
        )
        if errors:
            e.add_field(name="⚠️ Warnings", value="\n".join(f"• {err}" for err in errors), inline=False)
        await log_msg.edit(embed=e, view=None)
 
        if member is not None:
            try:
                dm_embed = success_embed(
                    "✅ Name Change Request Accepted",
                    f"Your name change request has been accepted.\n"
                    f"**{old_name}** → **{new_name}**\n\n",
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass   # Player has DMs closed
 
        await interaction.followup.send(
            f"Request #{request_id} accepted." + (f"\n⚠️ Warnings:\n" + "\n".join(errors) if errors else ""),
            ephemeral=True,
        )
 
    async def deny_request(
        self,
        interaction: discord.Interaction,
        request_id: int,
        requester_id: int,
        old_name: str,
        new_name: str,
        log_msg: discord.Message,
        reason: str,
    ):
        await interaction.response.defer(ephemeral=True)
 
        if request_id not in self._pending:
            await interaction.followup.send(
                "This request has already been processed.", ephemeral=True
            )
            return
 
        del self._pending[request_id]
 
        e = log_msg.embeds[0] if log_msg.embeds else discord.Embed()
        e.color = discord.Color.red()
        e.title = f"Name Change Request #{request_id} — ❌ Denied"
        e.add_field(name="Reason", value=reason, inline=False)
        e.add_field(
            name="Reviewed by",
            value=f"{interaction.user.mention} at {discord.utils.format_dt(discord.utils.utcnow(), 'F')}",
            inline=False,
        )
        await log_msg.edit(embed=e, view=None)
 
        member = interaction.guild.get_member(requester_id)
        if member is not None:
            try:
                dm_embed = error_embed(
                    "❌ Name Change Request Denied",
                    f"Your name change request (**{old_name}** → **{new_name}**) "
                    f"has been denied by staff.\n"
                    f"**Reason:** {reason}",
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass
 
        await interaction.followup.send(
            f"Request #{request_id} denied.", ephemeral=True
        )
 
    @commands.command(name="nc_accept")
    @commands.has_any_role(*STAFF_ROLES)
    async def nc_accept(self, ctx, request_id: int):
        """Accept a name change request by ID. Usage: !nc_accept <id>"""
        if ctx.guild.id != self.config["server"]:
            return
 
        req = self._pending.get(request_id)
        if req is None:
            await ctx.send(f"No pending request with ID #{request_id}.")
            return
 
        log_channel = ctx.guild.get_channel(NAME_CHANGE_LOG_CHANNEL_ID)
        log_msg = None
        if log_channel:
            try:
                log_msg = await log_channel.fetch_message(req["log_msg_id"])
            except discord.NotFound:
                pass
 
        class _FakeInteraction:
            """Shim so accept_request can work from a prefix command context."""
            def __init__(self, ctx):
                self.guild = ctx.guild
                self.user  = ctx.author
                self._ctx  = ctx
                self.response = self
                self._deferred = False
 
            async def defer(self, ephemeral=False):
                self._deferred = True
 
            async def send(self, content=None, **kwargs):
                await self._ctx.send(content, **kwargs)
 
            @property
            def followup(self):
                return self
 
        fake = _FakeInteraction(ctx)
        await self.accept_request(
            fake, request_id,
            req["requester_id"], req["old_name"], req["new_name"],
            log_msg,
        )
 
    @commands.command(name="nc_deny")
    @commands.has_any_role(*STAFF_ROLES)
    async def nc_deny(self, ctx, request_id: int, *, reason: str):
        """Deny a name change request by ID. Usage: !nc_deny <id> <reason>"""
        if ctx.guild.id != self.config["server"]:
            return
 
        req = self._pending.get(request_id)
        if req is None:
            await ctx.send(f"No pending request with ID #{request_id}.")
            return
 
        log_channel = ctx.guild.get_channel(NAME_CHANGE_LOG_CHANNEL_ID)
        log_msg = None
        if log_channel:
            try:
                log_msg = await log_channel.fetch_message(req["log_msg_id"])
            except discord.NotFound:
                pass
 
        class _FakeInteraction:
            def __init__(self, ctx):
                self.guild = ctx.guild
                self.user  = ctx.author
                self._ctx  = ctx
                self.response = self
                self._deferred = False
 
            async def defer(self, ephemeral=False):
                self._deferred = True
 
            async def send(self, content=None, **kwargs):
                kwargs.pop("ephemeral", None)
                await self._ctx.send(content, **kwargs)
 
            @property
            def followup(self):
                return self
 
        fake = _FakeInteraction(ctx)
        await self.deny_request(
            fake, request_id,
            req["requester_id"], req["old_name"], req["new_name"],
            log_msg, reason,
        )
 
    @commands.command(name="nc_accept_all")
    @commands.has_any_role(*STAFF_ROLES)
    async def nc_accept_all(self, ctx):
        """Accept all pending name change requests. Usage: !nc_accept_all"""
        if ctx.guild.id != self.config["server"]:
            return
 
        if not self._pending:
            await ctx.send("There are no pending name change requests.")
            return
 
        ids = list(self._pending.keys())
        await ctx.send(f"Processing {len(ids)} request(s)…")
 
        log_channel = ctx.guild.get_channel(NAME_CHANGE_LOG_CHANNEL_ID)
 
        for request_id in ids:
            req = self._pending.get(request_id)
            if req is None:
                continue
 
            log_msg = None
            if log_channel:
                try:
                    log_msg = await log_channel.fetch_message(req["log_msg_id"])
                except discord.NotFound:
                    pass
 
            class _FakeInteraction:
                def __init__(self_inner, ctx):
                    self_inner.guild    = ctx.guild
                    self_inner.user     = ctx.author
                    self_inner._ctx     = ctx
                    self_inner.response = self_inner
 
                async def defer(self_inner, ephemeral=False):
                    pass
 
                async def send(self_inner, content=None, **kwargs):
                    kwargs.pop("ephemeral", None)
                    await self_inner._ctx.send(content, **kwargs)
 
                @property
                def followup(self_inner):
                    return self_inner
 
            fake = _FakeInteraction(ctx)
            await self.accept_request(
                fake, request_id,
                req["requester_id"], req["old_name"], req["new_name"],
                log_msg,
            )
 
        await ctx.send("All pending name change requests have been processed.")
 
    @commands.command(name="nc_pending")
    @commands.has_any_role(*STAFF_ROLES)
    async def nc_pending(self, ctx):
        """List all pending name change requests. Usage: !nc_pending"""
        if ctx.guild.id != self.config["server"]:
            return
 
        if not self._pending:
            await ctx.send("There are no pending name change requests.")
            return
 
        lines = [
            f"**#{rid}** — `{r['old_name']}` → `{r['new_name']}` "
            f"(<@{r['requester_id']}>{', free' if r['is_free'] else ''})"
            for rid, r in self._pending.items()
        ]
        await ctx.send("**Pending name change requests:**\n" + "\n".join(lines))
 

async def setup(bot: commands.Bot):
    await bot.add_cog(NameChange(bot))
 
