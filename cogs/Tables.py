import discord
from discord.ext import commands

import aiosqlite
import gspread_asyncio
import asyncio
from oauth2client.service_account import ServiceAccountCredentials
from collections import Counter

import urllib
import re
import io
import aiohttp
import json

from constants import (channels, general_channels, key_channels, ranks, num_players, SH_KEY, LOOKUP_KEY)

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


class Tables(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('./config.json', 'r') as cjson:
            self.config = json.load(cjson)

    def _is_gps(self, scores: str) -> bool:
        for gp in re.split(r"[|+]", scores):
            if not gp.strip().isdigit():
                return False
        return True

    def _sum_gps(self, scores: str) -> int:
        return sum(int(gp.strip()) for gp in re.split(r"[|+]", scores))

    def _parse_lines(self, data: str) -> tuple[list[str], list[int]]:
        def keep(line):
            parts = line.split()
            if not line.strip() or len(parts) < 2:
                return False
            last = parts[-1]
            return last.isdigit() or self._is_gps(last)

        players, scores = [], []
        for line in filter(keep, data.split("\n")):
            parts = line.split()
            players.append(" ".join(parts[:-1]))
            scores.append(self._sum_gps(parts[-1]))
        return players, scores

    @staticmethod
    async def fetch_country(session: aiohttp.ClientSession, mkc_id: str) -> str:
            """Return uppercase country code or empty string on failure."""
            if not mkc_id:
                return ""
            try:
                url = f"http://mkc-api.vps.mkcentral.com/api/registry/players/{mkc_id}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return ""
                    data = await resp.json()
                    return (data.get("country_code") or "").upper()
            except Exception:
                return ""

    @commands.command(name="table")
    @commands.max_concurrency(number=1, wait=True)
    @commands.cooldown(3, 60, commands.BucketType.member)
    async def table(self, ctx, *, data):
        if not any(role.name in {"Administrator", "Updater", "Lounge Staff", "Reporter"} for role in ctx.author.roles):
            await ctx.send(
                "You need the **Reporter** role to submit tables.\n"
                "You can obtain it in the #self-roles channel.\n\n"
                "集計を提出するにはReporterロールが必要です。\n"
                "これは #self-roles から取得できます。"
            )
            return

        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!")
            return

        if ctx.channel.id in general_channels.values():
            await ctx.send("This command cannot be used outside a tier channel.", delete_after=10)
            return

        channel_name = (ctx.channel.name or "").lower()
        tier_match = re.search(r"tier-([a-z0-9]+)", channel_name)        
        if not tier_match:
            await ctx.send("This command can only be used in a tier channel.", delete_after=10)
            return

        tier = tier_match.group(1).upper()
        if tier not in channels:
            await ctx.send(f"Unknown tier channel: {ctx.channel.name}", delete_after=10)
            return

        size = 1  # FFA only for now

        players, scores = self._parse_lines(data)
        if len(players) != num_players:
            await ctx.send(f"Your table does not contain {num_players} valid score lines, try again!\nYou are missing {num_players - len(players)} player(s).")
            return

        lower_names = [n.lower() for n in players]
        if len(set(lower_names)) < len(lower_names):
            await ctx.send("Duplicate names are not allowed, please try again.")
            return

        is300 = sum(scores)

        paired = sorted(zip(scores, players), reverse=False)
        sorted_scores = [s for s, _ in paired]
        sorted_names  = [n for _, n in paired]

        score_counts = Counter(sorted_scores)
        duplicate_scores = [score for score, count in score_counts.items() if count > 1]

        if duplicate_scores:
            duplicate_scores.sort()

            message = (
                f"Two or more players have **{', '.join(map(str, duplicate_scores))}** as their score. " + 
                "Please check your input and try again."
            )

            await ctx.send(message)
            return

        placements = []
        for i, s in enumerate(sorted_scores):
            if i == 0:
                placements.append(1)
            elif s == sorted_scores[i - 1]:
                placements.append(placements[-1])
            else:
                placements.append(i + 1)

        agc = await agcm.authorize()
        sh  = await agc.open_by_key(LOOKUP_KEY)
        bot_sheet = await sh.worksheet("search")

        await bot_sheet.batch_update([{
            'range': "B9:B32",
            'values': [[name] for name in sorted_names],
        }])

        got_batch  = await bot_sheet.batch_get(["C9:C32"])
        good_names = [got_batch[0][i][0] for i in range(num_players)]

        errors = "\n".join(
            f"Player **{sorted_names[i]}** is not on the leaderboard; check your input"
            for i in range(num_players)
            if good_names[i] == "N/A"
        )
        if errors:
            await ctx.send(errors)
            return

        try:
            sh_main      = await agcm.authorize()
            sh_main      = await sh_main.open_by_key(SH_KEY)
            ph_ws        = await sh_main.worksheet("Player History")
            ph_name_col  = await ph_ws.col_values(1)
            ph_mkc_col   = await ph_ws.col_values(2)
            # Build name (lowercase) → MKC ID map
            name_to_mkc  = {
                ph_name_col[i].strip().lower(): ph_mkc_col[i].strip()
                for i in range(min(len(ph_name_col), len(ph_mkc_col)))
                if ph_name_col[i].strip() and ph_mkc_col[i].strip()
            }
        except Exception:
            name_to_mkc = {}
 
        fetch_country = Tables.fetch_country
        async with aiohttp.ClientSession() as session:
            mkc_ids      = [name_to_mkc.get(n.strip().lower(), "") for n in good_names]
            country_codes = await asyncio.gather(*[fetch_country(session, mid) for mid in mkc_ids])
 
        def display_name(name: str, country: str) -> str:
            return f"{name} [{country}]" if country else name


        sorted_scores.reverse()

        table_text = (
            "#hide playerScores\n"
            f"#title Tier {tier} FFA\n"
            "FFA - Free for All #FFAC1C\n" #8078FA ourple
        )
        for name, score, country in zip(good_names, sorted_scores, country_codes):
            table_text += f"{display_name(name, country)} {score}\n"

        image_url = (
            "https://gb2.hlorenzi.com/table.png?data="
            + urllib.parse.quote(table_text)
        )
        # score_groups = defaultdict(list)
        # for _name, _score, _placement in zip(sorted_names, sorted_scores, placements):
        #     score_groups[_score].append((_name, _placement))

        # tie_lines = []

        # for _score, _group in score_groups.items():
        #     if len(_group) > 1:
        #         internal_pos = int(_group[0][1])
        #         display_pos = (num_players) - internal_pos

        #         tie_lines.append(
        #             f"Two or more players have **{display_pos}** as their score. " + 
        #             "Please check your input and try again."
        #         )

        # if tie_lines:
        #     message = (
        #         ""
        #         + "\n".join(tie_lines)
        #     )
        #     await ctx.send(message)
        #     return

        e = discord.Embed(title="Table")
        e.set_image(url=image_url)
        content = "Please react to this message with \U00002611 within the next 30 seconds to confirm the table is correct"
        if is300 != 300:
            e.add_field(
                name="⚠️ Warning",
                value=f"The total score of {is300} might be incorrect! Most tables should add up to 300 points. Please check your input for duplicate scores.",
            )

        embedded = await ctx.send(content=content, embed=e)
        CHECK_BOX = "\U00002611"
        X_MARK    = "\U0000274C"
        await embedded.add_reaction(CHECK_BOX)
        await embedded.add_reaction(X_MARK)

        def check(reaction, user):
            return (
                user == ctx.author
                and reaction.message.id == embedded.id
                and str(reaction.emoji) in (CHECK_BOX, X_MARK)
            )

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
        except:
            await embedded.delete()
            return

        if str(reaction.emoji) == X_MARK:
            await embedded.delete()
            return

        names_str  = ",".join(good_names)
        places_str = ",".join(str(p) for p in reversed(placements))
        db_entry   = (size, tier, names_str, places_str, image_url, 0, ctx.author.id)

        try:
            db = await aiosqlite.connect('updating.db')
            c  = await db.cursor()
            await c.execute(
                """INSERT INTO tables (size, tier, names, placements, tableurl, messageid, authorid)
                   VALUES (?,?,?,?,?,?,?)""",
                db_entry,
            )
            new_id = c.lastrowid
            await db.commit()
        except Exception as exc:
            print(exc)
            return
        finally:
            await db.close()

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    await ctx.send("Could not download the table image.")
                    return
                file_data = io.BytesIO(await resp.read())
                f = discord.File(file_data, filename="MogiTable.png")

        result_embed = discord.Embed(title="Mogi Table", colour=int("625B09", 16))
        result_embed.add_field(name="ID",           value=new_id)
        result_embed.add_field(name="Tier",         value=tier)
        result_embed.add_field(name="Submitted by", value=ctx.author.mention)
        result_embed.set_image(url="attachment://MogiTable.png")

        tier_channel = ctx.guild.get_channel(channels[tier.upper()])
        try:
            if tier_channel is None:
                raise ValueError(f"No channel found for tier {tier}")
            table_msg = await tier_channel.send(file=f, embed=result_embed)
        except (discord.HTTPException, aiohttp.ClientError, OSError) as exc:
            try:
                db = await aiosqlite.connect('updating.db')
                c = await db.cursor()
                await c.execute("DELETE FROM tables WHERE tableid = ?", (new_id,))
                await db.commit()
            except Exception:
                pass
            finally:
                await db.close()
            await ctx.send(f"Failed to post the table to Discord because of a network/SSL error: {exc}")
            return

        await embedded.delete()

        if tier_channel.id != ctx.channel.id:
            await ctx.send(f"Successfully sent table to {tier_channel.mention} `(ID: {new_id})`")
        else:
            await ctx.message.delete()

        # ── Update DB row with real message ID ────────────────────────────────
        try:
            db = await aiosqlite.connect('updating.db')
            c  = await db.cursor()
            await c.execute(
                "UPDATE tables SET messageid = ? WHERE tableid = ?",
                (table_msg.id, new_id),
            )
            await db.commit()
        except Exception as exc:
            print(exc)
        finally:
            await db.close()

        # Post to updating log (if configured)
        try:
            log_channel_id = key_channels.get("updating_log", 0)
            if log_channel_id:
                log_channel = ctx.guild.get_channel(log_channel_id)
                if log_channel:
                    le = discord.Embed(title="Table Submitted", color=discord.Color.gold())
                    le.add_field(name="ID", value=str(new_id), inline=True)
                    le.add_field(name="Tier", value=tier, inline=True)
                    le.add_field(name="Submitted by", value=ctx.author.mention, inline=True)
                    try:
                        le.add_field(name="Message Link", value=f"[Link]({table_msg.jump_url})", inline=False)
                    except Exception as e:
                        logger.error(f"Error adding message link to log embed: {e}", exc_info=True)
                    await log_channel.send(embed=le)
        except Exception as e:
            logger.error(f"Error sending table submission message to log: {e}", exc_info=True)

    @table.error
    async def table_error(self, ctx, error):

        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"You're on cooldown. Try again in {error.retry_after:.0f}s.")
            return True

        return False

    @commands.command(name="submit")
    @commands.max_concurrency(number=1, wait=True)
    @commands.cooldown(3, 60, commands.BucketType.member)
    async def submit(self, ctx, size: int, *, data: str):
        """
        Submit a Squad Queue table.

        Usage:
            !submit 2
            Team 1 - A
            Player 1 105
            Player 2 71

            Team 2 - B
            Player 3 97
            Player 4 64
        """

        if not any(
            role.name in {"Administrator", "Updater", "Lounge Staff", "Reporter"}
            for role in ctx.author.roles
        ):
            await ctx.send(
                "You need the **Reporter** role to submit tables.\n"
                "You can obtain it in the #self-roles channel.\n\n"
                "集計を提出するにはReporterロールが必要です。\n"
                "これは #self-roles から取得できます。"
            )
            return

        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!")
            return

        if ctx.channel.id in general_channels.values():
            await ctx.send(
                "This command cannot be used outside a tier channel.",
                delete_after=10
            )
            return

        channel_name = (ctx.channel.name or "").lower()

        if not channel_name.startswith("sq"):
            await ctx.send(
                "This command can only be used in an SQ thread.",
                delete_after=10
            )
            return

        tier = "SQ"

        if size < 1:
            await ctx.send(
                "The Squad Queue format must contain at least 1 player per team."
            )
            return

        # Parse teams
        #
        # Expected:
        #
        # Team 1 - A
        # Kingcv 105
        # Sushiberry 71
        #
        # Team 2 - B
        # S.A.C 97
        # B1aze 64
        #
        team_header_pattern = re.compile(
            r"^\s*Team\s+\d+\s*-\s*(.+?)\s*$",
            re.IGNORECASE
        )

        lines = [line.strip() for line in data.splitlines()]

        teams = []
        current_team = None

        for line in lines:
            if not line:
                continue

            team_match = team_header_pattern.match(line)

            if team_match:
                # Save previous team
                if current_team is not None:
                    teams.append(current_team)

                tag = team_match.group(1).strip()

                if not tag:
                    await ctx.send(
                        "A team is missing its tag. "
                        "Please use the format `Team 1 - A`."
                    )
                    return

                current_team = {
                    "tag": tag,
                    "players": []
                }

                continue

            if current_team is None:
                await ctx.send(
                    "Invalid table format. "
                    "Every player must belong to a team using a header such as "
                    "`Team 1 - A`."
                )
                return

            parts = line.rsplit(maxsplit=1)

            if len(parts) != 2:
                await ctx.send(
                    f"Could not read this player line:\n`{line}`\n\n"
                    "Each player must be written as `Player Score`."
                )
                return

            player_name, score_text = parts

            if not score_text.isdigit():
                await ctx.send(
                    f"Invalid score for **{player_name}**: `{score_text}`"
                )
                return

            score = int(score_text)

            if score < 0:
                await ctx.send(
                    f"Invalid score for **{player_name}**: `{score}`"
                )
                return

            current_team["players"].append({
                "name": player_name.strip(),
                "score": score
            })

        if current_team is not None:
            teams.append(current_team)

        if not teams:
            await ctx.send(
                "No teams were found. Please use the format `Team 1 - A`."
            )
            return
        
        is1550 = sum(
            player["score"]
            for team in teams
            for player in team["players"]
            )

        tags = [team["tag"].casefold() for team in teams]

        if len(tags) != len(set(tags)):
            await ctx.send(
                "Duplicate team tags are not allowed. "
                "Every team must have a unique tag."
            )
            return

        invalid_teams = []

        for i, team in enumerate(teams, start=1):
            if len(team["players"]) != size:
                invalid_teams.append(
                    f"Team **{team['tag']}** has {len(team['players'])} "
                    f"player(s); expected {size}."
                )

        if invalid_teams:
            await ctx.send(
                "**Invalid Squad Queue table**\n\n"
                + "\n".join(invalid_teams)
            )
            return

        for team in teams:
            team["players"].sort(key=lambda player: player["score"], reverse=True)

        all_players = [
            player
            for team in teams
            for player in team["players"]
        ]

        player_names = [player["name"] for player in all_players]
        lower_names = [name.casefold() for name in player_names]

        if len(set(lower_names)) != len(lower_names):
            duplicates = sorted({
                name
                for name in lower_names
                if lower_names.count(name) > 1
            })

            await ctx.send(
                "Duplicate names are not allowed, please try again.\n"
                f"Duplicate player(s): {', '.join(duplicates)}"
            )
            return

        agc = await agcm.authorize()
        sh = await agc.open_by_key(LOOKUP_KEY)
        bot_sheet = await sh.worksheet("search")

        start_row = 9
        end_row = start_row + len(player_names) - 1

        await bot_sheet.batch_update([{
            "range": f"B{start_row}:B{end_row}",
            "values": [[name] for name in player_names],
        }])

        got_batch = await bot_sheet.batch_get(
            [f"C{start_row}:C{end_row}"]
        )

        good_names = [
            got_batch[0][i][0]
            for i in range(len(player_names))
        ]

        errors = "\n".join(
            f"Player **{player_names[i]}** is not on the leaderboard; "
            "check your input"
            for i in range(len(player_names))
            if good_names[i] == "N/A"
        )

        if errors:
            await ctx.send(errors)
            return

        try:
            sh_main      = await agcm.authorize()
            sh_main      = await sh_main.open_by_key(SH_KEY)
            ph_ws        = await sh_main.worksheet("Player History")
            ph_name_col  = await ph_ws.col_values(1)
            ph_mkc_col   = await ph_ws.col_values(2)
            # Build name (lowercase) → MKC ID map
            name_to_mkc  = {
                ph_name_col[i].strip().lower(): ph_mkc_col[i].strip()
                for i in range(min(len(ph_name_col), len(ph_mkc_col)))
                if ph_name_col[i].strip() and ph_mkc_col[i].strip()
            }
        except Exception:
            name_to_mkc = {}
 
        fetch_country = Tables.fetch_country
        async with aiohttp.ClientSession() as session:
            mkc_ids      = [name_to_mkc.get(n.strip().lower(), "") for n in good_names]
            country_codes = await asyncio.gather(*[fetch_country(session, mid) for mid in mkc_ids])
 
        def display_name(name: str, country: str) -> str:
            return f"{name} [{country}]" if country else name

        table_text = (
            f"#title Tier {tier}\n"
            "Results #9A78FA\n"
        )

        player_index = 0
        for team, team_good_names in zip(
            teams,
            [
                good_names[
                    sum(len(t["players"]) for t in teams[:i]):
                    sum(len(t["players"]) for t in teams[:i + 1])
                ]
                for i in range(len(teams))
            ]
        ):
            table_text += f"{team['tag']}\n"

            for player, good_name in zip(team["players"], team_good_names):
                table_text += f"{display_name(good_name, country_codes[player_index])} {player['score']}\n"
                player_index += 1

        image_url = (
            "https://gb2.hlorenzi.com/table.png?data="
            + urllib.parse.quote(table_text)
        )
        
        e = discord.Embed(title="SQ Table")
        e.set_image(url=image_url)

        content = (
            "Please react to this message with ☑️ within the next "
            "30 seconds to confirm the table is correct"
        )
        if is1550 != 1550:
            e.add_field(
                name="⚠️ Warning",
                value=f"The total score of {is1550} might be incorrect! Most tables should add up to 1550 points. Please check your input.",
            )

        embedded = await ctx.send(content=content, embed=e)

        CHECK_BOX = "\U00002611"
        X_MARK = "\U0000274C"

        await embedded.add_reaction(CHECK_BOX)
        await embedded.add_reaction(X_MARK)

        def check(reaction, user):
            return (
                user == ctx.author
                and reaction.message.id == embedded.id
                and str(reaction.emoji) in (CHECK_BOX, X_MARK)
            )

        try:
            reaction, _ = await self.bot.wait_for(
                "reaction_add",
                timeout=30.0,
                check=check
            )
        except asyncio.TimeoutError:
            await embedded.delete()
            return

        if str(reaction.emoji) == X_MARK:
            await embedded.delete()
            return

        names_str = ",".join(good_names)

        # For SQ, store each player's score in the placements field.
        places_str = ",".join(
            str(player["score"])
            for team in teams
            for player in team["players"]
        )

        db_entry = (
            size,
            tier,
            names_str,
            places_str,
            image_url,
            0,
            ctx.author.id
        )

        try:
            db = await aiosqlite.connect("updating.db")
            c = await db.cursor()

            await c.execute(
                """
                INSERT INTO tables
                    (size, tier, names, placements, tableurl, messageid, authorid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                db_entry,
            )

            new_id = c.lastrowid
            await db.commit()

        except Exception as exc:
            print(exc)
            return

        finally:
            await db.close()

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:

                if resp.status != 200:
                    await ctx.send("Could not download the table image.")
                    return

                file_data = io.BytesIO(await resp.read())
                f = discord.File(file_data, filename="MogiTable.png")

        result_embed = discord.Embed(
            title="SQ Table",
            colour=int("625B09", 16)
        )

        result_embed.add_field(name="ID", value=new_id)
        result_embed.add_field(name="Tier", value=tier)
        result_embed.add_field(
            name="Format",
            value=f"{size}v{size}"
        )
        result_embed.add_field(
            name="Submitted by",
            value=ctx.author.mention
        )

        result_embed.set_image(url="attachment://MogiTable.png")

        tier_channel = ctx.guild.get_channel(channels[tier.upper()])

        try:
            if tier_channel is None:
                raise ValueError(f"No channel found for tier {tier}")

            table_msg = await tier_channel.send(
                file=f,
                embed=result_embed
            )

        except (discord.HTTPException, aiohttp.ClientError, OSError) as exc:

            try:
                db = await aiosqlite.connect("updating.db")
                c = await db.cursor()

                await c.execute(
                    "DELETE FROM tables WHERE tableid = ?",
                    (new_id,)
                )

                await db.commit()

            except Exception:
                pass

            finally:
                await db.close()

            await ctx.send(
                "Failed to post the table to Discord because of a "
                f"network/SSL error: {exc}"
            )
            return

        await embedded.delete()

        if tier_channel.id != ctx.channel.id:
            await ctx.send(
                f"Successfully sent table to {tier_channel.mention} "
                f"`(ID: {new_id})`"
            )
        else:
            await ctx.message.delete()

        try:
            db = await aiosqlite.connect("updating.db")
            c = await db.cursor()

            await c.execute(
                "UPDATE tables SET messageid = ? WHERE tableid = ?",
                (table_msg.id, new_id),
            )

            await db.commit()

        except Exception as exc:
            print(exc)

        finally:
            await db.close()

        try:
            log_channel_id = key_channels.get("updating_log", 0)

            if log_channel_id:
                log_channel = ctx.guild.get_channel(log_channel_id)

                if log_channel:
                    le = discord.Embed(
                        title="Squad Queue Table Submitted",
                        color=discord.Color.gold()
                    )

                    le.add_field(
                        name="ID",
                        value=str(new_id),
                        inline=True
                    )

                    le.add_field(
                        name="Tier",
                        value=tier,
                        inline=True
                    )

                    le.add_field(
                        name="Format",
                        value=f"{size}v{size}",
                        inline=True
                    )

                    le.add_field(
                        name="Submitted by",
                        value=ctx.author.mention,
                        inline=True
                    )

                    try:
                        le.add_field(
                            name="Message Link",
                            value=f"[Link]({table_msg.jump_url})",
                            inline=False
                        )
                    except Exception as e:
                        logger.error(
                            f"Error adding message link to log: {e}",
                            exc_info=True
                        )

                    await log_channel.send(embed=le)

        except Exception as e:
            logger.error(
                f"Error sending SQ table submission log: {e}",
                exc_info=True
            )

    @commands.command()
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def pending(self, ctx):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!")
            return
        try:
            db = await aiosqlite.connect('updating.db')
            c  = await db.cursor()
            await c.execute("SELECT * from tables")
            tables = await c.fetchall()
            msg = ""
            for tier in channels.keys():
                tier_tables = [t for t in tables if t[2].upper() == tier]
                if tier_tables:
                    msg += f"Tier {tier}: {len(tier_tables)} tables\n"
                    for t in tier_tables:
                        msg += f"\tSubmission ID {t[0]}\n"
            await ctx.send(msg or "There are no pending tables to be updated")
        except Exception as e:
            logger.error(f"Error fetching pending tables: {e}", exc_info=True)
            await ctx.send("An error occurred while fetching pending tables.")
            return
        finally:
            await db.close()

    @commands.command()
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def view(self, ctx, tableid: int):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!")
            return
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            
            await c.execute("SELECT * from tables WHERE tableid = ?", (tableid,))
            table = await c.fetchone()
            
            if table:
                tier = table[2]
                channel = ctx.guild.get_channel(channels[tier.upper()])
                e = discord.Embed(title="Table (Pending)", color=discord.Color.orange())
                try:
                    table_msg = await channel.fetch_message(table[6])
                    e.add_field(name="Message Link", value=f"[Link]({table_msg.jump_url})")
                except:
                    pass
                e.set_image(url=table[5])
                await ctx.send(embed=e)
            else:
                await c.execute("SELECT * from updated WHERE tableid = ?", (tableid,))
                updated = await c.fetchone()
                
                if updated:
                    tier = updated[5]
                    msgid = updated[4]
                    channel = ctx.guild.get_channel(channels.get(tier.upper(), 0))
                    e = discord.Embed(title="Table (Updated)", color=discord.Color.green())
                    if channel:
                        try:
                            table_msg = await channel.fetch_message(msgid)
                            e.add_field(name="Message Link", value=f"[Link]({table_msg.jump_url})")
                        except:
                            pass
                    e.add_field(name="Tier", value=tier, inline=True)
                    await ctx.send(embed=e)
                else:
                    await ctx.send(f"Table ID {tableid} not found in pending or updated tables.")
        except Exception as ex:
            await ctx.send("Table couldn't be found")
        finally:
            await db.close()

    @commands.command()
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff", "Reporter")
    async def delete(self, ctx, tableid: int):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!")
            return
        try:
            db = await aiosqlite.connect('updating.db')
            c  = await db.cursor()
            await c.execute("SELECT * from tables WHERE tableid = ?", (tableid,))
            table    = await c.fetchone()
            msg_id   = table[6]
            author_id = table[7]
            tier     = table[2]
        except:
            await ctx.send(f"Database error: Table ID {tableid} not found")
            return
        finally:
            await db.close()
        try:
            channel   = ctx.guild.get_channel(channels[tier.upper()])
            table_msg = await channel.fetch_message(msg_id)
            if author_id == ctx.author.id:
                await table_msg.delete()
            else:
                await ctx.send("You are not the author of this table")
                return
        except:
            await ctx.send("Table message is already deleted")
            return
        try:
            db = await aiosqlite.connect('updating.db')
            c  = await db.cursor()
            await c.execute("DELETE from tables WHERE tableid = ?", (tableid,))
            await db.commit()
            await ctx.send(f"Removed table {tableid} from approval queue")
            try:
                log_channel_id = key_channels.get("updating_log", 0)
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(log_channel_id)
                    if log_channel:
                        le = discord.Embed(title="Table Deleted", color=discord.Color.red())
                        le.add_field(name="ID", value=str(tableid), inline=True)
                        le.add_field(name="Tier", value=tier, inline=True)
                        le.add_field(name="Deleted by", value=ctx.author.mention, inline=True)
                        le.add_field(name="Original author", value=f"<@{author_id}>", inline=True)
                        await log_channel.send(embed=le)
            except Exception:
                pass
        except:
            await ctx.send("Database error removing table from approval queue")
        finally:
            await db.close()


async def setup(bot):
    await bot.add_cog(Tables(bot))