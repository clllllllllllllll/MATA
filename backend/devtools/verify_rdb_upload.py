import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

QUERIES = {
    "residents": """
        SELECT COUNT(*) FROM residents;
    """,
    "resident_postings": """
        SELECT COUNT(*) FROM resident_postings;
    """,
    "posting_codes": """
        SELECT COUNT(*) FROM posting_codes;
    """,
    "upload_logs": """
        SELECT COUNT(*) FROM upload_logs WHERE upload_type = 'rdb';
    """,
    "status_distribution": """
        SELECT status, COUNT(*)
        FROM resident_postings
        GROUP BY status
        ORDER BY status;
    """,
    "null_r_year": """
        SELECT COUNT(*)
        FROM resident_postings
        WHERE r_year IS NULL;
    """,
    "employed_rows": """
        SELECT COUNT(*)
        FROM resident_postings
        WHERE status = 'employed';
    """,
    "orphan_posting_codes": """
        SELECT COUNT(*)
        FROM resident_postings rp
        LEFT JOIN posting_codes pc ON pc.code = rp.posting_code
        WHERE rp.posting_code IS NOT NULL
        AND pc.code IS NULL;
    """,
    "duplicate_phases": """
        SELECT resident_id, reporting_period_id, start_date, COUNT(*)
        FROM resident_postings
        GROUP BY resident_id, reporting_period_id, start_date
        HAVING COUNT(*) > 1;
    """,
    "latest_upload_logs": """
        SELECT upload_type, reporting_period_id, summary
        FROM upload_logs
        WHERE upload_type = 'rdb'
        ORDER BY created_at DESC
        LIMIT 3;
    """,
}

async def main():
    async with AsyncSessionLocal() as session:
        for name, sql in QUERIES.items():
            print(f"\n=== {name} ===")
            result = await session.execute(text(sql))
            rows = result.fetchall()
            for row in rows:
                print(row)

asyncio.run(main())