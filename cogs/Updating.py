import discord
from discord.ext import commands

import aiosqlite
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials
import json
from datetime import date
import functools
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import asyncio
import random
import sqlite3

from constants import (channels, key_channels, key_roles, ranks, getRank,
                       SH_KEY, updateCols, getCols,
                       peakColumn, rowOffset, colOffset,
                       sheet_start_rows,
                       rowcol_to_a1, get_strike_info,
                       place_MMRs, pen_row, pen_cols, pen_channel,
                       num_players)

import logging
logger = logging.getLogger('discord')

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

from constants import key_roles

def findmember(ctx, name):
    members = ctx.guild.members
    player_role = ctx.guild.get_role(key_roles["player"])
    target_name = (name or "").strip().lower()

    def pred(m):
        # Only consider verified players
        if player_role not in m.roles:
            return False

        candidate_names = []
        if m.display_name:
            candidate_names.append(m.display_name)
        if m.nick:
            candidate_names.append(m.nick)
        if m.name:
            candidate_names.append(m.name)

        normalized_candidates = {
            candidate.strip().lower()
            for candidate in candidate_names
            if candidate and candidate.strip()
        }

        return target_name in normalized_candidates

    return discord.utils.find(pred, members)

def _rank_change_label(old_rank: str, new_rank: str) -> str:
    rank_order = {rank_name: index for index, rank_name in enumerate(ranks.keys())}
    old_index = rank_order.get(old_rank, len(rank_order))
    new_index = rank_order.get(new_rank, len(rank_order))

    if new_index < old_index:
        return f"{new_rank}"
    if new_index > old_index:
        return f"{new_rank}"
    return ""


def _generate_mmr_table_image(
    size: int,
    tier: str,
    good_names: list,
    placements: list,
    peak_mmrs: list,
    old_mmrs: list,
    mmr_changes: list,
    new_mmrs: list,
    races: int,
    id_num: int,
    promotion_labels: list | None = None,
    output_filename: str = "MMRTable.png"
) -> Path:
    """
    Generates an image of the MMR table using matplotlib and pandas.
    This function is synchronous and should be run in an executor.
    """
    
    table_data = []
    current_placement_idx = 0

    font_path = Path(__file__).parent.parent / "assets" / "fonts" / "Titillium_Web" / "TitilliumWeb-Regular.ttf"
    font_path_bold = Path(__file__).parent.parent / "assets" / "fonts" / "Titillium_Web" / "TitilliumWeb-Bold.ttf"
    font_manager.fontManager.addfont(str(font_path))
    font_manager.fontManager.addfont(str(font_path_bold))
    table_font = font_manager.FontProperties(fname=font_path, size=12)
    table_font_bold = font_manager.FontProperties(fname=font_path_bold, size=12)
    plt.rcParams['font.family'] = table_font.get_name()

    headers = ["Rank", "Player", "Peak", "Old MMR", "+/-", "New MMR", "Promotions"]

    for i in range(len(good_names)):
        row = []
        if i % size == 0:
            row.append(str(placements[current_placement_idx]))
            current_placement_idx += 1
        else:
            row.append("")

        row.append(good_names[i])
        peak_val = peak_mmrs[i] if i < len(peak_mmrs) else "N/A"
        row.append(peak_val if peak_val != "N/A" else "-")
        row.append(old_mmrs[i])
        change = mmr_changes[i]
        row.append(f"+{change}" if isinstance(change, int) and change > 0 else str(change))
        row.append(new_mmrs[i])
        row.append(promotion_labels[i] if promotion_labels and i < len(promotion_labels) else "")
        table_data.append(row)

    color_bg = "#241C3D" # Dark purple

    fig, ax = plt.subplots(figsize=(8.6, 9), facecolor=color_bg)
    ax.set_facecolor(color_bg)
    ax.axis('off')

    the_table = ax.table(
        cellText=table_data,
        colLabels=headers,
        cellLoc='center',
        loc='center',
        bbox=[0.0, 0.0, 1.0, 1.0],
        edges='closed' 
    )

    the_table.auto_set_font_size(False)
    the_table.set_fontsize(13)

    cells = the_table.get_celld()
    column_widths = {
        0: 0.08,  # Placement
        1: 0.30,  # Player Name
        2: 0.10,  # Peak MMR
        3: 0.12,  # Old MMR
        4: 0.09,  # Change
        5: 0.12,  # New MMR
        6: 0.20   # Promotions
    }

    header_color = '#3A2E62'  # Dark Purple
    border_color = '#2C2C2C' # Gray
    cell_color = '#5C4A9A'  # Ourple
    player_cell_color = '#212121'  # Dark Gray
    MAX_GREEN = mcolors.to_rgb('#548235') # Strong Green
    MAX_RED = mcolors.to_rgb('#C00000')   # Strong Red
    NEUTRAL_WHITE = mcolors.to_rgb('#FFFFFF')
    text_white = '#FFFFFF'
    text_black = '#000000'

    for (row_idx, col_idx), cell in cells.items():
        cell.set_edgecolor(border_color)
        cell.set_facecolor(cell_color)
        cell_text = cell.get_text()
        cell_text.set_color(text_white)
        if col_idx in column_widths:
            cell.set_width(column_widths[col_idx])
        text = cell.get_text().get_text()
        # if len(text) > 15:
        #     cell.get_text().set_fontsize(11)
        if row_idx == 0: # Header row
            cell.set_height(1.03)
            cell.set_facecolor(header_color)
            cell.get_text().set_fontsize(12.5)
        else:
            cell.set_height(1.1)
            if col_idx == 1: # Player Name column
                cell.set_facecolor(player_cell_color)
            if col_idx == 5: # New MMR column
                cell.get_text().set_fontproperties(table_font_bold)
                cell.get_text().set_fontsize(13)
            if col_idx == 4: # MMR Change column
                cell.set_facecolor(player_cell_color)
                raw_text = cell.get_text().get_text()
                try:
                    val = int(raw_text.replace('+', '').replace(' ', ''))
                    intensity = min(abs(val) / 75.0, 1.0)
                    if val > 0:
                        new_color = [NEUTRAL_WHITE[i] + (MAX_GREEN[i] - NEUTRAL_WHITE[i]) * intensity for i in range(3)]
                    elif val < 0:
                        new_color = [NEUTRAL_WHITE[i] + (MAX_RED[i] - NEUTRAL_WHITE[i]) * intensity for i in range(3)]
                    else:
                        new_color = NEUTRAL_WHITE
                    cell.get_text().set_color(new_color)
                except ValueError:
                    cell.get_text().set_color(NEUTRAL_WHITE)

    plt.title(f"Tier {tier.upper()} Free For All Results", fontsize=18, pad=13, color=text_white)
    plt.figtext(0.5, 0.085, f"ID: {id_num}  |  Rallies: {races}  |  Updated on {date.today()}", 
                ha="center", color=text_white, fontsize=11, bbox={"facecolor":"#121212", "alpha":0.2, "pad":5})

    output_path = Path(output_filename)
    plt.savefig(output_path, bbox_inches='tight', dpi=300)
    plt.close(fig)
    return output_path


class Updating(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config 

    async def _apply_rank_change_for_player(self, ctx, player_name: str, old_mmr, new_mmr):
        try:
            old_mmr_value = int(old_mmr)
            new_mmr_value = int(new_mmr)
        except (TypeError, ValueError):
            return ""

        old_rank = getRank(old_mmr_value)
        new_rank = getRank(new_mmr_value)
        if old_rank == new_rank:
            return ""

        label = _rank_change_label(old_rank, new_rank)
        member = findmember(ctx, player_name)
        if member is None:
            return f"{player_name} — {label}"

        new_role = ctx.guild.get_role(ranks[new_rank]["roleid"])
        if new_role is None:
            return f"{member.mention} — {label}"

        for rank_name, rank_data in ranks.items():
            role = ctx.guild.get_role(rank_data["roleid"])
            if role and role in member.roles and role.id != new_role.id:
                try:
                    await member.remove_roles(role, reason="MMR rank update")
                except (discord.Forbidden, discord.HTTPException):
                    pass

        try:
            if new_role not in member.roles:
                await member.add_roles(new_role, reason="MMR rank update")
        except (discord.Forbidden, discord.HTTPException):
            pass

        return f"{member.mention} — {label}"

    async def _approve_table_internal(self, ctx, table, extraArgs=""):
        """Internal helper to process the approval logic for a single table row."""
        tableid, size_str, tier, names_raw, placements_raw, _, messageid = table
        size = int(size_str)
        tier = tier.upper()
        names = names_raw.split(",")
        placements = placements_raw.split(",")
        
        arguments = extraArgs.split(";") if extraArgs else []
        instructions = {}
        
        if tier == "SQ":
            for i in range(size):
                instructions[i+1] = 0.75
        elif len(arguments) > 0:
            try:
                instructions = await self.processInstructions(ctx, tier, arguments[0])
            except Exception:
                return False

        mults = [instructions.get(i+1, 1) for i in range(size)]
        races = 1
        if len(arguments) > 1:
            try:
                raceArg = int(arguments[1])
                if raceArg == 1:
                    races = raceArg
            except ValueError:
                pass

        try:
            await self.updateTable(ctx, size, tier, names, placements, mults, races, messageid, tableid)
        except Exception as e:
            logger.error(f"Error in updateTable for table {tableid}: {e}", exc_info=True)
            return False

        async with aiosqlite.connect('updating.db') as db:
            await db.execute("DELETE from tables WHERE tableid = ?", (tableid,))
            await db.commit()

        # Handle Reactions
        channel_id = channels.get(tier)
        if channel_id:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                try:
                    reactMsg = await channel.fetch_message(messageid)
                    await reactMsg.add_reaction("\U00002611")
                except Exception:
                    logger.warning(f"Could not add reaction to message {messageid}")
        
        return True

    async def updateTable(self, ctx: commands.Context, size: int, tier: str, names: list, placements: list, mults: list, races: int, messageid: int = 0, tableid: int = 0):
        """
        Handles the core logic of updating Google Sheets and generating the MMR table image.
        """
        msg = await ctx.send("Working...")
        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("Bot")
        pHistory = await sh.worksheet("Player History")
        idSheet = await sh.worksheet("ID")
        
        channel = ctx.guild.get_channel(channels[tier.upper()])
        start = sheet_start_rows[size]
              
        updateCells = [{
            'range': f"{updateCols[0]}{start}:{updateCols[0]}{start+num_players-1}",
            'values': [[name] for name in names]}, {
            'range': f"{updateCols[1]}{start}:{updateCols[1]}{start+int(num_players/size)-1}",
            'values': [[int(placement)] for placement in placements]}, {
            'range': f"{updateCols[2]}{start}:{updateCols[2]}{start+num_players-1}",
            'values': [[mult] for mult in mults]}
            ]
        updateCells.append({'range': f"C{start+num_players}",
                            'values': [[races]]})
        await botSheet.batch_update(updateCells)

        gotBatch = await botSheet.batch_get([f"{getCols[0]}{start}:{getCols[1]}{start+num_players-1}"])
        
        peakMMRs = []
        oldMMRs = []
        mmrChanges = []
        newMMRs = []
        rowNums = []
        colNums = []
        goodNames = []
        for i in range(num_players):
            peakMMRs.append(gotBatch[0][i][0])
            oldMMRs.append(gotBatch[0][i][1])
            mmrChanges.append(int(gotBatch[0][i][2]))
            newMMRs.append(int(gotBatch[0][i][3]))
            rowNums.append(gotBatch[0][i][4])
            colNums.append(int(gotBatch[0][i][5]))
            goodNames.append(gotBatch[0][i][6])

        idCell = await idSheet.acell('A1')
        idNum = int(idCell.value)

        errors = ""
        for i in range(num_players):
            if rowNums[i] == "#N/A" or oldMMRs[i] == "N/A":
                errors += f"Player {names[i]} is not on the sheet; check your input.\n"
            if colNums[i] >= 399:
                errors += (f"Player {names[i]} needs to be archived, which is not supported by this bot; "
                           "please update this table with the sheet script.\n")
            if oldMMRs[i] == "Placement":
                errors += (f"Player {names[i]} needs to be given Placement MMR; "
                           "please give them a base MMR on the sheet.\n")
        if len(errors) > 0:
            await ctx.send(errors, delete_after=30)
            await msg.delete()
            raise ValueError("Data validation failed from Google Sheet.")
        
        updateCells = []
        placementUpdateCells = []
        peakChanges = []
        # The `placements` list in the DB is stored reversed relative to the
        # visual order. Reverse it here so images and placement history are
        # generated in ascending order (1 -> N).
        try:
            placements = list(placements)[::-1]
        except Exception:
            placements = placements
        for i in range(num_players):
            if peakMMRs[i] == "N/A":
                if colNums[i] >= 4:
                    peakCell = {'range': f"{peakColumn}{int(rowNums[i])+rowOffset}",
                                'values': [[newMMRs[i]]]}
                    updateCells.append(peakCell)
                    peakChanges.append([str(int(rowNums[i])+rowOffset), "N/A"])
            elif newMMRs[i] > int(peakMMRs[i]):
                peakCell = {'range': f"{peakColumn}{int(rowNums[i])+rowOffset}",
                            'values': [[newMMRs[i]]]}
                updateCells.append(peakCell)
                peakChanges.append([str(int(rowNums[i])+rowOffset), str(peakMMRs[i])])
            
            current_mmr_change = mmrChanges[i]
            while int(oldMMRs[i]) + current_mmr_change < 0:
                current_mmr_change += 1
            
            cellA1 = rowcol_to_a1(int(rowNums[i])+rowOffset, colNums[i]+colOffset)
            updateCells.append({'range': cellA1, 'values': [[current_mmr_change]]})

            player_placement = int(placements[int(i/size)])
            placementUpdateCells.append({'range': cellA1, 'values': [[player_placement]]})

        idCell = await idSheet.acell('A1')
        current_id = int(idCell.value) if idCell.value else 0
        idNum = tableid
        if idNum > current_id:
            await idSheet.update_cell(1, 1, idNum)
        else:
            idNum = current_id 

        image_output_path = Path("MMRTable.png")
        
        promotion_labels = []
        for i in range(num_players):
            rank1 = getRank(int(oldMMRs[i]))
            rank2 = getRank(int(newMMRs[i]))
            if rank1 != rank2:
                promotion_labels.append(_rank_change_label(rank1, rank2))
                await self._apply_rank_change_for_player(
                    ctx,
                    goodNames[i],
                    oldMMRs[i],
                    newMMRs[i],
                )
            else:
                promotion_labels.append("")

        try:
            loop = asyncio.get_running_loop()
            image_generation_task = functools.partial(
                _generate_mmr_table_image,
                size=size,
                tier=tier,
                good_names=goodNames,
                placements=placements,
                peak_mmrs=peakMMRs,
                old_mmrs=oldMMRs,
                mmr_changes=mmrChanges,
                new_mmrs=newMMRs,
                races=races,
                id_num=idNum,
                promotion_labels=promotion_labels,
                output_filename=image_output_path
            )
            await loop.run_in_executor(None, image_generation_task)
            # logger.info(f"Successfully generated MMR table image: {image_output_path}")
        except Exception as e:
            logger.error(f"Error generating MMR table image: {e}", exc_info=True)
            await ctx.send("Failed to generate the MMR table image.", delete_after=15)
            await msg.delete()
            raise

        await pHistory.batch_update(updateCells)
        await msg.delete()

        response_msg_content = f"Table #{idNum} updated successfully"
        if ctx.channel != channel:
            response_msg_content += f"; check {channel.mention} to view"
        myMsg = await ctx.send(response_msg_content)

        if ctx.channel == channel:
            await myMsg.delete(delay=5)


        f = discord.File(image_output_path, filename="MMRTable.png")
        e = discord.Embed(title="MMR Table", color=discord.Color.purple())
        e.add_field(name="ID", value=str(idNum), inline=True)
        e.add_field(name="Tier", value=tier.upper(), inline=True)
        
        if messageid != 0 and tableid != 0:
            try:
                foundmsg = await channel.fetch_message(messageid)
                submissionContent = f"{tableid}"
            except discord.NotFound:
                submissionContent = str(tableid)
            except Exception as ex:
                logger.warning(f"Could not fetch submission message {messageid}: {ex}")
                submissionContent = str(tableid)
            #e.add_field(name="Submission ID", value=submissionContent, inline=True)
            
        e.add_field(name="Updated by", value=ctx.author.mention, inline=True)
        
        lossMultStr = ""
        if tier.upper() != "SQ":
            for i in range(num_players):
                if mults[i] != 1:
                    lossMultStr += (f"{mults[i]:.2f}x MMR multiplier for {goodNames[i]}\n")
        if lossMultStr:
            e.add_field(name="Notes", value=lossMultStr, inline=False)
        
        e.set_image(url="attachment://MMRTable.png")
        
        sentmsg = await channel.send(file=f, embed=e)
        
        rowNumStr = ",".join([str(rowNum) for rowNum in rowNums])
        colNumStr = ",".join([str(colNum) for colNum in colNums])
        peakChangesStr = ",".join([",".join(map(str, change)) for change in peakChanges])
        oldmmrs_str = ",".join(str(val) for val in oldMMRs)
        newmmrs_str = ",".join(str(val) for val in newMMRs)
        msgid_for_db = sentmsg.id
        db_entry = (idNum, rowNumStr, colNumStr, peakChangesStr, msgid_for_db, tier.upper(), oldmmrs_str, newmmrs_str)
        
        db = None 
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            for column_name in ("oldmmrs", "newmmrs"):
                try:
                    await c.execute(f"ALTER TABLE updated ADD COLUMN {column_name} TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass
            await c.execute("""INSERT INTO updated
                            (tableid, rowids, colids, peakChanges, msgid, tier, oldmmrs, newmmrs)
                            VALUES (?,?,?,?,?,?,?,?)
                            """, db_entry)
            await db.commit()
            # Post to updating log if configured
            try:
                log_channel_id = key_channels.get("updating_log", 0)
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(log_channel_id)
                    if log_channel:
                        le = discord.Embed(title="Table Updated", color=discord.Color.green())
                        le.add_field(name="ID", value=str(idNum), inline=True)
                        le.add_field(name="Tier", value=tier.upper(), inline=True)
                        le.add_field(name="Updated by", value=ctx.author.mention, inline=True)
                        try:
                            le.add_field(name="Message Link", value=f"[Link]({sentmsg.jump_url})", inline=False)
                        except Exception:
                            pass
                        await log_channel.send(embed=le)
            except Exception as e:
                logger.error(f"Error sending update message to log: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error inserting update {idNum} into local DB: {e}", exc_info=True)
            await ctx.send("Error saving update details to local database.", delete_after=10)
        finally:
            if db: await db.close()

    @commands.max_concurrency(number=1, wait=True)
    @commands.group(aliases=['u'])
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def update(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Please specify a subcommand like `approve`, `deny`, `text`, etc.", delete_after=10)
            return

    # @commands.max_concurrency(number=1, wait=True)
    # @update.command(aliases=['a'])
    # @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    # async def approve_all(self, ctx):
    #     if ctx.guild.id != self.config["server"]:
    #         await ctx.send("You cannot use this command in this server!", delete_after=10)
    #         return
    #     db = None
    #     try:
    #         db = await aiosqlite.connect('updating.db')
    #         c = await db.cursor()
    #         await c.execute("SELECT * from tables")
    #         tables = await c.fetchall()
    #         if not tables:
    #             return await ctx.send("There are no pending tables.")
    #         await ctx.send(f"Updating {len(tables)} tables. Please wait...")

    #         updated_tables = 0
    #         for table in tables:
    #             success = await self._approve_table_internal(ctx, table)
    #             if success:
    #                 updated_tables += 1
    #         await ctx.send(f"Successfully updated {updated_tables}/{len(tables)} tables.")

    #     except Exception as e:
    #         logger.error(f"Error fetching tables from DB: {e}", exc_info=True)
    #         await ctx.send("An error occurred while retrieving table data.", delete_after=10)
    #         return
    #     finally:
    #         if db: await db.close()
            
    # @update.command(name="approve")
    # @commands.max_concurrency(number=1, wait=True)
    # @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    # async def approve(self, ctx, tableid: int, *, extraArgs=""):
    #     """Approves a specific table by ID."""
    #     if ctx.guild.id != self.config["server"]:
    #         return await ctx.send("You cannot use this command in this server!", delete_after=10)

    #     async with aiosqlite.connect('updating.db') as db:
    #         async with db.execute("SELECT * FROM tables WHERE tableid = ?", (tableid,)) as cursor:
    #             table = await cursor.fetchone()

    #     if not table:
    #         return await ctx.send(f"Table {tableid} not found.")

    #     success = await self._approve_table_internal(ctx, table, extraArgs)
    #     if not success:
    #         await ctx.send(f"Failed to approve table {tableid}. Check logs.", delete_after=10)

    # OG Approve command that works well
    @commands.max_concurrency(number=1, wait=True)
    @update.command(aliases=['a'])
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def approve(self, ctx, tableid:int, *, extraArgs=""):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("SELECT * from tables WHERE tableid = ?", (tableid,))
            table = await c.fetchone()
            if not table:
                await ctx.send("Table couldn't be found.", delete_after=10)
                return

            size = int(table[1])
            tier = table[2].upper()
            names = table[3].split(",")
            placements = table[4].split(",")
            messageid = table[6]
        except Exception as e:
            logger.error(f"Error fetching table {tableid} from DB: {e}", exc_info=True)
            await ctx.send("An error occurred while retrieving table data.", delete_after=10)
            return
        finally:
            if db: await db.close()
            
        arguments = extraArgs.split(";")
        instructions = {}
        if tier.upper() == "SQ":
            for i in range(num_players):
                instructions[i+1] = 0.75
                
        elif len(arguments) > 0:
            try:
                instructions = await self.processInstructions(ctx, tier, arguments[0])
            except Exception:
                return
        mults = []
        for i in range(num_players):
            if(i+1) in instructions.keys():
                mults.append(instructions[i+1])
            else:
                mults.append(1)

        races = 1
        if len(arguments) > 1:
            try:
                raceArg = int(arguments[1])
            except ValueError:
                await ctx.send("The number of races you entered is not a valid integer; try again.", delete_after=10)
                return
            if raceArg != 1:
                await ctx.send("The number of races you entered is not 1; try again.", delete_after=10)
                return
            races = raceArg
        
        try:
            await self.updateTable(ctx, size, tier, names, placements, mults, races, messageid, tableid)
        except Exception as e:
            logger.error(f"Error in updateTable for table {tableid}: {e}", exc_info=True)
            await ctx.send("An error occurred during table update.", delete_after=10)
            return
        
        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("DELETE from tables WHERE tableid = ?", (tableid,))
            await db.commit()
        except Exception as e:
            logger.error(f"Database error removing table {tableid} from approval queue: {e}", exc_info=True)
            await ctx.send("Database error removing table from approval queue.", delete_after=10)
            return
        finally:
            if db: await db.close()
        
        channel = ctx.guild.get_channel(channels[tier.upper()])
        if channel:
            try:
                reactMsg = await channel.fetch_message(messageid)
                CHECK_BOX = "\U00002611"
                await reactMsg.add_reaction(CHECK_BOX)
            except discord.NotFound:
                logger.warning(f"Message {messageid} not found in channel {channel.id} for reaction.")
            except Exception as e:
                logger.error(f"Error adding reaction to message {messageid}: {e}", exc_info=True)
        else:
            logger.warning(f"Channel for tier {tier.upper()} not found.")


    # OG Approve command that works well
    @commands.max_concurrency(number=1, wait=True)
    @update.command(aliases=["all"])
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def approve_all(self, ctx, *, extraArgs=""):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        db = None
        tables_list = []
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("SELECT * from tables")
            tables = await c.fetchall()
            if not tables:
                await ctx.send("No tables found.", delete_after=10)
                return
            
            for table in tables:
                tableid = int(table[0])
                size = int(table[1])
                tier = table[2].upper()
                names = table[3].split(",")
                placements = table[4].split(",")
                messageid = table[6]
                tables_list.append({
                    "tableid": tableid,
                    "size": size,
                    "tier": tier,
                    "names": names,
                    "placements": placements,
                    "messageid": messageid
                })

        except Exception as e:
            logger.error(f"Error fetching table {tableid} from DB: {e}", exc_info=True)
            await ctx.send("An error occurred while retrieving table data.", delete_after=10)
            return
        finally:
            if db: await db.close()
        
        
        arguments = extraArgs.split(";")
        instructions = {}
        if tier.upper() == "SQ":
            for i in range(num_players):
                instructions[i+1] = 0.75
                
        elif len(arguments) > 0:
            try:
                instructions = await self.processInstructions(ctx, tier, arguments[0])
            except Exception:
                return
        mults = []
        for i in range(num_players):
            if(i+1) in instructions.keys():
                mults.append(instructions[i+1])
            else:
                mults.append(1)

        races = 1
        if len(arguments) > 1:
            try:
                raceArg = int(arguments[1])
            except ValueError:
                await ctx.send("The number of races you entered is not a valid integer; try again.", delete_after=10)
                return
            if raceArg != 1:
                await ctx.send("The number of races you entered is not 1; try again.", delete_after=10)
                return
            races = raceArg

        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()

            for table in tables_list:
                tableid   = table["tableid"]
                size      = table["size"]
                tier      = table["tier"]
                names     = table["names"]
                placements = table["placements"]
                messageid = table["messageid"]

                # Step 1: Update the table
                try:
                    await self.updateTable(ctx, size, tier, names, placements, mults, races, messageid, tableid)
                except Exception as e:
                    logger.error(f"Error in updateTable for table {tableid}: {e}", exc_info=True)
                    await ctx.send("An error occurred during table update.", delete_after=10)
                    return

                # Step 2: Remove from DB
                try:
                    await c.execute("DELETE FROM tables WHERE tableid = ?", (tableid,))
                    await db.commit()
                except Exception as e:
                    logger.error(f"Database error removing table {tableid} from approval queue: {e}", exc_info=True)
                    await ctx.send("Database error removing table from approval queue.", delete_after=10)
                    return

                # Step 3: Add reaction to the message
                channel = ctx.guild.get_channel(channels[tier.upper()])
                if channel:
                    try:
                        react_msg = await channel.fetch_message(messageid)
                        await react_msg.add_reaction("\U00002611")
                    except discord.NotFound:
                        logger.warning(f"Message {messageid} not found in channel {channel.id} for reaction.")
                    except Exception as e:
                        logger.error(f"Error adding reaction to message {messageid}: {e}", exc_info=True)
                else:
                    logger.warning(f"Channel for tier {tier.upper()} not found.")

        except Exception as e:
            logger.error(f"Unexpected error during batch update: {e}", exc_info=True)
        finally:
            if db:
                await db.close()
        
        # try:
        #     for table in tables_list:
        #         tableid = table["tableid"]
        #         size = table["size"]
        #         tier = table["tier"]
        #         names = table["names"]
        #         placements = table["placements"]
        #         messageid = table["messageid"]
        #         await self.updateTable(ctx, size, tier, names, placements, mults, races, messageid, tableid)
        # except Exception as e:
        #     logger.error(f"Error in updateTable for table {tableid}: {e}", exc_info=True)
        #     await ctx.send("An error occurred during table update.", delete_after=10)
        #     return
        
        # db = None
        # try:
        #     db = await aiosqlite.connect('updating.db')
        #     c = await db.cursor()
        #     for table in tables_list:
        #         tableid = table["tableid"]
        #         await c.execute("DELETE from tables WHERE tableid = ?", (tableid,))
        #     await db.commit()
        # except Exception as e:
        #     logger.error(f"Database error removing table {tableid} from approval queue: {e}", exc_info=True)
        #     await ctx.send("Database error removing table from approval queue.", delete_after=10)
        #     return
        # finally:
        #     if db: await db.close()
        
        # channel = ctx.guild.get_channel(channels[tier.upper()])
        # if channel:
        #     try:
        #         for table in tables_list:
        #             messageid = table["messageid"]
        #             reactMsg = await channel.fetch_message(messageid)
        #             CHECK_BOX = "\U00002611"
        #             await reactMsg.add_reaction(CHECK_BOX)
        #     except discord.NotFound:
        #         logger.warning(f"Message {messageid} not found in channel {channel.id} for reaction.")
        #     except Exception as e:
        #         logger.error(f"Error adding reaction to message {messageid}: {e}", exc_info=True)
        # else:
        #     logger.warning(f"Channel for tier {tier.upper()} not found.")


    @commands.max_concurrency(number=1, wait=True)
    @update.command(aliases=['d'])
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def deny(self, ctx, tableid:int):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        messageid = None
        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("SELECT * from tables WHERE tableid = ?", (tableid,))
            table = await c.fetchone()
            if not table:
                await ctx.send("Table couldn't be found.", delete_after=10)
                return
            tier = table[2].upper()
            messageid = table[6]
        except Exception as e:
            logger.error(f"Error fetching table {tableid} from DB: {e}", exc_info=True)
            await ctx.send("An error occurred while retrieving table data.", delete_after=10)
            return
        finally:
            if db: await db.close()


        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("DELETE from tables WHERE tableid = ?", (tableid,))
            await db.commit()
            await ctx.send(f"Removed table {tableid} from approval queue.")
            # Log denial to updating log
            try:
                log_channel_id = key_channels.get("updating_log", 0)
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(log_channel_id)
                    if log_channel:
                        le = discord.Embed(title="Table Denied", color=discord.Color.dark_red())
                        le.add_field(name="ID", value=str(tableid), inline=True)
                        le.add_field(name="Denied by", value=ctx.author.mention, inline=True)
                        await log_channel.send(embed=le)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Database error denying table {tableid}: {e}", exc_info=True)
            await ctx.send("Database error removing table from approval queue.", delete_after=10)
            return
        finally:
            if db: await db.close()

        channel = ctx.guild.get_channel(channels[tier.upper()])
        if channel:
            try:
                # reactMsg = await channel.fetch_message(messageid)
                # X_MARK = "\U0000274C"
                # await reactMsg.add_reaction(X_MARK)
                msg = await channel.fetch_message(messageid)
                await msg.delete()
            except discord.NotFound:
                logger.warning(f"Message {messageid} not found in channel {channel.id} for reaction.")
            except Exception as e:
                logger.error(f"Error adding reaction to message {messageid}: {e}", exc_info=True)
        else:
            logger.warning(f"Channel for tier {tier.upper()} not found.")


    
    @update.command(aliases=['u'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def undo(self, ctx, idNum: int):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        pHistory = await sh.worksheet("Player History")
        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("SELECT * from updated WHERE tableid = ?", (idNum,))
            table = await c.fetchone()
            if not table:
                await ctx.send("Table not found in local database.", delete_after=10)
                return
            rowids = table[1].split(",")
            colids = table[2].split(",")
            peakchanges = table[3].split(",")
            msgid = table[4]
            tier = table[5]
            oldmmrs = table[6].split(",") if len(table) > 6 and table[6] else []
            newmmrs = table[7].split(",") if len(table) > 7 and table[7] else []
            clearedCells = []
            for i in range(num_players):
                clearCell = {'range': rowcol_to_a1(int(rowids[i])+rowOffset, int(colids[i])+colOffset),
                             'values': [['']]}
                clearedCells.append(clearCell)
            for i in range(int(len(peakchanges)/2)):
                oldpeak_val = peakchanges[2*i+1]
                if oldpeak_val != "N/A":
                    oldpeak = int(oldpeak_val)
                else:
                    oldpeak = oldpeak_val
                peakCell = {'range': f"{peakColumn}{int(peakchanges[2*i])}",
                            'values': [[oldpeak]]}
                clearedCells.append(peakCell)
            player_names = []
            for i in range(num_players):
                row_num = int(rowids[i]) + rowOffset
                name_value = ""
                for name_col in (1, int(colids[i]) + colOffset - 1):
                    name_cell = await pHistory.acell(rowcol_to_a1(row_num, name_col))
                    if name_cell.value and str(name_cell.value).strip():
                        name_value = str(name_cell.value).strip()
                        break
                player_names.append(name_value)

            for i, player_name in enumerate(player_names):
                if not player_name or not oldmmrs or not newmmrs or i >= len(oldmmrs) or i >= len(newmmrs):
                    continue
                await self._apply_rank_change_for_player(
                    ctx,
                    player_name,
                    newmmrs[i],
                    oldmmrs[i],
                )

            # Use separate request payload copies for each worksheet to avoid gspread mutating the shared list
            await pHistory.batch_update(
                [{'range': cell['range'], 'values': cell['values']} for cell in clearedCells]
            )
            channel = ctx.guild.get_channel(channels[tier.upper()])
            await c.execute("DELETE from updated WHERE tableid = ?", (idNum,))
            await db.commit()
            if channel:
                try:
                    msg = await channel.fetch_message(msgid)
                    await msg.delete()
                except discord.NotFound:
                    logger.warning(f"Message {msgid} not found for undo operation in channel {channel.id}.")
                except Exception as e:
                    logger.error(f"Error deleting message {msgid} during undo: {e}", exc_info=True)
            # Log undo to updating log
            try:
                log_channel_id = key_channels.get("updating_log", 0)
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(log_channel_id)
                    if log_channel:
                        le = discord.Embed(title="Table Undone", color=discord.Color.orange())
                        le.add_field(name="ID", value=str(idNum), inline=True)
                        le.add_field(name="Undone by", value=ctx.author.mention, inline=True)
                        try:
                            le.add_field(name="Message ID", value=str(msgid), inline=True)
                        except Exception:
                            pass
                        await log_channel.send(embed=le)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error during undo operation for ID {idNum}: {e}", exc_info=True)
            await ctx.send("An error occurred during the undo operation.", delete_after=10)
            return
        finally:
            if db: await db.close()
        if channel != ctx.channel:
            await ctx.send("Undo operation completed.")


    @update.command(aliases=['rl'])
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def reduceloss(self, ctx, idNum: int, *, playerName: str):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return

        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        pHistory = await sh.worksheet("Player History")

        db = None
        try:
            db = await aiosqlite.connect('updating.db')
            c = await db.cursor()
            await c.execute("SELECT * from updated WHERE tableid = ?", (idNum,))
            table = await c.fetchone()
            if not table:
                await ctx.send("Table not found in local database.", delete_after=10)
                return

            rowids = table[1].split(",")
            colids = table[2].split(",")
            peakchanges = table[3].split(",")
            msgid = table[4]
            tier = table[5]

            # Find the player by name (case-insensitive partial match)
            # We need to fetch the actual names from the sheet to match against playerName
            # Build a list of (index, row, col) for all players in this table
            player_cells = []
            for i in range(num_players):
                row = int(rowids[i]) + rowOffset
                col = int(colids[i]) + colOffset
                player_cells.append((i, row, col))

            # Fetch the name column for each player row from Player History
            # Names are assumed to be one column to the left of the MMR change column (adjust if needed)
            name_col = 1  # the name column index in the sheet (1-based); adjust to your layout
            name_ranges = [rowcol_to_a1(row, name_col) for (_, row, _) in player_cells]
            name_values = await pHistory.batch_get(name_ranges)

            # Find matching player index
            matched_index = None
            matched_row = None
            matched_col = None
            for i, name_cell in enumerate(name_values):
                cell_name = name_cell[0][0].strip() if name_cell and name_cell[0] else ""
                if cell_name.lower() == playerName.lower():
                    matched_index = player_cells[i][0]
                    matched_row = player_cells[i][1]
                    matched_col = player_cells[i][2]
                    break

            if matched_index is None:
                await ctx.send(
                    f"Player `{playerName}` not found in table `{idNum}`. "
                    f"Check the name and try again.",
                    delete_after=10
                )
                return

            # Clear only that player's MMR change cell
            clear_range = rowcol_to_a1(matched_row, matched_col)
            clear_payload = [{'range': clear_range, 'values': [['']]}]

            oldmmrs = table[6].split(",") if len(table) > 6 and table[6] else []
            newmmrs = table[7].split(",") if len(table) > 7 and table[7] else []
            if matched_index is not None and matched_index < len(oldmmrs) and matched_index < len(newmmrs):
                await self._apply_rank_change_for_player(
                    ctx,
                    playerName,
                    newmmrs[matched_index],
                    oldmmrs[matched_index],
                )

            await pHistory.batch_update(clear_payload)
            # Log to results channel
            channel = ctx.guild.get_channel(channels[tier.upper()])
            if channel:
                le = discord.Embed(title="MMR Loss Reduction Applied", color=discord.Color.blue())
                le.add_field(name="Table ID", value=str(idNum), inline=True)
                le.add_field(name="Player", value=playerName, inline=True)
                le.add_field(name="Done by", value=ctx.author.mention, inline=True)
                le.add_field(name="Reason", value="Disconnect before start", inline=True)
                await channel.send(embed=le)
            # Log to updating log
            try:
                log_channel_id = key_channels.get("updating_log", 0)
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(log_channel_id)
                    if log_channel:
                        le = discord.Embed(title="MMR Loss Reduction Applied", color=discord.Color.blue())
                        le.add_field(name="Table ID", value=str(idNum), inline=True)
                        le.add_field(name="Player", value=playerName, inline=True)
                        le.add_field(name="Done by", value=ctx.author.mention, inline=True)
                        le.add_field(name="Reason", value="Disconnect before start", inline=True)
                        await log_channel.send(embed=le)
            except Exception:
                pass

            await ctx.send(f"MMR change for `{playerName}` in table `{idNum}` has been cleared.")

        except Exception as e:
            logger.error(f"Error during reduceloss for ID {idNum}, player {playerName}: {e}", exc_info=True)
            await ctx.send("An error occurred during the reduceloss operation.", delete_after=10)
        finally:
            if db:
                await db.close()
                

    @update.command(aliases=['s'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def strike(self, ctx, amount:int, tier, *, args):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        if amount < 0:
            await ctx.send("Please enter a positive amount.", delete_after=10)
            return
        if tier.upper() not in channels.keys():
            await ctx.send("Please enter a valid tier.", delete_after=10)
            return
        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("Bot")
        pHistory = await sh.worksheet("Player History")
        strikeSheet = await sh.worksheet("Strikes")
        channel = ctx.guild.get_channel(pen_channel)
        arguments = args.split(";")
        playername = arguments[0].strip()
        reason = ""
        if len(arguments) > 1:
            reason = arguments[1].strip()
        print(playername, amount, tier, reason)
        updateCells = [{'range': rowcol_to_a1(pen_row, pen_cols[0]),
                        'values': [[playername]]},
                       {'range': rowcol_to_a1(pen_row, pen_cols[1]),
                        'values': [[amount]]}]
        await botSheet.batch_update(updateCells)
        info = await botSheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
        print(info)
        strikes = info[0][0][4:7]
        pHrow = info[0][0][2]
        if pHrow == "#N/A":
            await ctx.send("This player is not on the sheet; check your input and try again.", delete_after=10)
            return
        strikeRow = info[0][0][1]
        newRow = info[0][0][0]
        goodName = info[0][0][8]
        
        offset = 0
        for strike in strikes:
            if strike == "":
                break
            offset += 1
        if offset == 3:
            await ctx.send("This player already has 3 strikes; if you believe this isn't correct, please remove the extra strikes from the sheet.")
            return
        updateCells = []
        if strikeRow == "Not found":
            rowUpdate = int(newRow)
            updateCells.append({'range': f"A{rowUpdate}",
                        'values': [[goodName]]})
        else:
            rowUpdate = int(strikeRow)
            
        pens = int(info[0][0][3])
        mmr = int(info[0][0][7])
        while mmr - amount < 0:
            amount -= 1
        pens += amount
        
        today = date.today()
        todaysdate = today.strftime("%m/%d/%y")
        m, d, y = map(int, todaysdate.split("/"))
        m += 1
        if m > 12:
            m-=12
            y+=1
        expireDate = f"{m}/{d}/{y}"

        updateCells.append({'range': rowcol_to_a1(rowUpdate, 4+offset),
                        'values': [[todaysdate]]})
        await strikeSheet.batch_update(updateCells)
        print(pens)
        await pHistory.update_cell(int(pHrow), 4, pens)
        
        content = f"Successfully added -{amount} and strike to {goodName}"
            
        e = discord.Embed(title="Strike + penalty added", color=discord.Color.red())
        e.add_field(name="Player", value=goodName, inline=False)
        e.add_field(name="Penalty", value=f"-{amount} MMR:\n{mmr} -> {mmr-amount}", inline=False)
        
        strikecount = 0
        strikeData = ""
        for i in range(3):
            if info[0][0][4+i] == "":
                continue
            m_str, d_str, y_str = str(info[0][0][4+i]).split("/")
            m, d, y = int(m_str), int(d_str), int(y_str)
            m+=1
            if m > 12:
                m-=12
                y+=1
            strikeData += (f"\nStrike {strikecount+1}: expires on {m}/{d}/{y}")
            strikecount += 1
        strikeData += (f"\nStrike {strikecount+1}: expires on {expireDate}")
        strikeData = f"{strikecount+1}/3 strikes\n{strikeData}"
        e.add_field(name="Strike info", value=strikeData, inline=False)

        if strikecount + 1 == 3:
            content += (f"\n{ctx.author.mention} player {goodName} has reached the strike limit and should be muted")
        msg = await ctx.send(content)
        if ctx.channel == channel:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            await msg.delete(delay=15)

        if reason != "":
            e.add_field(name="Reason", value=reason, inline=False)
        
        if channel:
            await channel.send(embed=e)
        else:
            logger.warning(f"Channel for tier {tier.upper()} not found for strike embed.")


    @update.command(aliases=['pen'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def penalty(self, ctx, amount:int, tier, *, args):
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        if amount < 0:
            await ctx.send("Please enter a positive amount.", delete_after=10)
            return
        if tier.upper() not in channels.keys():
            await ctx.send("Please enter a valid tier.", delete_after=10)
            return
        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("Bot")
        pHistory = await sh.worksheet("Player History")
        channel = ctx.guild.get_channel(pen_channel)
        arguments = args.split(";")
        playername = arguments[0].strip()
        reason = ""
        if len(arguments) > 1:
            reason = arguments[1].strip()
        
        updateCells = [{'range': rowcol_to_a1(pen_row, pen_cols[0]),
                        'values': [[playername]]},
                       {'range': rowcol_to_a1(pen_row, pen_cols[1]),
                        'values': [[amount]]}]
        await botSheet.batch_update(updateCells)
        info = await botSheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
        pHrow = info[0][0][2]
        if pHrow == "#N/A":
            await ctx.send("This player is not on the sheet; check your input and try again.", delete_after=15)
            return
        pens = int(info[0][0][3])
        mmr = info[0][0][7]
        goodName = info[0][0][8]
        if mmr == "Placement":
            await ctx.send(f"Player {goodName} needs to be given Placement MMR before they can receive a penalty!", delete_after=15)
            return
        while int(mmr) - amount < 0:
            amount -= 1
        pens += amount
        await pHistory.update_cell(int(pHrow), 4, pens)
        e = discord.Embed(title="Penalty added", color=discord.Color.orange())
        e.add_field(name="Player", value=goodName, inline=False)
        e.add_field(name="Penalty", value=f"-{amount} MMR:\n{int(mmr)} -> {int(mmr)-amount}", inline=False)
        if reason != "":
            e.add_field(name="Reason", value=reason, inline=False)
        if channel:
            await channel.send(embed=e)
        else:
            logger.warning(f"Channel for tier {tier.upper()} not found for penalty embed.")

        if channel == ctx.channel:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
        else:
            await ctx.send(f"-{amount} penalty given to {goodName} in {channel.mention}")

    @update.command(aliases=['us', 'uns'])
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def unstrike(self, ctx, amount: int, tier, *, args):
        """Reverts a strike and removes the associated MMR penalty."""
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        
        if amount < 0:
            await ctx.send("Please enter a positive amount to restore.", delete_after=10)
            return

        if tier.upper() not in channels.keys():
            await ctx.send("Please enter a valid tier.", delete_after=10)
            return

        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("Bot")
        pHistory = await sh.worksheet("Player History")
        strikeSheet = await sh.worksheet("Strikes")
        channel = ctx.guild.get_channel(pen_channel)

        arguments = args.split(";")
        playername = arguments[0].strip()
        reason = arguments[1].strip() if len(arguments) > 1 else ""

        updateCells = [{'range': rowcol_to_a1(pen_row, pen_cols[0]), 'values': [[playername]]},
                       {'range': rowcol_to_a1(pen_row, pen_cols[1]), 'values': [[0]]}]
        await botSheet.batch_update(updateCells)
        
        info = await botSheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
        data = info[0][0]
        
        pHrow = data[2]
        if pHrow == "#N/A":
            await ctx.send(f"{playername} is not on the sheet; check your input.", delete_after=10)
            return

        strikeRow = data[1]
        strikes = data[4:7]
        goodName = data[8]
        current_pens = int(data[3])
        current_mmr = int(data[7])

        # Find the index of the most recent strike to remove
        strike_index = -1
        for i in range(len(strikes) - 1, -1, -1):
            if strikes[i] != "":
                strike_index = i
                break
        
        if strike_index == -1 and amount == 0:
            await ctx.send(f"{goodName} has no strikes or penalties to revert.", delete_after=10)
            return

        strike_updates = []
        if strikeRow != "Not found" and strike_index != -1:
            strike_col = 4 + strike_index
            strike_updates.append({'range': rowcol_to_a1(int(strikeRow), strike_col),
                                   'values': [[""]]})
            await strikeSheet.batch_update(strike_updates)

        # Update MMR Penalties in Player History
        new_pens = max(0, current_pens - amount)
        await pHistory.update_cell(int(pHrow), 4, new_pens)

        # Build Response Embed
        e = discord.Embed(title="Strike / Penalty Reverted", color=discord.Color.blue())
        e.add_field(name="Player", value=goodName, inline=False)
        
        action_desc = []
        if strike_index != -1:
            action_desc.append(f"Removed Strike #{strike_index + 1}")
        if amount > 0:
            action_desc.append(f"Restored {amount} MMR ({current_mmr} -> {current_mmr + amount})")
        
        e.add_field(name="Action Taken", value="\n".join(action_desc), inline=False)
        
        if reason:
            e.add_field(name="Appeal Reason", value=reason, inline=False)
        
        if channel:
            await channel.send(embed=e)
        
        msg = await ctx.send(f"Successfully removed penalty + strike for {goodName}.")
        
        if ctx.channel == channel:
            try:
                await ctx.message.delete()
                await msg.delete(delay=10)
            except:
                pass

    @update.command(aliases=['up', 'unp'])
    @commands.max_concurrency(number=1, wait=True)
    @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    async def unpen(self, ctx, amount: int, tier, *, args):
        """Reverts an MMR penalty for a player without affecting strikes."""
        if ctx.guild.id != self.config["server"]:
            await ctx.send("You cannot use this command in this server!", delete_after=10)
            return
        
        if amount < 0:
            await ctx.send("Please enter a positive amount to restore.", delete_after=10)
            return

        if tier.upper() not in channels.keys():
            await ctx.send("Please enter a valid tier.", delete_after=10)
            return

        agc = await agcm.authorize()
        sh = await agc.open_by_key(SH_KEY)
        botSheet = await sh.worksheet("Bot")
        pHistory = await sh.worksheet("Player History")
        channel = ctx.guild.get_channel(pen_channel)

        arguments = args.split(";")
        playername = arguments[0].strip()
        reason = arguments[1].strip() if len(arguments) > 1 else ""

        updateCells = [
            {'range': rowcol_to_a1(pen_row, pen_cols[0]), 'values': [[playername]]},
            {'range': rowcol_to_a1(pen_row, pen_cols[1]), 'values': [[0]]}
        ]
        await botSheet.batch_update(updateCells)
        
        info = await botSheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
        data = info[0][0]
        
        pHrow = data[2]
        if pHrow == "#N/A":
            await ctx.send(f"{playername} is not on the sheet; check your input.", delete_after=10)
            return

        current_pens = int(data[3])
        current_mmr = data[7]
        goodName = data[8]

        new_pens = max(0, current_pens - amount)
        
        await pHistory.update_cell(int(pHrow), 4, new_pens)

        e = discord.Embed(title="Penalty Reverted", color=discord.Color.green())
        e.add_field(name="Player", value=goodName, inline=False)
        e.add_field(name="Restored MMR", value=f"{amount} MMR", inline=True)
        
        if current_mmr != "Placement":
            e.add_field(name="MMR Adjustment", value=f"{current_mmr} -> {int(current_mmr) + amount}", inline=True)
        
        if reason:
            e.add_field(name="Reason", value=reason, inline=False)
        
        if channel:
            await channel.send(embed=e)
        
        msg = await ctx.send(f"Successfully removed -{amount} penalty from {goodName}.")
        
        if ctx.channel == channel:
            try:
                await ctx.message.delete()
                await msg.delete(delay=10)
            except (discord.Forbidden, discord.HTTPException):
                pass

    # TODO: uncomment if placement becomes a thing again
    # @update.command(aliases=['pl'])
    # @commands.max_concurrency(number=1,wait=True)
    # @commands.has_any_role("Administrator", "Updater", "Lounge Staff")
    # async def place(self, ctx, rank, *, playername):
    #     if ctx.guild.id != self.config["server"]:
    #         await ctx.send("You cannot use this command in this server!", delete_after=10)
    #         return
    #     if rank.lower() not in place_MMRs.keys():
    #         await ctx.send(f"Please enter one of the following ranks: {', '.join(place_MMRs.keys())}", delete_after=10)
    #         return
    #     placemmr = place_MMRs[rank.lower()]
    #     agc = await agcm.authorize()
    #     sh = await agc.open_by_key(SH_KEY)
    #     botSheet = await sh.worksheet("Bot")
    #     pHistory = await sh.worksheet("Player History")
    #     await botSheet.update_cell(pen_row, pen_cols[0], playername)
    #     info = await botSheet.batch_get([f"{get_strike_info[0]}:{get_strike_info[1]}"])
    #     pHrow = info[0][0][2]
    #     mmr = info[0][0][7]
    #     if pHrow == "#N/A" or len(info[0][0]) < 8:
    #         await ctx.send("This player is not on the sheet; check your input and try again.", delete_after=15)
    #         return
    #     goodName = info[0][0][8]
        
    #     if mmr != "Placement":
    #         await ctx.send("This player does not have Placement MMR! Check the sheet and try again.", delete_after=15)
    #         return
    #     await pHistory.update_cell(pHrow, 7, placemmr)
    #     try:
    #         await ctx.message.delete()
    #     except discord.HTTPException:
    #         pass
    #     await ctx.send(f"Successfully placed {goodName} in {rank.lower()} with {placemmr} MMR; make sure to give them the {rank.lower()} role in server!")

    @commands.command(name="assignranks")
    @commands.has_any_role("Administrator", "Lounge Staff")
    async def assignranks(self, ctx):
        """
        Assigns a rank role to every member with the Player role based on
        their current MMR in Player History. Run once at the start of a season.
        """
        if ctx.guild.id != self.config["server"]:
            return

        status_msg = await ctx.send("fetching player data from sheet…")

        agc = await agcm.authorize()
        sh  = await agc.open_by_key(SH_KEY)
        ph  = await sh.worksheet("Player History")

        # Column A = name, column E = current MMR (adjust if your layout differs)
        name_col = await ph.col_values(1)
        mmr_col  = await ph.col_values(5)

        # Build a name → MMR lookup (lowercase keys for case-insensitive matching)
        sheet_data = {}
        for i, name in enumerate(name_col):
            name = name.strip()
            if not name:
                continue
            mmr_val = mmr_col[i].strip() if i < len(mmr_col) else ""
            try:
                sheet_data[name.lower()] = int(mmr_val)
            except (ValueError, TypeError):
                pass  # skip header or non-numeric MMR cells

        # ── Collect all rank role objects ─────────────────────────────────────
        rank_roles = {
            rank_name: ctx.guild.get_role(info["roleid"])
            for rank_name, info in ranks.items()
        }
        all_rank_roles = [r for r in rank_roles.values() if r is not None]

        # ── Get the Player role ───────────────────────────────────────────────
        player_role = discord.utils.get(ctx.guild.roles, name="Player")
        if player_role is None:
            await status_msg.edit(content="could not find the **Player** role.")
            return

        players = [m for m in ctx.guild.members if player_role in m.roles and not m.bot]
        await status_msg.edit(content=f"assigning ranks to {len(players)} players…")

        assigned  = 0
        skipped   = []

        for member in players:
            display = member.display_name.strip().lower()

            if display not in sheet_data:
                skipped.append(f"• **{member.display_name}** — not found in sheet")
                continue

            mmr = sheet_data[display]
            rank_name = getRank(mmr)
            new_role = rank_roles.get(rank_name)

            if new_role is None:
                skipped.append(f"• **{member.display_name}** — rank `{rank_name}` has no role configured")
                continue

            # Remove all existing rank roles, then add the correct one
            roles_to_remove = [r for r in member.roles if r in all_rank_roles and r != new_role]
            try:
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Season rank reset")
                if new_role not in member.roles:
                    await member.add_roles(new_role, reason=f"Season rank assignment: {rank_name}")
                assigned += 1
            except discord.Forbidden:
                skipped.append(f"• **{member.display_name}** — missing permissions to edit roles")
            except discord.HTTPException as e:
                skipped.append(f"• **{member.display_name}** — HTTP error: `{e}`")

            # Small delay to avoid hitting Discord's rate limit on role edits
            await asyncio.sleep(0.2)

        # ── Final report ──────────────────────────────────────────────────────
        summary = f"done. **{assigned}/{len(players)}** players assigned ranks."
        if skipped:
            skipped_text = "\n".join(skipped)
            # Split into chunks if too long for a single message
            if len(skipped_text) > 1800:
                skipped_text = skipped_text[:1800] + "\n… (truncated)"
            summary += f"\n\n**Skipped ({len(skipped)}):**\n{skipped_text}"

        await status_msg.edit(content=summary)

    async def processInstructions(self, ctx: commands.Context, tier: str, instructions_str: str):
        returnInstructions = {}
        if len(instructions_str) > 0:
            strings = instructions_str.split(",")
            for string in strings:
                idAmount = string.split()
                if len(idAmount) != 2:
                    await ctx.send(f"Your instruction `{string}` needs to have 2 arguments separated by spaces.", delete_after=15)
                    raise ValueError("Instruction format error")
                try:
                    playerID = int(idAmount[0].strip())
                except ValueError:
                    await ctx.send(f"Your first argument in instruction `{string}` is not an integer!", delete_after=15)
                    raise ValueError("Player ID not integer")
                if not (1 <= playerID <= 12): # Assuming 12 is max player ID in a table
                    await ctx.send(f"Your first argument in instruction `{string}` needs to be between 1 and 12.", delete_after=15)
                    raise ValueError("Player ID out of range")
                try:
                    multiplier = float(idAmount[1].strip())
                except ValueError:
                    await ctx.send(f"Your second argument in instruction `{string}` is not a valid number!", delete_after=15)
                    raise ValueError("Multiplier not float")
                if not (0 <= multiplier <= 2): # Assuming multiplier range 0-2
                    await ctx.send(f"Your second argument in instruction `{string}` is not a float between 0-2!", delete_after=15)
                    raise ValueError("Multiplier out of range")
                returnInstructions[playerID] = multiplier
        return returnInstructions
        
        
async def setup(bot):
    await bot.add_cog(Updating(bot))

