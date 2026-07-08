"""Enable RLS on remaining public app reference tables.

Revision ID: 20260708_000015
Revises: 20260704_000014
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op


revision = "20260708_000015"
down_revision = "20260704_000014"
branch_labels = None
depends_on = None


RLS_TABLES = (
    "alembic_version",
    "academic_month_boundaries",
    "event_series",
    "global_session_types",
    "loa_types",
    "multi_posting_rules",
    "posting_codes",
    "posting_groups",
    "programmes",
    "public_holidays",
    "reporting_periods",
    "secretary_programme_pools",
    "session_types",
    "weekend_exceptions",
)


ENABLE_ROW_LEVEL_SECURITY_SQL = (
    'ALTER TABLE IF EXISTS public."alembic_version" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."academic_month_boundaries" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."event_series" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."global_session_types" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."loa_types" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."multi_posting_rules" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."posting_codes" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."posting_groups" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."programmes" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."public_holidays" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."reporting_periods" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."secretary_programme_pools" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."session_types" ENABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."weekend_exceptions" ENABLE ROW LEVEL SECURITY',
)


DISABLE_ROW_LEVEL_SECURITY_SQL = (
    'ALTER TABLE IF EXISTS public."alembic_version" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."academic_month_boundaries" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."event_series" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."global_session_types" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."loa_types" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."multi_posting_rules" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."posting_codes" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."posting_groups" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."programmes" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."public_holidays" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."reporting_periods" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."secretary_programme_pools" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."session_types" DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE IF EXISTS public."weekend_exceptions" DISABLE ROW LEVEL SECURITY',
)


def upgrade() -> None:
    for statement in ENABLE_ROW_LEVEL_SECURITY_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DISABLE_ROW_LEVEL_SECURITY_SQL:
        op.execute(statement)
