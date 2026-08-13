"""Names permitted for independently runnable local PostgreSQL tests."""

from __future__ import annotations

import os


DEFAULT_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_e2b2_verify"
PHASE_R_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_r_verify"
PHASE_K_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_k_verify"
PHASE_L_DISPOSABLE_DATABASE_NAME = "mata_evolved_ttf_l_verify"
ALLOWED_DISPOSABLE_DATABASE_NAMES = frozenset(
    {
        DEFAULT_DISPOSABLE_DATABASE_NAME,
        PHASE_R_DISPOSABLE_DATABASE_NAME,
        PHASE_K_DISPOSABLE_DATABASE_NAME,
        PHASE_L_DISPOSABLE_DATABASE_NAME,
    }
)


def configured_disposable_database_name(
    *,
    default: str = DEFAULT_DISPOSABLE_DATABASE_NAME,
) -> str:
    """Return an explicit local test target, rejecting arbitrary overrides."""

    database_name = os.environ.get("MATA_RLS_DISPOSABLE_DATABASE_NAME", default)
    if database_name not in ALLOWED_DISPOSABLE_DATABASE_NAMES:
        raise ValueError("MATA_RLS_DISPOSABLE_DATABASE_NAME is not an allowed target")
    return database_name
