from __future__ import annotations

from typing import Any

from app.schemas.data_revalidation import (
    DataRevalidationChangedEntity,
    DataRevalidationContext,
    DataRevalidationImpactSummary,
    DataRevalidationOutcome,
)


_AFFECTED_MODEL_BY_ENTITY = {
    DataRevalidationChangedEntity.RESIDENT: "residents",
    DataRevalidationChangedEntity.RESIDENT_POSTING: "resident_postings",
    DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT: "resident_postings",
    DataRevalidationChangedEntity.TEACHING_TARGET: "teaching_targets",
    DataRevalidationChangedEntity.FORM_F1_RECORD: "form_f1_records",
    DataRevalidationChangedEntity.ACADEMIC_MONTH_BOUNDARY: "academic_month_boundaries",
    DataRevalidationChangedEntity.REPORTING_PERIOD: "reporting_periods",
    DataRevalidationChangedEntity.PUBLIC_HOLIDAY: "public_holidays",
    DataRevalidationChangedEntity.PROGRAMME: "programmes",
    DataRevalidationChangedEntity.LOA_TYPE: "loa_types",
    DataRevalidationChangedEntity.MULTI_POSTING_RULE: "multi_posting_rules",
    DataRevalidationChangedEntity.POSTING_GROUP: "posting_groups",
    DataRevalidationChangedEntity.WEEKEND_EXCEPTION: "weekend_exceptions",
    DataRevalidationChangedEntity.GLOBAL_SESSION_TYPE: "global_session_types",
}


def _affected_models_for(context: DataRevalidationContext) -> list[str]:
    model_name = _AFFECTED_MODEL_BY_ENTITY.get(context.changed_entity)
    return [model_name] if model_name else []


def _warning_delta(summary: DataRevalidationImpactSummary) -> dict[str, int]:
    return {
        "created": summary.warnings_created,
        "updated": summary.warnings_updated,
        "resolved": summary.warnings_resolved,
        "remaining": summary.warnings_remaining,
    }


def _audit_metadata(
    context: DataRevalidationContext,
    summary: DataRevalidationImpactSummary,
) -> dict[str, Any]:
    return {
        "triggered_by": context.trigger_source.value,
        "trigger_entity": context.changed_entity.value,
        "trigger_entity_id": context.entity_id,
        "impact_summary": {
            "outcome": summary.outcome.value,
            "scope": summary.scope.value,
            "rows_examined": summary.rows_examined,
            "rows_updated": summary.rows_updated,
            "affected_models": list(summary.affected_models),
        },
        "warnings_delta": _warning_delta(summary),
    }


def _summary(
    *,
    context: DataRevalidationContext,
    outcome: DataRevalidationOutcome,
    message: str,
    affected_models: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> DataRevalidationImpactSummary:
    base_details: dict[str, Any] = {
        "handler_version": "3H-B",
        "business_tables_mutated": False,
        "warnings_mutated": False,
        "changed_fields": list(context.changed_fields),
    }
    if context.source_metadata:
        base_details["source_metadata"] = dict(context.source_metadata)
    base_details.update(details or {})
    payload = DataRevalidationImpactSummary(
        outcome=outcome,
        trigger_source=context.trigger_source,
        changed_entity=context.changed_entity,
        action=context.action,
        scope=context.scope,
        summary=message,
        affected_models=affected_models if affected_models is not None else _affected_models_for(context),
        details=base_details,
    )
    payload.audit_metadata = _audit_metadata(context, payload)
    return payload


def _manual_required_summary(
    *,
    context: DataRevalidationContext,
    message: str,
    details: dict[str, Any] | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.MANUAL_REVALIDATION_REQUIRED,
        message=message,
        details={"backend_handler_available": False, **(details or {})},
    )


async def revalidate_after_upload(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.TARGETED_REVALIDATION,
        message=(
            "Data Revalidation recorded that upload-time parsing already handled "
            "derived data for this scope; no additional 3H-B mutations were run."
        ),
        details={"backend_handler_available": True},
    )


async def revalidate_after_live_data_correction(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    if context.changed_entity == DataRevalidationChangedEntity.UNKNOWN:
        return _summary(
            context=context,
            outcome=DataRevalidationOutcome.NO_OP,
            message="No Data Revalidation handler is selected for this unknown Live Data correction.",
            affected_models=[],
            details={"backend_handler_available": False},
        )

    if context.changed_entity == DataRevalidationChangedEntity.RESIDENT_POSTING_SOURCE_FRAGMENT:
        return await preview_resident_posting_source_cell_revalidation(
            context=context,
            db_session=db_session,
        )

    affected_models: list[str] | None = None
    details: dict[str, Any] = {"backend_handler_available": True}
    if (
        context.changed_entity == DataRevalidationChangedEntity.TEACHING_TARGET
        and "details_of_training" in context.changed_fields
    ):
        affected_models = ["teaching_targets", "teaching_name_catalogue"]
        details["catalogue_regenerated"] = True

    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
        message=(
            "Live Data correction may affect future compliance reads. "
            "No heavy Data Revalidation handler is implemented."
        ),
        affected_models=affected_models,
        details=details,
    )


async def revalidate_after_config_change(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    if context.changed_entity == DataRevalidationChangedEntity.UNKNOWN:
        return _summary(
            context=context,
            outcome=DataRevalidationOutcome.NO_OP,
            message="No Data Revalidation handler is selected for this unknown config change.",
            affected_models=[],
            details={"backend_handler_available": False},
        )

    if context.changed_entity == DataRevalidationChangedEntity.MULTI_POSTING_RULE:
        return _manual_required_summary(
            context=context,
            message=(
                "The targeted config Data Revalidation handler is not implemented yet. "
                "A later phase will revalidate affected multi-posting warnings and source cells."
            ),
        )

    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.FUTURE_COMPLIANCE_IMPACT,
        message=(
            "Config change may affect future compliance reads. "
            "No heavy Data Revalidation handler is implemented in 3H-B."
        ),
        details={"backend_handler_available": True},
    )


async def revalidate_warning_scope(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    return _summary(
        context=context,
        outcome=DataRevalidationOutcome.WARNING_ONLY,
        message=(
            "Data Revalidation warning refresh hook is not implemented yet; "
            "3H-B records warning-only impact without mutating warnings."
        ),
        details={"backend_handler_available": False},
    )


async def preview_resident_posting_source_cell_revalidation(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    details = {
        key: context.source_metadata[key]
        for key in ("affected_row_count", "replacement_row_count")
        if key in context.source_metadata
    }
    return _manual_required_summary(
        context=context,
        message=(
            "The backend source-cell Data Revalidation handler is not implemented yet. "
            "A later phase will parse corrected RDB source-cell text and refresh affected warnings."
        ),
        details=details,
    )


async def apply_resident_posting_source_cell_revalidation(
    *,
    context: DataRevalidationContext,
    db_session: Any | None = None,
) -> DataRevalidationImpactSummary:
    return _manual_required_summary(
        context=context,
        message=(
            "The backend source-cell Data Revalidation handler is not implemented yet. "
            "3H-B does not apply RDB source-cell parsing or resident_postings regeneration."
        ),
    )
