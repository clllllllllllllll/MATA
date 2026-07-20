from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.models import ProgrammeInstitutionPostingMap
from app.services.programme_institution_posting import normalise_mapping_code
from tests.resident_fakes import PROGRAMME_SEED_ROWS, FakeResidentSession


def test_mapping_model_has_required_columns_constraints_and_indexes() -> None:
    table = ProgrammeInstitutionPostingMap.__table__

    assert {
        "id",
        "programme_code",
        "institution_code",
        "posting_code",
        "status",
        "display_order",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())
    assert table.c.posting_code.nullable is True
    assert table.c.display_order.server_default is not None
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    } >= {
        "uq_programme_institution_posting_map_scope",
        "ck_programme_institution_posting_map_status",
        "ck_programme_institution_posting_map_active_posting",
    }
    assert {
        index.name
        for index in table.indexes
        if isinstance(index, Index)
    } == {
        "idx_programme_institution_posting_map_institution_status",
        "idx_programme_institution_posting_map_programme_status",
        "idx_programme_institution_posting_map_posting",
    }


def test_fake_seed_matches_infrastructure_migration_contract() -> None:
    rows = FakeResidentSession().programme_institution_posting_map

    assert len(rows) == 28
    assert [row["programme_code"] for row in rows] == [
        code for code, _name in PROGRAMME_SEED_ROWS
    ]
    assert [row["display_order"] for row in rows] == list(range(28))
    assert {row["institution_code"] for row in rows} == {"TTSH"}
    assert {row["status"] for row in rows} == {"pending"}
    assert all(row["posting_code"] is None for row in rows)
    geri = next(row for row in rows if row["programme_code"] == "GERI")
    assert geri["status"] == "pending"
    assert geri["posting_code"] is None


def test_mapping_code_normalisation_is_institution_agnostic() -> None:
    assert normalise_mapping_code("  ktph  ", field_name="institution_code") == "KTPH"
    assert normalise_mapping_code(" geri ", field_name="programme_code") == "GERI"
