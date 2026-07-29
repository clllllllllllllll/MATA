"""revoke browser-role access to backend-owned application objects

Revision ID: 20260722_000024
Revises: 20260722_000023
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op


revision = "20260722_000024"
down_revision = "20260722_000023"
branch_labels = None
depends_on = None


PUBLIC_OBJECT_REVOKES = (
    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC",
    "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC",
    "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC",
)

PUBLIC_DEFAULT_PRIVILEGE_REVOKES = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC",
)

BROWSER_ROLE_REVOKE_SQL = """
DO $migration$
DECLARE
    browser_role text;
BEGIN
    FOREACH browser_role IN ARRAY ARRAY['anon', 'authenticated']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM %I',
                browser_role
            );
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM %I',
                browser_role
            );
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM %I',
                browser_role
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON TABLES FROM %I',
                browser_role
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON SEQUENCES FROM %I',
                browser_role
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE ALL PRIVILEGES ON FUNCTIONS FROM %I',
                browser_role
            );
        END IF;
    END LOOP;
END
$migration$;
"""


def upgrade() -> None:
    for statement in PUBLIC_OBJECT_REVOKES:
        op.execute(statement)
    for statement in PUBLIC_DEFAULT_PRIVILEGE_REVOKES:
        op.execute(statement)
    op.execute(BROWSER_ROLE_REVOKE_SQL)


def downgrade() -> None:
    # Privilege provenance is unknowable here.  Restoring broad access would be
    # unsafe; operators must restore only a previously documented grant set.
    pass
