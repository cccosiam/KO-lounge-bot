import discord
from discord.ext import commands

import aiosqlite
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials

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

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    # ── Unified !table command ────────────────────────────────────────────────

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

        # ── Parse score block ─────────────────────────────────────────────────
        players, scores = self._parse_lines(data)
        if len(players) != num_players:
            await ctx.send(f"Your table does not contain {num_players} valid score lines, try again!\nYou are missing {num_players - len(players)} player(s).")
            return

        lower_names = [n.lower() for n in players]
        if len(set(lower_names)) < len(lower_names):
            await ctx.send("Duplicate names are not allowed, please try again.")
            return

        is300 = sum(scores)

        # ── Sort players by score descending, compute placements ──────────────
        paired = sorted(zip(scores, players), reverse=False)
        sorted_scores = [s for s, _ in paired]
        sorted_names  = [n for _, n in paired]

        placements = []
        for i, s in enumerate(sorted_scores):
            if i == 0:
                placements.append(1)
            elif s == sorted_scores[i - 1]:
                placements.append(placements[-1])
            else:
                placements.append(i + 1)
        # ── Sheets name lookup ────────────────────────────────────────────────
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

        sorted_scores.reverse()

        # ── Build lorenzi image URL ───────────────────────────────────────────
        table_text = (
            "#hide playerScores\n"
            f"#title Tier {tier} FFA\n"
            "FFA - Free for All #FFAC1C\n" #8078FA ourple
        )
        for name, score in zip(good_names, sorted_scores):
            table_text += f"{name} {score}\n"

        image_url = (
            "https://gb2.hlorenzi.com/table.png?data="
            + urllib.parse.quote(table_text)
        )
        # ── Send confirmation preview ─────────────────────────────────────────
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

        # ── Persist to DB ─────────────────────────────────────────────────────
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

        # ── Download image and post to tier channel ───────────────────────────
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
            # Log deletion to updating log
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