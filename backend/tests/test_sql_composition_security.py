from __future__ import annotations

import ast
import inspect
from uuid import uuid4

import pytest

from app.services import admin_config, parsed_data, upload_logs


ATTACK_TEXT = "GRM' OR 1=1; DROP TABLE users --"


class _NeverExecuteSession:
    async def execute(self, statement, params=None):  # noqa: ANN001
        raise AssertionError(f"unsafe update reached database execution: {statement} {params}")


def test_scope_and_filter_values_remain_bound_parameters() -> None:
    admin_params: dict[str, object] = {}
    admin_clause = admin_config._scope_or_clause(
        field_name="r.programme_code",
        values=[ATTACK_TEXT],
        params=admin_params,
        param_prefix="programme_code",
    )
    assert ATTACK_TEXT not in admin_clause
    assert admin_params == {"programme_code_0": ATTACK_TEXT}

    parsed_params: dict[str, object] = {}
    parsed_clause = parsed_data._scope_or_clause(
        column_sql="r.programme_code",
        values=[ATTACK_TEXT],
        params=parsed_params,
    )
    assert ATTACK_TEXT not in parsed_clause
    assert parsed_params == {"scope_programme_code_0": ATTACK_TEXT}

    where_clauses, upload_params = upload_logs._build_filters(
        programme_scope=set(),
        master_admin=True,
        upload_type=ATTACK_TEXT,
        status=ATTACK_TEXT,
        programme_code=ATTACK_TEXT,
        reporting_period_id=None,
        search=ATTACK_TEXT,
    )
    assert all(ATTACK_TEXT not in clause for clause in where_clauses)
    assert upload_params["upload_type"] == ATTACK_TEXT
    assert upload_params["status"] == ATTACK_TEXT
    assert upload_params["programme_code"] == ATTACK_TEXT
    assert upload_params["search"] == f"%{ATTACK_TEXT.lower()}%"


def test_dynamic_sql_helpers_reject_untrusted_structure() -> None:
    with pytest.raises(ValueError, match="scope field"):
        admin_config._scope_or_clause(
            field_name="programme_code; DROP TABLE users",
            values=["GRM"],
            params={},
            param_prefix="programme_code",
        )
    with pytest.raises(ValueError, match="parameter prefix"):
        admin_config._scope_or_clause(
            field_name="programme_code",
            values=["GRM"],
            params={},
            param_prefix="programme_code) OR 1=1 --",
        )
    with pytest.raises(ValueError, match="scope column"):
        parsed_data._scope_or_clause(
            column_sql="programme_code; DROP TABLE users",
            values=["GRM"],
            params={},
        )
    with pytest.raises(ValueError, match="search column"):
        parsed_data._add_search_filter(
            [],
            {},
            search="GRM",
            columns_sql=["name) FROM users; DROP TABLE users --"],
        )
    with pytest.raises(ValueError, match="partial-text filter"):
        parsed_data._add_partial_text_filter(
            [],
            {},
            key="mcr",
            column_sql="mcr) OR 1=1 --",
            value="M12345A",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table_name", "changed"),
    [
        ("residents; DROP TABLE users", {"name": "Resident"}),
        ("residents", {"name = NULL; DROP TABLE users --": "Resident"}),
        ("residents", {}),
    ],
)
async def test_update_sink_rejects_untrusted_table_or_fields(
    table_name: str,
    changed: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="update specification"):
        await parsed_data._apply_update(
            _NeverExecuteSession(),
            table_name=table_name,
            row_id=uuid4(),
            changed=changed,
        )


def test_page_and_update_structural_arguments_remain_source_literals() -> None:
    tree = ast.parse(inspect.getsource(parsed_data))
    page_call_count = 0
    update_call_count = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        if node.func.id == "_page":
            page_call_count += 1
            for argument in ("select_sql", "from_sql", "order_sql"):
                assert isinstance(keywords.get(argument), ast.Constant)
                assert isinstance(keywords[argument].value, str)
        elif node.func.id == "_apply_update":
            update_call_count += 1
            table_name = keywords.get("table_name")
            assert isinstance(table_name, ast.Constant)
            assert table_name.value in parsed_data._UPDATE_ALLOWED_FIELDS_BY_TABLE

    assert page_call_count == 7
    assert update_call_count == len(parsed_data._UPDATE_ALLOWED_FIELDS_BY_TABLE)
