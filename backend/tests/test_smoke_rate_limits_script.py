from __future__ import annotations

import os

import pytest

from scripts import smoke_rate_limits as smoke


def test_deployed_guard_refuses_non_local_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(smoke.DEPLOYED_CONFIRM_ENV, raising=False)

    with pytest.raises(smoke.SafetyError, match="Refusing to run against non-local base URL"):
        smoke.validate_deployed_guard(
            "https://mata-backend.vercel.app/api/v1",
            allow_deployed=False,
            environ=os.environ,
        )


def test_deployed_guard_allows_non_local_only_with_flag_and_exact_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(smoke.DEPLOYED_CONFIRM_ENV, "wrong")

    with pytest.raises(smoke.SafetyError, match=smoke.DEPLOYED_CONFIRM_ENV):
        smoke.validate_deployed_guard(
            "https://mata-backend.vercel.app/api/v1",
            allow_deployed=True,
            environ=os.environ,
        )

    monkeypatch.setenv(smoke.DEPLOYED_CONFIRM_ENV, smoke.DEPLOYED_CONFIRM_VALUE)

    smoke.validate_deployed_guard(
        "https://mata-backend.vercel.app/api/v1",
        allow_deployed=True,
        environ=os.environ,
    )


def test_local_base_url_does_not_require_deployed_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(smoke.DEPLOYED_CONFIRM_ENV, raising=False)

    smoke.validate_deployed_guard(
        "http://localhost:8000/api/v1",
        allow_deployed=False,
        environ=os.environ,
    )
    smoke.validate_deployed_guard(
        "http://127.0.0.1:8000/api/v1",
        allow_deployed=False,
        environ=os.environ,
    )


def test_max_attempts_is_capped() -> None:
    assert smoke.normalise_max_attempts(0) == 1
    assert smoke.normalise_max_attempts(8) == 8
    assert smoke.normalise_max_attempts(101) == smoke.MAX_ATTEMPTS_CAP


def test_summary_classification_for_common_status_sequences() -> None:
    target = smoke.TARGETS["public-auth-invalid"]

    repeated_401 = smoke.summarise_attempts(
        target,
        [
            smoke.AttemptRecord(1, 401, None, 10.0),
            smoke.AttemptRecord(2, 401, None, 12.0),
        ],
    )
    assert repeated_401.verdict == "OBSERVED_NO_429"
    assert repeated_401.status_counts == {401: 2}

    rate_limited = smoke.summarise_attempts(
        target,
        [
            smoke.AttemptRecord(1, 401, None, 10.0),
            smoke.AttemptRecord(2, 429, "57", 12.0),
        ],
    )
    assert rate_limited.verdict == "PASS_RATE_LIMITED"
    assert rate_limited.first_429_attempt == 2
    assert rate_limited.retry_after == "57"

    edge_blocked = smoke.summarise_attempts(
        target,
        [smoke.AttemptRecord(1, 403, None, 10.0)],
    )
    assert edge_blocked.verdict == "PASS_EDGE_BLOCKED"

    validation_only = smoke.summarise_attempts(
        target,
        [
            smoke.AttemptRecord(1, 422, None, 10.0),
            smoke.AttemptRecord(2, 400, None, 12.0),
        ],
    )
    assert validation_only.verdict == "OBSERVED_NO_429"


def test_token_values_are_not_rendered_in_output() -> None:
    target = smoke.TARGETS["invalid-bearer-auth-me"]
    secret_token = "super-secret-token-value"
    result = smoke.summarise_attempts(
        target,
        [smoke.AttemptRecord(1, 401, None, 10.0)],
    )

    text_output = smoke.render_table([result])
    json_output = smoke.render_json([result])

    assert secret_token not in text_output
    assert secret_token not in json_output
    assert "Authorization" not in text_output
    assert "Authorization" not in json_output
