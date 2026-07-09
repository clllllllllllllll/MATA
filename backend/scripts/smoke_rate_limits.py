"""Safe smoke helper for checking backend rate-limit behavior.

This is a controlled smoke script, not a load test. It defaults to localhost,
caps request counts, runs serially, stops on 429, and requires an explicit
confirmation gate before it can hit deployed/UAT URLs.

Run from the backend directory, for example:
    python scripts/smoke_rate_limits.py --target public-auth-invalid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_TARGET = "public-auth-invalid"
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_DELAY_SECONDS = 0.15
MAX_ATTEMPTS_CAP = 100
DEPLOYED_CONFIRM_ENV = "MATA_RATE_LIMIT_STRESS_CONFIRM"
DEPLOYED_CONFIRM_VALUE = "I_UNDERSTAND_THIS_HITS_UAT"
DEFAULT_ADMIN_TOKEN_ENV = "MATA_ADMIN_TOKEN"
DEFAULT_RESIDENT_TOKEN_ENV = "MATA_RESIDENT_TOKEN"
REPORTING_PERIOD_ENV = "MATA_RATE_LIMIT_REPORTING_PERIOD_ID"
INVALID_BEARER_TOKEN = "mata-rate-limit-invalid-token"

EDGE_BLOCK_STATUSES = {403}


class SafetyError(RuntimeError):
    """Raised when the requested smoke run violates a safety guard."""


@dataclass(frozen=True, slots=True)
class TargetSpec:
    name: str
    method: str
    path: str
    purpose: str
    json_payload: Mapping[str, Any] | None = None
    invalid_bearer: bool = False
    use_api_base: bool = True
    requires_include_mutating: bool = False
    requires_admin_token: bool = False
    requires_reporting_period_id: bool = False
    allow_success_status: bool = False


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt: int
    status_code: int
    retry_after: str | None
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class TargetResult:
    target: str
    method: str
    path: str
    attempts_made: int
    status_counts: dict[int, int]
    first_429_attempt: int | None
    retry_after: str | None
    verdict: str
    skipped_reason: str | None = None
    error: str | None = None


TARGETS: dict[str, TargetSpec] = {
    "public-auth-invalid": TargetSpec(
        name="public-auth-invalid",
        method="POST",
        path="/auth/login",
        purpose="Check whether invalid public resident login attempts eventually return 429.",
        json_payload={"role": "resident", "mcr": "MATA-RL-PROBE"},
    ),
    "invalid-bearer-auth-me": TargetSpec(
        name="invalid-bearer-auth-me",
        method="GET",
        path="/auth/me",
        purpose="Check whether invalid bearer requests are app-limited or edge-blocked.",
        invalid_bearer=True,
    ),
    "external-register-invalid": TargetSpec(
        name="external-register-invalid",
        method="POST",
        path="/external-residents/register",
        purpose="Safely probe public external registration with invalid payload only.",
        json_payload={
            "name": "",
            "mcr": "",
            "home_cluster": "Invalid",
            "posting_schedule": [],
        },
    ),
    "upload-inactive-period": TargetSpec(
        name="upload-inactive-period",
        method="POST",
        path="/admin/upload/rdb",
        purpose="Probe upload route with a tiny invalid file before parser work.",
        requires_include_mutating=True,
        requires_admin_token=True,
        requires_reporting_period_id=True,
    ),
    "health": TargetSpec(
        name="health",
        method="GET",
        path="/health",
        purpose="Low-count baseline response timing only; 429 is not expected.",
        use_api_base=False,
        allow_success_status=True,
    ),
}


def normalise_max_attempts(raw_value: int) -> int:
    return max(1, min(raw_value, MAX_ATTEMPTS_CAP))


def _is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def validate_deployed_guard(
    base_url: str,
    *,
    allow_deployed: bool,
    environ: Mapping[str, str],
) -> None:
    if _is_local_base_url(base_url):
        return

    if not allow_deployed:
        raise SafetyError(
            "Refusing to run against non-local base URL. Pass --allow-deployed "
            f"and set {DEPLOYED_CONFIRM_ENV}={DEPLOYED_CONFIRM_VALUE} for UAT.",
        )

    if environ.get(DEPLOYED_CONFIRM_ENV) != DEPLOYED_CONFIRM_VALUE:
        raise SafetyError(
            f"Refusing deployed run until {DEPLOYED_CONFIRM_ENV} is set exactly to "
            f"{DEPLOYED_CONFIRM_VALUE}.",
        )


def _base_origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise SafetyError(f"Invalid base URL: {base_url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def build_target_url(base_url: str, target: TargetSpec) -> str:
    if target.use_api_base:
        return f"{base_url.rstrip('/')}/{target.path.lstrip('/')}"
    return f"{_base_origin(base_url)}{target.path}"


def _target_skip_reason(
    target: TargetSpec,
    *,
    include_mutating: bool,
    admin_token: str | None,
    reporting_period_id: str | None,
) -> str | None:
    if target.requires_include_mutating and not include_mutating:
        return "requires --include-mutating"
    if target.requires_admin_token and not admin_token:
        return "requires admin token env var"
    if target.requires_reporting_period_id and not reporting_period_id:
        return f"requires --reporting-period-id or {REPORTING_PERIOD_ENV}"
    return None


def _request_kwargs(
    target: TargetSpec,
    *,
    admin_token: str | None,
    reporting_period_id: str | None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    kwargs: dict[str, Any] = {"headers": headers}

    if target.invalid_bearer:
        headers["Authorization"] = f"Bearer {INVALID_BEARER_TOKEN}"

    if target.requires_admin_token and admin_token:
        headers["Authorization"] = f"Bearer {admin_token}"

    if target.name == "upload-inactive-period":
        kwargs["data"] = {"reporting_period_id": reporting_period_id}
        kwargs["files"] = {
            "file": (
                "rate-limit-probe.txt",
                b"not an xlsx workbook",
                "text/plain",
            ),
        }
        return kwargs

    if target.json_payload is not None:
        kwargs["json"] = dict(target.json_payload)

    return kwargs


def _unexpected_status_seen(target: TargetSpec, records: Sequence[AttemptRecord]) -> bool:
    for record in records:
        status = record.status_code
        if status == 0 or status >= 500:
            return True
        if 200 <= status < 300 and not target.allow_success_status:
            return True
    return False


def summarise_attempts(
    target: TargetSpec,
    attempts: Sequence[AttemptRecord],
    *,
    skipped_reason: str | None = None,
    error: str | None = None,
) -> TargetResult:
    status_counts = dict(Counter(record.status_code for record in attempts))
    first_429 = next(
        (record.attempt for record in attempts if record.status_code == 429),
        None,
    )
    retry_after = next(
        (record.retry_after for record in attempts if record.retry_after),
        None,
    )

    if skipped_reason is not None:
        verdict = "SKIPPED"
    elif error is not None or _unexpected_status_seen(target, attempts):
        verdict = "FAILED_UNEXPECTED"
    elif first_429 is not None:
        verdict = "PASS_RATE_LIMITED"
    elif any(record.status_code in EDGE_BLOCK_STATUSES for record in attempts):
        verdict = "PASS_EDGE_BLOCKED"
    else:
        verdict = "OBSERVED_NO_429"

    return TargetResult(
        target=target.name,
        method=target.method,
        path=target.path,
        attempts_made=len(attempts),
        status_counts=status_counts,
        first_429_attempt=first_429,
        retry_after=retry_after,
        verdict=verdict,
        skipped_reason=skipped_reason,
        error=error,
    )


def _skipped_result(target: TargetSpec, reason: str) -> TargetResult:
    return summarise_attempts(target, [], skipped_reason=reason)


def run_target(
    client: httpx.Client,
    *,
    base_url: str,
    target: TargetSpec,
    max_attempts: int,
    include_mutating: bool,
    admin_token_env: str,
    reporting_period_id: str | None,
    delay_seconds: float,
    environ: Mapping[str, str],
) -> TargetResult:
    admin_token = environ.get(admin_token_env)
    resolved_reporting_period_id = reporting_period_id or environ.get(REPORTING_PERIOD_ENV)
    skip_reason = _target_skip_reason(
        target,
        include_mutating=include_mutating,
        admin_token=admin_token,
        reporting_period_id=resolved_reporting_period_id,
    )
    if skip_reason is not None:
        return _skipped_result(target, skip_reason)

    url = build_target_url(base_url, target)
    attempts: list[AttemptRecord] = []
    for attempt_number in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = client.request(
                target.method,
                url,
                **_request_kwargs(
                    target,
                    admin_token=admin_token,
                    reporting_period_id=resolved_reporting_period_id,
                ),
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            attempts.append(AttemptRecord(attempt_number, 0, None, elapsed_ms))
            return summarise_attempts(target, attempts, error=exc.__class__.__name__)

        elapsed_ms = (time.perf_counter() - started) * 1000
        retry_after = response.headers.get("Retry-After")
        attempts.append(
            AttemptRecord(
                attempt=attempt_number,
                status_code=response.status_code,
                retry_after=retry_after,
                elapsed_ms=elapsed_ms,
            ),
        )

        if response.status_code == 429 or retry_after or response.status_code in EDGE_BLOCK_STATUSES:
            break

        if attempt_number < max_attempts and delay_seconds > 0:
            time.sleep(delay_seconds)

    return summarise_attempts(target, attempts)


def _format_status_counts(status_counts: Mapping[int, int]) -> str:
    if not status_counts:
        return "-"
    return ", ".join(
        f"{status}:{count}" for status, count in sorted(status_counts.items())
    )


def render_table(results: Sequence[TargetResult]) -> str:
    headers = [
        "target",
        "method/path",
        "attempts",
        "status counts",
        "first 429",
        "retry-after",
        "verdict",
        "note",
    ]
    rows = []
    for result in results:
        rows.append(
            [
                result.target,
                f"{result.method} {result.path}",
                str(result.attempts_made),
                _format_status_counts(result.status_counts),
                str(result.first_429_attempt) if result.first_429_attempt else "-",
                result.retry_after or "-",
                result.verdict,
                result.skipped_reason or result.error or "-",
            ],
        )

    widths = [
        max(len(row[index]) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    lines = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def render_json(results: Sequence[TargetResult]) -> str:
    return json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely smoke-test selected MATA backend rate-limit behavior.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGETS),
        help=f"Target to run. May be passed multiple times. Default: {DEFAULT_TARGET}",
    )
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--allow-deployed", action="store_true")
    parser.add_argument("--include-mutating", action="store_true")
    parser.add_argument("--admin-token-env", default=DEFAULT_ADMIN_TOKEN_ENV)
    parser.add_argument("--resident-token-env", default=DEFAULT_RESIDENT_TOKEN_ENV)
    parser.add_argument("--reporting-period-id")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    max_attempts = normalise_max_attempts(args.max_attempts)
    delay_seconds = max(0.0, min(args.delay_seconds, 5.0))
    selected_targets = args.target or [DEFAULT_TARGET]

    try:
        validate_deployed_guard(
            args.base_url,
            allow_deployed=args.allow_deployed,
            environ=os.environ,
        )
    except SafetyError as exc:
        print(f"SAFETY: {exc}", file=sys.stderr)
        return 2

    results: list[TargetResult] = []
    with httpx.Client(timeout=args.timeout_seconds, follow_redirects=False) as client:
        for target_name in selected_targets:
            results.append(
                run_target(
                    client,
                    base_url=args.base_url,
                    target=TARGETS[target_name],
                    max_attempts=max_attempts,
                    include_mutating=args.include_mutating,
                    admin_token_env=args.admin_token_env,
                    reporting_period_id=args.reporting_period_id,
                    delay_seconds=delay_seconds,
                    environ=os.environ,
                ),
            )

    output = render_json(results) if args.json_output else render_table(results)
    print(output)
    return 1 if any(result.verdict == "FAILED_UNEXPECTED" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
