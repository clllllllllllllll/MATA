import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT id, label, start_date, end_date
                FROM reporting_periods
                ORDER BY created_at DESC
                LIMIT 10
            """)
        )
        for row in result:
            print(row)

asyncio.run(main())