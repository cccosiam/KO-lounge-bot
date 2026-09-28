import aiosqlite
import asyncio

async def migrate():
    async with aiosqlite.connect('updating.db') as db:
        for column_name in ("placements", "scores"):
            try:
                await db.execute(
                    f"ALTER TABLE updated ADD COLUMN {column_name} TEXT DEFAULT ''"
                )
            except aiosqlite.OperationalError:
                pass
        await db.commit()

asyncio.run(migrate())