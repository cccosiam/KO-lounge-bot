import aiosqlite
import asyncio

async def migrate():
    async with aiosqlite.connect('updating.db') as db:
        await db.execute("ALTER TABLE updated ADD COLUMN placements TEXT DEFAULT ''")
        await db.commit()

asyncio.run(migrate())