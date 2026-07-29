# Phase 5B Security Archive

These files are historical Phase 5B implementation, security, migration, UAT,
runbook, fix-log, and verification records.

The current security source of truth is
[`docs/security.md`](../../../security.md). The current architectural decision,
trade-off, unresolved-gap, and superseded-decision history remains
[`docs/99_decision_log_and_gap_audit.md`](../../../99_decision_log_and_gap_audit.md).
Current architecture and API behavior live in the other top-level domain
contracts:

- [`docs/schema.md`](../../../schema.md)
- [`docs/api.md`](../../../api.md)
- [`docs/business-logic.md`](../../../business-logic.md)
- [`docs/parsing.md`](../../../parsing.md)
- [`docs/auth-account-contract.md`](../../../auth-account-contract.md)

The archived records preserve point-in-time context, commands, test evidence,
deployment observations, blocked outcomes, and implementation reasoning. They
do not override current canonical contracts, and their historical verdicts
must not be rewritten to imply later local or deployed results.

## Supabase and PostgreSQL readiness

- [Supabase production readiness audit](5b_g_supabase_readiness_audit.md)
- [Service-role and privileged backend access review](5b_g_service_role_access_review.md)

## RLS, roles, and grants

- [RLS, grants, and Data API readiness matrix](5b_g_rls_grants_matrix.md)
- [Full PostgreSQL RLS implementation](5b_h_e_full_rls_implementation.md)

## Runbooks and migration smoke plans

- [Staff bootstrap runbook](5b_g_staff_bootstrap_runbook.md)
- [Supabase migration smoke plan](5b_g_supabase_migration_smoke_plan.md)

These two runbooks retain historical Phase 5B detail. Current bootstrap,
migration, rollback, and recovery requirements are defined by the account and
security contracts linked above.

## Session and transport hardening

- [Session transport hardening plan](5b_h_session_transport_hardening_plan.md)
- [Production security implementation](5b_h_d_production_security_implementation.md)

## Session lifecycle and reliable logout

- [Session lifecycle assurance](5b_h_session_lifecycle_assurance.md)
- [Reliable logout](5b_h_m06_reliable_logout.md)

## Combined audit, atomic attendance, and request limits

- [Combined security integration audit](5b_h_def_security_integration_audit.md)
- [Atomic attendance and ad-hoc ownership](5b_h_aud_m04_atomic_attendance.md)
- [Pre-parser request-body limits](5b_h_m05_upload_preparser_limits.md)
- [Local security fixes](5b_i_local_security_fixes.md)

## UAT and deployment evidence

- [Vercel UAT security plan](5b_h_vercel_uat_security_plan.md)
- [UAT security audit](5b_h_uat_security_audit.md)
- [UAT security fix log](5b_h_uat_security_fix_log.md)
- [Supabase/Vercel UAT smoke checklist](5b_h_vercel_supabase_uat_smoke.md)
- [Deployment security and functional UAT audit](5b_h_c_deployment_security_audit.md)
- [Live Vercel and Supabase evidence](uat-evidence/5b-h-c-live-mcp-evidence-2026-07-22.md)
