from __future__ import annotations

from uuid import uuid4

import pytest

from app.schemas.data_revalidation import (
    CANONICAL_DATA_REVALIDATION_OUTCOMES,
    DataRevalidationAction,
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationOutcome,
    DataRevalidationScope,
    DataRevalidationTriggerSource,
)
from app.services import data_revalidation_service


class MutationGuardSession:
    async def execute(self, *args, **kwargs):  # pragma: no cover - should never be reached
        raise AssertionError("default Data Revalidation handlers must not execute SQL")

    async def commit(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("default Data Revalidation handlers must not commit")

    async def rollback(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("default Data Revalidation handlers must not rollback")


class _MappingResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_MappingResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)

    def one_or_none(self) -> dict | None:
        if len(self._rows) > 1:
            raise AssertionError("Expected at most one row")
        return self._rows[0] if self._rows else None


class EmptyConfigImpactSession:
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "/* data_revalidation:warning_candidates */" in sql:
            return _MappingResult([])
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("Data Revalidation handlers must not commit")

    async def rollback(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("Data Revalidation handlers must not rollback")


class BulkConfigImpactSession:
    def __init__(self, *, warning_count: int) -> None:
        self.warning_issues = [
            {
                "id": str(uuid4()),
                "fingerprint": f"programme|GERI|{index}",
                "warning_type": "unmatched_multi_posting",
                "status": "reappeared" if index % 2 else "unresolved",
                "severity": "warning",
                "reporting_period_id": str(uuid4()),
                "programme_code": "GERI",
                "mcr": f"M{index:05d}A",
                "month_label": "May-26",
                "last_seen_at": None,
                "latest_upload_warning_id": str(uuid4()),
                "source_payload": {"posting_codes": ["A", "B"]},
                "message": "No matching multi-posting rule found",
                "suggested_action": None,
            }
            for index in range(warning_count)
        ]

    async def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        if "/* data_revalidation:warning_candidates */" in sql:
            statuses = set(payload.get("statuses") or [])
            warning_types = set(payload.get("warning_types") or [])
            rows = [
                row
                for row in self.warning_issues
                if row["status"] in statuses
                and row["warning_type"] in warning_types
                and row["programme_code"] == payload.get("programme_code")
            ]
            return _MappingResult(rows[: payload.get("limit", len(rows))])
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("Data Revalidation handlers must not commit")

    async def rollback(self) -> None:  # pragma: no cover - should never be reached
        raise AssertionError("Data Revalidation handlers must not rollback")


def _context(**overrides) -> DataRevalidationContext:
    payload = {
        "trigger_source": DataRevalidationTriggerSource.LIVE_DATA_CORRECTION,
        "changed_entity": DataRevalidationChangedEntity.RESIDENT,
        "action": DataRevalidationAction.UPDATE,
        "scope": DataRevalidationScope.SINGLE_ROW,
        "entity_id": str(uuid4()),
        "programme_code": "GERI",
        "resident_id": str(uuid4()),
        "reporting_period_id": str(uuid4()),
        "upload_log_id": None,
        "changed_fields": ["programme_code"],
        "source_metadata": {"source_page": "parsed_data"},
        "actor_user_id": str(uuid4()),
        "actor_role": "admin",
        "reason": "Correct Live Data row",
    }
    payload.update(overrides)
    return DataRevalidationContext.model_validate(payload)


def test_canonical_outcome_enum_values_are_exact() -> None:
    assert CANONICAL_DATA_REVALIDATION_OUTCOMES == (
        "no_op",
        "warning_only",
        "targeted_revalidation",
        "future_compliance_impact",
        "manual_revalidation_required",
    )
    assert tuple(item.value for item in DataRevalidationOutcome) == CANONICAL_DATA_REVALIDATION_OUTCOMES


@pytest.mark.asyncio
async def test_live_data_correction_returns_stable_future_impact_summary_shape() -> None:
    context = _context()

    summary = await data_revalidation_service.revalidate_after_live_data_correction(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT
    assert summary.trigger_source == DataRevalidationTriggerSource.LIVE_DATA_CORRECTION
    assert summary.changed_entity == DataRevalidationChangedEntity.RESIDENT
    assert summary.action == DataRevalidationAction.UPDATE
    assert summary.scope == DataRevalidationScope.SINGLE_ROW
    assert summary.rows_examined == 0
    assert summary.rows_updated == 0
    assert summary.warnings_created == 0
    assert summary.warnings_updated == 0
    assert summary.warnings_resolved == 0
    assert summary.warnings_remaining == 0
    assert summary.affected_models == ["residents"]
    assert summary.affected_warning_ids == []
    assert summary.audit_metadata["triggered_by"] == "live_data_correction"
    assert summary.audit_metadata["trigger_entity"] == "resident"
    assert summary.audit_metadata["warnings_delta"] == {
        "created": 0,
        "updated": 0,
        "resolved": 0,
        "remaining": 0,
    }
    assert summary.details["handler_version"] == "3H-B"


@pytest.mark.asyncio
async def test_config_change_returns_future_impact_for_default_config_entities() -> None:
    context = _context(
        trigger_source=DataRevalidationTriggerSource.ADMIN_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.POSTING_GROUP,
        action=DataRevalidationAction.CREATE,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        changed_fields=["group_code", "posting_code"],
        source_metadata={"source_page": "admin_config"},
    )

    summary = await data_revalidation_service.revalidate_after_config_change(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT
    assert summary.trigger_source == DataRevalidationTriggerSource.ADMIN_CONFIG_CHANGE
    assert summary.changed_entity == DataRevalidationChangedEntity.POSTING_GROUP
    assert summary.affected_models == ["posting_groups"]
    assert summary.warnings_created == 0
    assert summary.warnings_updated == 0
    assert summary.warnings_resolved == 0
    assert "future compliance reads" in summary.summary


@pytest.mark.asyncio
async def test_source_fragment_preview_returns_warning_only_non_mutating_summary() -> None:
    context = _context(
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT,
        action=DataRevalidationAction.REPLACE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
        changed_fields=["source_cell_text"],
    )

    summary = await data_revalidation_service.preview_resident_posting_source_cell_revalidation(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.WARNING_ONLY
    assert summary.changed_entity == DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT
    assert summary.details["backend_handler_available"] is True
    assert summary.details["business_tables_mutated"] is False
    assert "without mutating resident_postings" in summary.summary
    assert summary.rows_examined == 0
    assert summary.rows_updated == 0


@pytest.mark.asyncio
async def test_multi_posting_rule_config_trigger_returns_manual_required_summary() -> None:
    context = _context(
        trigger_source=DataRevalidationTriggerSource.PC_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.MULTI_POSTING_RULE,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.UNRESOLVED_WARNINGS,
        changed_fields=["posting_code_1", "main_posting_code"],
    )

    summary = await data_revalidation_service.revalidate_after_config_change(
        context=context,
        db_session=EmptyConfigImpactSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.MANUAL_REVALIDATION_REQUIRED
    assert summary.trigger_source == DataRevalidationTriggerSource.PC_CONFIG_CHANGE
    assert summary.changed_entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE
    assert summary.details["backend_handler_available"] is True
    assert summary.details["concrete_revalidation_handler_available"] is False
    assert summary.details["affected_warning_count"] == 0
    assert summary.details["warning_candidate_limit"] == data_revalidation_service._WARNING_QUERY_LIMIT
    assert summary.details["warning_candidate_limit_reached"] is False
    assert summary.details["affected_warning_count_is_partial"] is False
    assert summary.details["affected_warning_details_are_partial"] is False
    assert "No source cells were reparsed" in summary.summary
    assert summary.warnings_created == 0
    assert summary.warnings_updated == 0
    assert summary.warnings_resolved == 0


@pytest.mark.asyncio
async def test_config_change_marks_warning_details_partial_when_candidate_cap_is_reached() -> None:
    warning_limit = data_revalidation_service._WARNING_QUERY_LIMIT
    session = BulkConfigImpactSession(warning_count=warning_limit + 5)
    original_statuses = [row["status"] for row in session.warning_issues]
    context = _context(
        trigger_source=DataRevalidationTriggerSource.ADMIN_CONFIG_CHANGE,
        changed_entity=DataRevalidationChangedEntity.PROGRAMME,
        action=DataRevalidationAction.UPDATE,
        scope=DataRevalidationScope.PROGRAMME_REPORTING_PERIOD,
        programme_code="GERI",
        changed_fields=["rdb_alias"],
    )

    summary = await data_revalidation_service.revalidate_after_config_change(
        context=context,
        db_session=session,
    )

    assert summary.details["affected_warning_count"] == warning_limit
    assert summary.details["affected_warning_count_is_partial"] is True
    assert summary.details["affected_warning_details_are_partial"] is True
    assert summary.details["warning_candidate_limit"] == warning_limit
    assert summary.details["warning_candidate_limit_reached"] is True
    assert summary.affected_warning_count == warning_limit
    assert summary.affected_warning_count_is_partial is True
    assert summary.affected_warning_details_are_partial is True
    assert summary.warning_candidate_limit == warning_limit
    assert summary.warning_candidate_limit_reached is True
    assert len(summary.affected_warning_issue_ids) <= 20
    assert len(summary.affected_warning_summaries) <= 10
    assert len(summary.details["affected_warning_issue_ids"]) <= 20
    assert len(summary.details["affected_warning_summaries"]) <= 10
    assert [row["status"] for row in session.warning_issues] == original_statuses


@pytest.mark.asyncio
async def test_warning_scope_default_is_warning_only_without_mutation() -> None:
    context = _context(
        trigger_source=DataRevalidationTriggerSource.MANUAL_REVALIDATION,
        changed_entity=DataRevalidationChangedEntity.UNKNOWN,
        action=DataRevalidationAction.MANUAL,
        scope=DataRevalidationScope.UNRESOLVED_WARNINGS,
        changed_fields=[],
    )

    summary = await data_revalidation_service.revalidate_warning_scope(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.WARNING_ONLY
    assert summary.scope == DataRevalidationScope.UNRESOLVED_WARNINGS
    assert summary.warnings_created == 0
    assert summary.warnings_updated == 0
    assert summary.warnings_resolved == 0
    assert "warning refresh hook is not implemented yet" in summary.summary


@pytest.mark.asyncio
async def test_upload_trigger_returns_targeted_placeholder_summary() -> None:
    context = _context(
        trigger_source=DataRevalidationTriggerSource.UPLOAD,
        changed_entity=DataRevalidationChangedEntity.UNKNOWN,
        action=DataRevalidationAction.UPLOAD,
        scope=DataRevalidationScope.UPLOAD_LOG,
        entity_id=None,
        upload_log_id=str(uuid4()),
        changed_fields=[],
    )

    summary = await data_revalidation_service.revalidate_after_upload(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.TARGETED_REVALIDATION
    assert summary.trigger_source == DataRevalidationTriggerSource.UPLOAD
    assert summary.scope == DataRevalidationScope.UPLOAD_LOG
    assert summary.details["business_tables_mutated"] is False
    assert "upload-time parsing already handled" in summary.summary


@pytest.mark.asyncio
async def test_unknown_live_data_entity_can_return_no_op() -> None:
    context = _context(
        changed_entity=DataRevalidationChangedEntity.UNKNOWN,
        action=DataRevalidationAction.UNKNOWN,
        scope=DataRevalidationScope.UNKNOWN,
        changed_fields=[],
    )

    summary = await data_revalidation_service.revalidate_after_live_data_correction(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.NO_OP
    assert summary.affected_models == []
    assert summary.details["backend_handler_available"] is False


@pytest.mark.asyncio
async def test_apply_source_cell_revalidation_returns_targeted_summary() -> None:
    context = _context(
        changed_entity=DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT,
        action=DataRevalidationAction.REPLACE,
        scope=DataRevalidationScope.RESIDENT_MONTH,
    )

    summary = await data_revalidation_service.apply_resident_posting_source_cell_revalidation(
        context=context,
        db_session=MutationGuardSession(),
    )

    assert summary.outcome == DataRevalidationOutcome.TARGETED_REVALIDATION
    assert summary.affected_models == ["resident_postings"]
    assert summary.details["business_tables_mutated"] is True
    assert summary.details["backend_handler_available"] is True
    assert "No compliance calculation" in summary.summary
