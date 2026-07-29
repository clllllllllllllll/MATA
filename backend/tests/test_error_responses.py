from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ApiError, ErrorCode
from app.middleware.errors import install_error_handlers


class _SecretPayload(BaseModel):
    password: int
    mcr: int


def _build_test_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api-error")
    async def api_error_route() -> None:
        raise ApiError(
            status_code=409,
            detail="Conflict happened",
            error_code=ErrorCode.CONFLICT.value,
            errors=["Duplicate resource"],
            warnings=["Retry later"],
            metadata={"scope": "ttf"},
        )

    @app.get("/http-error")
    async def http_error_route() -> None:
        raise HTTPException(status_code=403, detail="Forbidden - admin role required")

    @app.get("/http-error-dict")
    async def http_error_dict_route() -> None:
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "TTF validation failed",
                "errors": ["Row 8 invalid"],
                "warnings": ["One row skipped"],
                "metadata": {"row": 8},
            },
        )

    @app.get("/request-validation/{count}")
    async def request_validation_route(count: int) -> dict[str, int]:
        return {"count": count}

    @app.get("/unexpected")
    async def unexpected_route() -> None:
        raise RuntimeError("boom /var/private/path secret-value")

    @app.get("/database-error")
    async def database_error_route() -> None:
        raise SQLAlchemyError(
            "SELECT password FROM users; postgresql://admin:secret@db/private"
        )

    @app.post("/request-validation-body")
    async def request_validation_body_route(payload: _SecretPayload) -> dict[str, int]:
        return payload.model_dump()

    @app.get("/sensitive-api-error")
    async def sensitive_api_error_route() -> None:
        raise ApiError(
            status_code=422,
            detail="Invalid MCR=M12345A",
            errors=[
                {
                    "mcr": "M12345A",
                    "password": "do-not-return",
                    "database_url": "postgresql://admin:secret@db/private",
                }
            ],
        )

    return app


def test_api_error_returns_standard_envelope() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/api-error")
    assert response.status_code == 409
    body = response.json()
    assert body == {
        "detail": "Conflict happened",
        "error_code": "CONFLICT",
        "errors": ["Duplicate resource"],
        "warnings": ["Retry later"],
        "metadata": {"scope": "ttf"},
    }


def test_http_exception_is_normalized_to_standard_envelope() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/http-error")
    assert response.status_code == 403
    body = response.json()
    assert body["detail"] == "Forbidden - admin role required"
    assert body["error_code"] == "FORBIDDEN"
    assert body["errors"] == []
    assert body["warnings"] == []
    assert body["metadata"] == {}


def test_http_exception_with_dict_detail_preserves_structure() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/http-error-dict")
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "TTF validation failed"
    assert body["error_code"] == "VALIDATION_FAILED"
    assert body["errors"] == ["Row 8 invalid"]
    assert body["warnings"] == ["One row skipped"]
    assert body["metadata"] == {"row": 8}


def test_request_validation_error_uses_standard_envelope() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/request-validation/not-an-int")
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Validation failed"
    assert body["error_code"] == "VALIDATION_FAILED"
    assert body["errors"]
    assert "validation_errors" in body["metadata"]


def test_validation_error_never_echoes_rejected_input() -> None:
    client = TestClient(_build_test_app())
    response = client.post(
        "/request-validation-body",
        json={"password": "do-not-echo", "mcr": "M12345A"},
    )

    assert response.status_code == 422
    body_text = response.text
    assert "do-not-echo" not in body_text
    assert "M12345A" not in body_text
    for item in response.json()["metadata"]["validation_errors"]:
        assert set(item) == {"loc", "type", "msg"}
        assert item["msg"] == "Invalid value"


def test_api_errors_are_recursively_redacted() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/sensitive-api-error")

    assert response.status_code == 422
    response_text = response.text
    assert "M12345A" not in response_text
    assert "do-not-return" not in response_text
    assert "admin:secret" not in response_text
    assert "[REDACTED]" in response_text


def test_unexpected_exception_returns_safe_generic_500(caplog) -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="app.middleware.errors"):
        response = client.get("/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "secret-value" not in str(body)
    assert "/var/private/path" not in str(body)
    correlation_id = body["metadata"]["correlation_id"]
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert correlation_id in caplog.text
    assert "category=unhandled" in caplog.text
    assert "exception_class=RuntimeError" in caplog.text
    assert "secret-value" not in caplog.text
    assert "/var/private/path" not in caplog.text
    assert "Traceback" not in caplog.text


def test_database_exception_does_not_log_sql_or_connection_details(caplog) -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="app.middleware.errors"):
        response = client.get("/database-error")

    assert response.status_code == 500
    assert "SELECT password" not in response.text
    assert "admin:secret" not in response.text
    assert "SELECT password" not in caplog.text
    assert "admin:secret" not in caplog.text
    assert "category=database" in caplog.text
    assert "exception_class=SQLAlchemyError" in caplog.text
