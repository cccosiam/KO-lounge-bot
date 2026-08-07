import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import re
from typing import Optional
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials
from better_profanity import profanity
from constants import key_channels, key_roles, base_MMR, profanity_whitelist, profanity_blacklist, SH_KEY, getRank, ranks

profanity.load_censor_words()
#profanity.add_censor_words(blacklist_words=profanity_blacklist)
profanity.load_censor_words(whitelist_words=profanity_whitelist)

PLAYER_ROLE_ID = key_roles["player"]
VERIFY_CHANNEL_ID = key_channels["verify"]
PENDING_VERIFY_CHANNEL_ID = key_channels["pending_verification"]
MKC_PROFILE_REGEX = re.compile(
    r"https?://(?:www\.)?mkcentral\.com(?:/[a-z]{2}(?:-[a-z]{2})?)?/registry/players/profile\?id=(\d+)",
    re.IGNORECASE,
)
MKC_API_BASE = "https://mkcentral.com/api/registry/players/{player_id}"
NICKNAME_REGEX = re.compile(r"^(?=.*[A-Za-z])(?=.{2,16})[A-Za-z0-9]+( [A-Za-z0-9]+)*$")

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

def _embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)
def info_embed(title: str, description: str) -> discord.Embed:
    return _embed(title, description, discord.Color.blurple())
def success_embed(title: str, description: str) -> discord.Embed:
    return _embed(title, description, discord.Color.green())
def error_embed(title: str, description: str) -> discord.Embed:
    return _embed(title, description, discord.Color.red())
def warning_embed(title: str, description: str) -> discord.Embed:
    return _embed(title, description, discord.Color.orange())

async def send_verification_log(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
    nickname: str | None,
    player_id: int | None,
    success: bool,
    reason: str,
):
    """Posts a verification attempt embed to the log channel."""
    channel = guild.get_channel(key_channels["verification_log"])
    if channel is None:
        return
 
    color  = discord.Color.green() if success else discord.Color.red()
    status = "✅ Success" if success else "❌ Failed"
 
    e = discord.Embed(title=f"Verification Attempt — {status}", color=color)
    e.add_field(name="User",     value=f"{member.mention} (`{member.id}`)", inline=False)
    e.add_field(name="Nickname", value=nickname or "*not provided*",         inline=True)
    e.add_field(name="MKC ID",   value=f"#{player_id}" if player_id else "**N/A**", inline=True)
    e.add_field(name="Result",   value=reason,                               inline=False)
    e.set_thumbnail(url=member.display_avatar.url)
    e.timestamp = discord.utils.utcnow()
 
    try:
        await channel.send(embed=e)
    except discord.HTTPException:
        pass

def _stamp_embed(embed: discord.Embed, result_text: str, color: discord.Color) -> discord.Embed:
    """Return a copy of the embed with an updated color and a Result field appended."""
    e = embed.copy()
    e.color = color
    e._fields = [f for f in (e._fields or []) if f["name"] != "Result"]
    e.add_field(name="Result", value=result_text, inline=False)
    e.timestamp = discord.utils.utcnow()
    return e

class VerificationModal(discord.ui.Modal, title="MKCentral Verification"):
    """Pop-up form that collects nickname + MKC profile URL in one shot."""

    nickname = discord.ui.TextInput(
        label="Nickname",
        placeholder="Name must be 2-16 characters long.",
        min_length=2,
        max_length=16,
    )
    mkc_url = discord.ui.TextInput(
        label="MKCentral Profile URL",
        placeholder="https://mkcentral.com/en-us/registry/players/profile?id=1276",
        min_length=10,
        max_length=200,
    )

    def __init__(self, cog: "Verification"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_verification(interaction, self.nickname.value, self.mkc_url.value)


class Verification(commands.Cog):
    """Handles new-player verification via the MKCentral registry API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._in_progress: set[int] = set()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id == VERIFY_CHANNEL_ID:
            try:
                await message.delete()
            except discord.Forbidden:
                pass


    @app_commands.command(
        name="verify",
        description="Verify your MKCentral account to get access to the Lounge Queue.",
    )
    async def verify(self, interaction: discord.Interaction):
        if interaction.channel_id != VERIFY_CHANNEL_ID:
            await interaction.response.send_message(
                embed=warning_embed(
                    "Wrong Channel",
                    f"Please use this command in <#{VERIFY_CHANNEL_ID}>.",
                ),
                ephemeral=True,
            )
            return

        member: discord.Member = interaction.user

        player_role = interaction.guild.get_role(PLAYER_ROLE_ID)
        if player_role and player_role in member.roles:
            await interaction.response.send_message(
                embed=warning_embed(
                    "Already Verified",
                    "You already have the **Player** role. "
                    "Contact a moderator if you need help.",
                ),
                ephemeral=True,
            )
            return

        if member.id in self._in_progress:
            await interaction.response.send_message(
                embed=warning_embed(
                    "Verification In Progress",
                    "You already have an active verification session in progress. "
                    "Please complete it or wait for it to expire.",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(VerificationModal(self))

    async def add_player_to_sheet(self, nickname: str, player_id: int) -> tuple[bool, str, bool]:
        try:
            agc = await agcm.authorize()
            sh = await agc.open_by_key(SH_KEY)

            add_edit_ws = await sh.worksheet("Add/Edit Players")
            player_history_ws = await sh.worksheet("Player History")

            await add_edit_ws.update("A3", [[nickname]])
            await add_edit_ws.update("D3", [[player_id]])

            await asyncio.sleep(0.5)

            err1 = await add_edit_ws.acell("A5")
            err2 = await add_edit_ws.acell("A7")
            row_cell = await add_edit_ws.acell("G3")

            err1_val = str(err1.value).strip() if err1.value else ""
            err2_val = str(err2.value).strip() if err2.value else ""

            if err2_val != "MKC ID is unused":
                mkc_id_col = await player_history_ws.col_values(2)
                if str(player_id) in [str(v) for v in mkc_id_col]:
                    return True, "", True
                else:
                    return False, (
                        f"Your MKCentral ID is already registered "
                        "under a different account. "
                        "Please open a ticket if you think this is a mistake.\n"
                        "あなたのMKCentral IDはすでに他のアカウントに登録されています。心当たりのない場合、チケットを切ってください。"
                    ), False

            if err1_val == "Name is already taken! Please ask the player to choose another":
                return False, (
                    "That nickname is already taken. "
                    "Please run `/verify` again and choose a different one.\n"
                    "そのニックネームはすでに使われています。他の名前でもう一度申請してください。"
                ), False

            row_num = int(row_cell.value)

            await player_history_ws.update(f"A{row_num}", [[nickname]])
            await player_history_ws.update(f"B{row_num}", [[player_id]])
            await player_history_ws.update(f"G{row_num}", [[base_MMR]])

            return True, "", False

        except Exception as exc:
            return False, f"Spreadsheet error: `{exc}`", False
    

    async def confirm_player_in_sheet(self, player_id: int) -> bool:
        try:
            agc = await agcm.authorize()
            sh  = await agc.open_by_key(SH_KEY)
            player_history_ws = await sh.worksheet("Player History")
            mkc_id_col = await player_history_ws.col_values(2)
            return str(player_id) in [str(v) for v in mkc_id_col]
        except Exception:
            return False

    async def assign_rank_role(self, member: discord.Member, mmr: int | None = None) -> None:
        if mmr is None:
            target_rank = "Silver 2"
        else:
            target_rank = getRank(mmr)

        role_ids = {rank_data["roleid"] for rank_data in ranks.values()}
        for role_id in role_ids:
            role = member.guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role)

        target_role = member.guild.get_role(ranks[target_rank]["roleid"])
        if target_role and target_role not in member.roles:
            await member.add_roles(target_role, reason="Rank assignment")

    async def get_player_mmr(self, player_id: int) -> int | None:
        try:
            agc = await agcm.authorize()
            sh = await agc.open_by_key(SH_KEY)
            player_history_ws = await sh.worksheet("Player History")
            mkc_ids = await player_history_ws.col_values(2)

            for idx, existing_id in enumerate(mkc_ids[1:], start=2):
                if str(existing_id).strip() != str(player_id):
                    continue

                mmr_cell = await player_history_ws.acell(f"C{idx}")
                mmr_value = mmr_cell.value
                if mmr_value is not None and str(mmr_value).strip():
                    return int(float(str(mmr_value).strip()))
                return None

            return None
        except Exception:
            return None

    async def process_verification(
        self,
        interaction: discord.Interaction,
        raw_nickname: str,
        raw_url: str,
    ):
        member: discord.Member = interaction.user

        nickname = raw_nickname.strip()
        player_id: int | None = None

        log_success = False
        log_reason = "Unknown error"

        async def fail(user_embed: discord.Embed, reason: str, msg=None):
            """Send the user-facing error and record the log reason."""
            nonlocal log_reason
            log_reason = reason
            if msg is not None:
                await msg.edit(embed=user_embed)
            else:
                await interaction.response.send_message(embed=user_embed, ephemeral=True)

        if not NICKNAME_REGEX.match(nickname):
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Invalid Nickname",
                    f"**{discord.utils.escape_markdown(nickname)}** contains invalid characters. "
                    "Only **letters and numbers** are allowed. Please run `/verify` again.\n"
                    f"**{discord.utils.escape_markdown(nickname)}** は使えない文字を含んでいます。アルファベットと記号のみ使えます。もう一度申請してください。",
                ),
                ephemeral=True,
            )
            log_reason = "Invalid nickname"
            return

        if profanity.contains_profanity(nickname) or any(str(word) in nickname.lower() for word in profanity.CENSOR_WORDSET):
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Inappropriate Nickname",
                    "That nickname contains inappropriate language and cannot be used. "
                    "Please run `/verify` again with a different nickname.\n"
                    "そのニックネームは不適切な言葉が含まれているため使えません。`/verify`で他の名前を申請してください。",
                ),
                ephemeral=True,
            )
            log_reason = "Inappropriate nickname"
            return

        normalized_url = re.sub(
            r"(https://mkcentral\.com)/[a-z]{2}(?:-[a-z]{2})?/",
            r"\1/",
            raw_url.strip(),
            flags=re.IGNORECASE,
        )

        url_match = MKC_PROFILE_REGEX.search(normalized_url)
        if not url_match:
            await interaction.response.send_message(
                embed=error_embed(
                    "❌ Invalid MKCentral URL",
                    "That doesn't look like a valid MKCentral profile URL. "
                    "Please run `/verify` again.\n"
                    "有効なMKCentralのURLではないようです。もう一度`/verify`で申請してください。",
                ),
                ephemeral=True,
            )
            log_reason = "Invalid MKCentral URL"
            return

        player_id = int(url_match.group(1))

        if member.id in self._in_progress:
            await interaction.response.send_message(
                embed=warning_embed(
                    "Verification In Progress",
                    "You already have an active verification session in progress.",
                ),
                ephemeral=True,
            )
            log_reason = "Active verification in progress"
            return

        # if player_id >= 93000:
        #     await fail(
        #         error_embed(
        #             "Manual Verification Required",
        #             "Your account must be verified manually by Staff. "
        #             "You will get a DM as soon as you get verified.\n"
        #             "あなたのアカウントはスタッフによる手動の認証が必要です。認証が完了しだい、DMでお知らせします。",
        #         ),
        #         f"MKC ID #{player_id} is a newly created account",
        #     )

        #     pending_channel = interaction.guild.get_channel(PENDING_VERIFY_CHANNEL_ID)
        #     if pending_channel:
        #         e = discord.Embed(
        #             title="New Account Pending Verification",
        #             color=discord.Color.yellow(),
        #         )
        #         e.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=False)
        #         e.add_field(name="Nickname", value=nickname, inline=True)
        #         e.add_field(name="MKC ID", value=f"#{player_id}", inline=True)
        #         e.add_field(name="MKC Profile", value=f"[Link]({normalized_url})", inline=True)
        #         e.set_thumbnail(url=member.display_avatar.url)
        #         e.timestamp = discord.utils.utcnow()
        #         try:
        #             await pending_channel.send(embed=e)
        #         except discord.HTTPException:
        #             pass
        #     return


        self._in_progress.add(member.id)

        await interaction.response.send_message(
            embed=info_embed(
                "Searching…",
                f"Retrieving player information…\n"
                "プレーヤーの情報を取得中...",
            ),
            ephemeral=True,
        )
        pending_msg = await interaction.original_response()

        try:
            api_url = MKC_API_BASE.format(player_id=player_id)
            player_data: Optional[dict] = None

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 404:
                            await pending_msg.edit(
                                embed=error_embed(
                                    "❌ Player Not Found",
                                    f"No MKCentral account with ID {player_id} exists."
                                    "Double-check your profile URL and run `/verify` again.\n"
                                    f"{player_id}というIDのMKCentralアカウントは存在しません。もう一度URLを確認し、`/verify`を実行してください。",
                                )
                            )
                            log_reason = "Player not found"
                            return

                        if resp.status != 200:
                            await pending_msg.edit(
                                embed=error_embed(
                                    "❌ API Error",
                                    f"The MKCentral API returned an unexpected error "
                                    f"(HTTP {resp.status}). Please try again later.",
                                )
                            )
                            log_reason = f"MKC API error {resp.status}"
                            return

                        player_data = await resp.json()

                except aiohttp.ClientError as exc:
                    await pending_msg.edit(
                        embed=error_embed(
                            "❌ Connection Error",
                            f"Could not reach the MKCentral API: `{exc}`\n"
                            "Please try again later.",
                        )
                    )
                    log_reason = f"Connection error: {exc}"
                    return

            if player_data.get("is_banned"):
                await pending_msg.edit(
                    embed=error_embed(
                        "🚫 Account Banned",
                        f"The MKCentral account {player_id} is banned "
                        "and cannot be used for verification.",
                    )
                )
                log_reason = "Banned account"
                return

            if player_data.get("is_shadow"):
                await pending_msg.edit(
                    embed=error_embed(
                        "🚫 Shadow Account",
                        f"The MKCentral account {player_id} cannot be used for verification.",
                    )
                )
                log_reason = "Shadow account"
                return

            mkc_discord: Optional[dict] = player_data.get("discord")
            if not mkc_discord:
                await pending_msg.edit(
                    embed=error_embed(
                        "❌ No Discord Linked",
                        "That MKCentral account has no Discord "
                        "account linked. Please link your Discord on MKCentral first, then "
                        "run `/verify` again.\n"
                        "そのMKCentralアカウントはDiscordアカウントと連携されていません。まずDiscordアカウントと連携し、それからもう一度`/verify`を実行してください。",
                    )
                )
                log_reason = "No Discord account linked"
                return

            mkc_discord_id = str(mkc_discord.get("discord_id", ""))
            if mkc_discord_id != str(member.id):
                await pending_msg.edit(
                    embed=error_embed(
                        "❌ Wrong MKCentral account",
                        "Make sure you're submitting your own MKCentral profile URL, "
                        "and that your Discord is linked correctly on MKCentral.\n"
                        "ご自身のMKCentralプロフィールURLを送信し、MKCentral上でDiscordが正しく連携されていることを確認してください。",
                    )
                )
                log_reason = "Wrong MKCentral account"
                return

            await pending_msg.edit(
                embed=info_embed(
                    "Registering…",
                    "Adding player to the database. This may take a moment…\n"
                    "データベースにプレーヤーを追加中です。これには少し時間がかかる事があります。",
                )
            )

            sheet_ok, sheet_err, is_returning = await self.add_player_to_sheet(nickname, player_id)

            if not sheet_ok:
                await pending_msg.edit(
                    embed=error_embed(
                        "❌ Registration Failed",
                        f"{sheet_err}. Please contact an administrator.",
                    )
                )
                log_reason = "Failed to add player to sheet"
                return

            if not await self.confirm_player_in_sheet(player_id):
                await pending_msg.edit(
                    embed=warning_embed(
                        "Too many verification requests at this time. ",
                        "Please wait a moment and run `/verify` again.\n"
                        "大量の認証リクエストが同時に行われています。時間を置いて`/verify`を実行してください。"
                    )
                )
                log_reason = "Too many verification requests"
                return

            player_role = interaction.guild.get_role(PLAYER_ROLE_ID)
            errors: list[str] = []

            if player_role:
                try:
                    await member.add_roles(player_role, reason="MKCentral verification passed")
                except discord.Forbidden:
                    errors.append("Could not assign the **Player** role (missing permissions).")
                except discord.HTTPException as exc:
                    errors.append(f"Failed to assign role: `{exc}`")
            else:
                errors.append("Player role not found — contact an admin.")

            try:
                await member.edit(nick=nickname, reason="MKCentral verification — nickname set")
            except discord.Forbidden:
                errors.append(
                    "Could not change your nickname (you may have a higher role than the bot)."
                )
            except discord.HTTPException as exc:
                errors.append(f"Failed to set nickname: `{exc}`")

            if is_returning:
                mmr = await self.get_player_mmr(player_id)
                await self.assign_rank_role(member, mmr)
            else:
                await self.assign_rank_role(member, None)

            mkc_name = player_data.get("name", f"#{player_id}")

            if errors:
                warning_text = "\n".join(f"• {e}" for e in errors)
                await pending_msg.edit(
                    embed=warning_embed(
                        "⚠️ Partially Verified",
                        f"You were added to the database as MKCentral player "
                        f"**{mkc_name}**, but the following issues occurred:\n\n"
                        f"{warning_text}\n\n"
                        "Please contact a moderator.",
                    )
                )
                log_success = True
                log_reason = f"Verified as **{mkc_name}** (#{player_id}) — role/nickname errors:\n{warning_text}"

            elif is_returning:
                await pending_msg.edit(
                    embed=success_embed(
                        "✅ Verification Successful",
                        "Welcome back to Knockout Tour Lounge! "
                        "Your match history is preserved.\n"
                        "Knockout Tour Loungeにおかえりなさい！あなたの戦績は残っていますよ。",
                    )
                )
                log_success = True
                log_reason = f"Verified as **{mkc_name}** (#{player_id}) — returning player"
            else:
                await pending_msg.edit(
                    embed=success_embed(
                        "✅ Verification Successful",
                        "Welcome to Knockout Tour Lounge!\n"
                        f"You have been assigned an initial rating of **{base_MMR}MMR**. Have fun!\n"
                        f"Knockout Tour Loungeへようこそ！初期MMRとして{base_MMR}MMRが与えられました。楽しんでください！",
                    )
                )
                log_success = True
                log_reason = f"Verified as **{mkc_name}** (#{player_id}) — new player"

        finally:
            self._in_progress.discard(member.id)
            await send_verification_log(self.bot, interaction.guild, member, nickname, player_id, log_success, log_reason)


    @commands.command(name="verify_pending")
    @commands.has_any_role("Administrator", "Verification Staff")
    async def verify_pending(self, ctx):
        """
        Reads all embeds in #pending-verification and verifies each player
        using the same sheet + role + nickname logic as the normal flow.
        Skips players that fail and continues with the rest.
        Usage: !verify_pending
        """
        if ctx.guild.id != self.bot.config["server"]:
            return
 
        pending_channel = ctx.guild.get_channel(PENDING_VERIFY_CHANNEL_ID)
        if pending_channel is None:
            await ctx.send("❌ Pending-verification channel not found.")
            return
 
        # Fetch all messages in the channel (up to 100)
        messages = [
            msg async for msg in pending_channel.history(limit=100, oldest_first=True)
            if not msg.author.bot or msg.author.id == self.bot.user.id
        ]
 
        # Filter to only bot embed messages that haven't been processed yet
        pending_msgs = [
            msg for msg in messages
            if msg.author.id == self.bot.user.id
            and msg.embeds
            and msg.embeds[0].color
            and msg.embeds[0].color.value == discord.Color.yellow().value
        ]
 
        if not pending_msgs:
            await ctx.send("There are no pending verifications to process.")
            return
 
        status_msg = await ctx.send(f"Processing **{len(pending_msgs)}** pending verification(s)…")
 
        results = {"success": 0, "skipped": 0, "errors": []}
 
        player_role = ctx.guild.get_role(PLAYER_ROLE_ID)
 
        for msg in pending_msgs:
            embed = msg.embeds[0]
 
            # ── Extract fields from embed ─────────────────────────────────────
            fields = {f.name: f.value for f in embed.fields}
 
            # Parse user ID from "User" field: "<@ID> (`ID`)"
            user_field = fields.get("User", "")
            user_id_match = re.search(r"`(\d+)`", user_field)
            if not user_id_match:
                results["skipped"] += 1
                results["errors"].append(f"Could not parse user ID from embed (msg {msg.id})")
                continue
 
            discord_id = int(user_id_match.group(1))
            nickname   = fields.get("Nickname", "").strip()
 
            # Parse MKC ID from "#XXXXX"
            mkc_field    = fields.get("MKC ID", "")
            mkc_id_match = re.search(r"(\d+)", mkc_field)
            if not mkc_id_match:
                results["skipped"] += 1
                results["errors"].append(f"Could not parse MKC ID from embed (msg {msg.id})")
                continue
 
            player_id = int(mkc_id_match.group(1))
            member    = ctx.guild.get_member(discord_id)
 
            if member is None:
                # Player left the server
                await msg.edit(embed=_stamp_embed(embed, "⚠️ Player left the server", discord.Color.orange()))
                results["skipped"] += 1
                results["errors"].append(f"<@{discord_id}> (MKC #{player_id}) is no longer in the server")
                continue
 
            # ── Sheet registration ────────────────────────────────────────────
            sheet_ok, sheet_err, is_returning = await self.add_player_to_sheet(nickname, player_id)
            if not sheet_ok:
                await msg.edit(embed=_stamp_embed(embed, f"❌ Sheet error: {sheet_err}", discord.Color.red()))
                results["skipped"] += 1
                results["errors"].append(f"{member.mention} (MKC #{player_id}): {sheet_err}")
                continue
 
            if not await self.confirm_player_in_sheet(player_id):
                await msg.edit(embed=_stamp_embed(embed, "❌ Could not confirm sheet registration", discord.Color.red()))
                results["skipped"] += 1
                results["errors"].append(f"{member.mention} (MKC #{player_id}): sheet write not confirmed")
                continue
 
            # ── Apply role and nickname ───────────────────────────────────────
            role_errors = []
 
            if player_role:
                try:
                    await member.add_roles(player_role, reason=f"Pending verification approved by {ctx.author}")
                except discord.Forbidden:
                    role_errors.append("Could not assign Player role (missing permissions).")
                except discord.HTTPException as exc:
                    role_errors.append(f"Role assignment failed: `{exc}`")
            else:
                role_errors.append("Player role not found.")
 
            try:
                await member.edit(nick=nickname, reason=f"Pending verification approved by {ctx.author}")
            except discord.Forbidden:
                role_errors.append("Could not set nickname (insufficient permissions).")
            except discord.HTTPException as exc:
                role_errors.append(f"Nickname update failed: `{exc}`")

            if is_returning:
                mmr = await self.get_player_mmr(player_id)
                await self.assign_rank_role(member, mmr)
            else:
                await self.assign_rank_role(member, None)
 
            # ── DM the player ─────────────────────────────────────────────────
            try:
                dm_embed = success_embed(
                    "✅ Verification Successful",
                    "Welcome to Knockout Tour Lounge!"
                    f"You have been assigned an initial rating of **{base_MMR}MMR**. Have fun!\n"
                    f"Knockout Tour Loungeへようこそ！初期MMRとして{base_MMR}MMRが与えられました。楽しんでください！"
                    if not is_returning else
                    "Welcome back to Knockout Tour Lounge! Your match history is preserved.\n"
                    "Knockout Tour Loungeにおかえりなさい！あなたの戦績は残っていますよ。",
                )
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # DMs closed
 
            # ── Update the pending embed to reflect outcome ───────────────────
            if role_errors:
                warning_text = "".join(f"• {e}" for e in role_errors)
                stamp = f"⚠️ Partially verified by {ctx.author} — {warning_text}"
                await msg.edit(embed=_stamp_embed(embed, stamp, discord.Color.orange()))
            else:
                await msg.delete()
 
            # ── Log to verification log ───────────────────────────────────────
            log_reason = (
                f"Pending verification approved by {ctx.author} — "
                f"{'returning player' if is_returning else 'new player'} (MKC #{player_id})"
            )
            if role_errors:
                log_reason += f" — warnings: {'; '.join(role_errors)}"
 
            await send_verification_log(
                self.bot, ctx.guild, member, nickname, player_id,
                success=True, reason=log_reason,
            )
 
            results["success"] += 1
 
        # ── Final summary ─────────────────────────────────────────────────────
        summary = (
            f"✅ Done. **{results['success']}** verified, "
            f"**{results['skipped']}** skipped."
        )
        if results["errors"]:
            summary += "**Skipped:**" + "".join(f"• {e}" for e in results["errors"])
 
        await status_msg.edit(content=summary)


async def setup(bot: commands.Bot):
    cog = Verification(bot)
    guild = discord.Object(id=bot.config["server"])
    await bot.add_cog(cog, guild=guild)