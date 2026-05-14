from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.errors import ApiError, ErrorCode
from app.middleware.errors import install_error_handlers


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


def test_unexpected_exception_returns_safe_generic_500() -> None:
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.get("/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "secret-value" not in str(body)
    assert "/var/private/path" not in str(body)
