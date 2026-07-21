from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.auth_stub import AuthIdentity, AuthStubMiddleware
from app.middleware.errors import install_error_handlers
from app.routers import external_residents
from tests.resident_fakes import (
    TTSH_ACTIVE_REGISTRATION_MAPPINGS,
    TTSH_INACTIVE_REGISTRATION_PROGRAMMES,
    FakeResidentSession,
)


MAPPING_PENDING_DETAIL = "Posting configuration for this programme is pending."
MAPPING_INACTIVE_DETAIL = "Posting configuration for this programme is unavailable."
MAPPING_MISSING_DETAIL = (
    "No posting configuration is available for this programme and institution."
)


def _client(
    fake_db: FakeResidentSession,
    identity: AuthIdentity | None = None,
) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.middleware("http")
    async def inject_identity(request, call_next):
        if identity is not None:
            request.state.identity = identity
        return await call_next(request)

    async def _db_override():
        yield fake_db

    async def _rate_limit_override() -> None:
        return None

    app.dependency_overrides[external_residents.get_db_session] = _db_override
    app.dependency_overrides[
        external_residents._persistent_registration_rate_limit
    ] = _rate_limit_override
    app.include_router(external_residents.router)
    return TestClient(app)


def _middleware_client(fake_db: FakeResidentSession) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(
        AuthStubMiddleware,
        settings=Settings(auth_mode="stub", _env_file=None),
    )

    async def _db_override():
        yield fake_db

    async def _rate_limit_override() -> None:
        return None

    app.dependency_overrides[external_residents.get_db_session] = _db_override
    app.dependency_overrides[
        external_residents._persistent_registration_rate_limit
    ] = _rate_limit_override
    app.include_router(external_residents.router)
    return TestClient(app)


def _configure_mapping(
    fake_db: FakeResidentSession,
    *,
    programme_code: str = "GERI",
    institution_code: str = "TTSH",
    posting_code: str | None = "TTSHGerMed",
    status: str = "active",
) -> None:
    mapping = next(
        (
            row
            for row in fake_db.programme_institution_posting_map
            if row["programme_code"] == programme_code
            and row["institution_code"] == institution_code
        ),
        None,
    )
    if mapping is None:
        fake_db.programme_institution_posting_map.append(
            {
                "programme_code": programme_code,
                "institution_code": institution_code,
                "posting_code": posting_code,
                "status": status,
                "display_order": len(fake_db.programme_institution_posting_map),
            }
        )
        return
    mapping.update(posting_code=posting_code, status=status)


def _registration_schedule(
    *,
    programme_code: str = "GERI",
    institution: str = "TTSH",
) -> list[dict[str, str]]:
    return [
        {
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "programme_code": programme_code,
            "institution": institution,
        }
    ]


def test_external_registration_succeeds_for_nuh() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "NUH Resident",
            "mcr": "E11111A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["home_cluster"] == "NUH"
    assert payload["resident"]["mcr"] == "E11111A"


def test_external_registration_succeeds_for_singhealth() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "SH Resident",
            "mcr": "E22222B",
            "home_cluster": "SingHealth",
            "posting_schedule": _registration_schedule(),
        },
    )

    assert response.status_code == 200
    assert response.json()["resident"]["home_cluster"] == "SingHealth"


def test_external_registration_creates_initial_posting_history_row() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    before = len(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "History Resident",
            "mcr": "E33333C",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(institution="KTPH"),
        },
    )

    assert response.status_code == 200
    assert len(fake_db.external_resident_postings) == before + 1
    row = fake_db.external_resident_postings[-1]
    assert row["posting_code"] == "KTPHGerMed"
    assert row["programme_code"] == "GERI"
    assert row["is_current"] is True
    assert row["end_date"] == date(2026, 9, 30)


def test_external_registration_creates_forecast_posting_schedule_rows() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    before = len(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Forecast Resident",
            "mcr": "E33334C",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
                {
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-31",
                    "programme_code": "GERI",
                    "institution": "KTPH",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["current_nhg_posting_code"] == "TTSHGerMed"
    assert [row["posting_code"] for row in payload["posting_schedule"]] == [
        "TTSHGerMed",
        "KTPHGerMed",
    ]
    assert [row["programme_code"] for row in payload["posting_schedule"]] == [
        "GERI",
        "GERI",
    ]
    assert len(fake_db.external_resident_postings) == before + 2
    assert fake_db.external_resident_postings[-2]["start_date"] == date(2026, 7, 1)
    assert fake_db.external_resident_postings[-2]["end_date"] == date(2026, 7, 31)
    assert fake_db.commits == 1


@pytest.mark.parametrize("with_native_occupancy", [False, True])
def test_external_registration_resolution_is_independent_of_native_occupancy(
    with_native_occupancy: bool,
) -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    assert not any(
        row["posting_code"] == "KTPHGerMed" for row in fake_db.resident_postings
    )
    if with_native_occupancy:
        fake_db.resident_postings.append(
            {
                **fake_db.resident_postings[0],
                "posting_code": "KTPHGerMed",
            }
        )
    native_residents_before = deepcopy(fake_db.residents)
    native_postings_before = deepcopy(fake_db.resident_postings)
    external_residents_before = len(fake_db.external_residents)
    external_postings_before = len(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Synthetic Occupancy Independent Resident",
            "mcr": "TST90001A" if with_native_occupancy else "TST90002A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "KTPH",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_schedule"][0]["posting_code"] == "KTPHGerMed"
    assert len(fake_db.external_residents) == external_residents_before + 1
    assert len(fake_db.external_resident_postings) == external_postings_before + 1
    assert fake_db.residents == native_residents_before
    assert fake_db.resident_postings == native_postings_before


def test_external_registration_options_return_only_active_ttsh_programmes() -> None:
    fake_db = FakeResidentSession()
    response = _client(fake_db).get("/external-residents/registration-options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["institutions"] == [{"code": "TTSH", "name": "TTSH"}]
    assert [row["programme_code"] for row in payload["programmes"]] == [
        code for code, _posting_code in TTSH_ACTIVE_REGISTRATION_MAPPINGS
    ]
    assert len(payload["programmes"]) == 24
    assert all(
        row["institutions"]
        == [
            {
                "institution_code": "TTSH",
                "available": True,
                "status": "active",
            }
        ]
        for row in payload["programmes"]
    )
    assert not (
        {row["programme_code"] for row in payload["programmes"]}
        & set(TTSH_INACTIVE_REGISTRATION_PROGRAMMES)
    )
    geri = next(
        row for row in payload["programmes"] if row["programme_code"] == "GERI"
    )
    assert geri["programme_name"] == "Geriatric Medicine"
    assert "posting_code" not in response.text


def test_external_registration_options_are_public_through_auth_middleware() -> None:
    client = _middleware_client(FakeResidentSession())

    response = client.get("/external-residents/registration-options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["institutions"] == [{"code": "TTSH", "name": "TTSH"}]
    assert len(payload["programmes"]) == 24


def test_external_registration_options_ignore_stale_bearer_header() -> None:
    client = _middleware_client(FakeResidentSession())

    anonymous_response = client.get("/external-residents/registration-options")
    stale_session_response = client.get(
        "/external-residents/registration-options",
        headers={"Authorization": "Bearer synthetic-expired-token"},
    )

    assert anonymous_response.status_code == 200
    assert stale_session_response.status_code == 200
    assert stale_session_response.json() == anonymous_response.json()


def test_external_registration_remains_public_through_auth_middleware() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    response = _middleware_client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Synthetic Public Registration Resident",
            "mcr": "TST92001A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["resident"]["mcr"] == "TST92001A"


def test_external_posting_schedule_remains_protected_through_auth_middleware() -> None:
    fake_db = FakeResidentSession()
    postings_before = deepcopy(fake_db.external_resident_postings)
    commits_before = fake_db.commits

    response = _middleware_client(fake_db).put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                }
            ]
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Unauthorized",
        "error_code": "UNAUTHORIZED",
        "errors": [],
        "warnings": [],
        "metadata": {},
    }
    assert fake_db.external_resident_postings == postings_before
    assert fake_db.commits == commits_before


def test_external_registration_options_route_has_no_collision() -> None:
    client = _middleware_client(FakeResidentSession())

    route = next(
        route
        for route in client.app.routes
        if getattr(route, "path", None) == "/external-residents/registration-options"
        and "GET" in getattr(route, "methods", set())
    )

    assert route.endpoint is external_residents.list_registration_options


def test_external_registration_options_ignore_secretary_pool_metadata() -> None:
    fake_db = FakeResidentSession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHNeuro",
            "programme_code": "GERI",
            "is_active": True,
        }
    )

    response = _client(fake_db).get("/external-residents/registration-options")

    assert response.status_code == 200
    geri_option = next(
        row
        for row in response.json()["programmes"]
        if row["programme_code"] == "GERI"
    )
    assert geri_option["institutions"] == [
        {
            "institution_code": "TTSH",
            "available": True,
            "status": "active",
        }
    ]


def test_external_registration_rejects_overlapping_forecast_rows() -> None:
    fake_db = FakeResidentSession()
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Overlap Resident",
            "mcr": "E33335C",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
                {
                    "start_date": "2026-07-15",
                    "end_date": "2026-08-15",
                    "programme_code": "GERI",
                    "institution": "KTPH",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before


def test_external_registration_rejects_invalid_forecast_date_range() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Dates",
            "mcr": "E33336C",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-08-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 422


def test_external_registration_rejects_invalid_forecast_programme() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Programme",
            "mcr": "E33337C",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "UNKNOWN",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 422


def test_external_registration_rejects_invalid_forecast_institution() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Institution",
            "mcr": "E33338C",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "SGH",
                },
            ],
        },
    )

    assert response.status_code == 422


def test_external_registration_rejects_invalid_home_cluster() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Cluster",
            "mcr": "E44444D",
            "home_cluster": "MOH",
            "current_nhg_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 422


def test_external_registration_rejects_mcr_already_in_native_residents() -> None:
    fake_db = FakeResidentSession()
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Conflict Native",
            "mcr": "M12345A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(),
        },
    )

    assert response.status_code == 409
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before


def test_external_registration_rejects_mcr_already_in_external_residents() -> None:
    fake_db = FakeResidentSession()
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Conflict External",
            "mcr": "E12345A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(),
        },
    )

    assert response.status_code == 409
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before


def test_external_registration_rejects_invalid_current_posting() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Posting",
            "mcr": "E55555E",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "UNKNOWN",
        },
    )

    assert response.status_code == 422


def test_external_registration_rejects_unresolved_forecast_posting_without_partial_rows() -> None:
    fake_db = FakeResidentSession()
    before_residents = len(fake_db.external_residents)
    before_postings = len(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Schedule Match",
            "mcr": "E55556E",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "WH",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_MISSING_DETAIL
    assert len(fake_db.external_residents) == before_residents
    assert len(fake_db.external_resident_postings) == before_postings


def test_external_registration_rejects_atomic_multi_row_resolution_failure() -> None:
    fake_db = FakeResidentSession()
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)
    native_residents_before = deepcopy(fake_db.residents)
    native_postings_before = deepcopy(fake_db.resident_postings)

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Synthetic Atomic Validation Resident",
            "mcr": "TST92001A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "KTPH",
                },
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "programme_code": "GERI",
                    "institution": "WH",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_MISSING_DETAIL
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before
    assert fake_db.residents == native_residents_before
    assert fake_db.resident_postings == native_postings_before


def test_external_registration_checks_global_mcr_before_schedule_resolution() -> None:
    fake_db = FakeResidentSession()
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Synthetic Duplicate Resident",
            "mcr": "M12345A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "WH",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "MCR already exists"
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before


def test_external_registration_does_not_use_ambiguous_secretary_pool_metadata() -> None:
    fake_db = FakeResidentSession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHNeuro",
            "programme_code": "GERI",
            "is_active": True,
        },
    )
    secretary_pools_before = deepcopy(fake_db.secretary_programme_pools)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Ambiguous Schedule Match",
            "mcr": "E55557E",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_schedule"][0]["posting_code"] == "TTSHGerMed"
    assert fake_db.secretary_programme_pools == secretary_pools_before


def test_external_posting_update_closes_old_and_creates_new_current_row() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    before = len(fake_db.external_resident_postings)
    current_row = next(row for row in fake_db.external_resident_postings if row["is_current"])
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting",
        json={"programme_code": "GERI", "institution": "KTPH"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is True
    assert payload["resident"]["current_nhg_posting_code"] == "KTPHGerMed"
    assert current_row["is_current"] is False
    assert current_row["end_date"] is not None
    assert len(fake_db.external_resident_postings) == before + 1
    assert fake_db.external_resident_postings[-1]["is_current"] is True
    assert fake_db.external_resident_postings[-1]["programme_code"] == "GERI"


def test_external_posting_update_same_posting_is_idempotent() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db, posting_code="TTSHCardio")
    before = len(fake_db.external_resident_postings)
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting",
        json={"programme_code": "CARDIO", "institution": "TTSH"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is False
    assert len(fake_db.external_resident_postings) == before


def test_external_posting_schedule_update_replaces_rows() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "programme_code": "GERI",
                    "institution": "KTPH",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is True
    assert payload["resident"]["current_nhg_posting_code"] == "TTSHGerMed"
    assert [row["posting_code"] for row in payload["posting_schedule"]] == [
        "TTSHGerMed",
        "KTPHGerMed",
    ]
    assert [row["programme_code"] for row in payload["posting_schedule"]] == [
        "GERI",
        "GERI",
    ]
    rows = [
        row
        for row in fake_db.external_resident_postings
        if row["external_resident_id"] == fake_db.external_resident_id
    ]
    assert [row["posting_code"] for row in rows] == ["TTSHGerMed", "KTPHGerMed"]
    assert [row["programme_code"] for row in rows] == ["GERI", "GERI"]


def test_external_posting_schedule_update_rejects_inactive_posting_without_deleting_rows() -> None:
    fake_db = FakeResidentSession()
    before = list(fake_db.external_resident_postings)
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "FM",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_INACTIVE_DETAIL
    assert fake_db.external_resident_postings == before


def test_external_posting_schedule_update_ignores_secretary_pool_metadata() -> None:
    fake_db = FakeResidentSession()
    fake_db.secretary_programme_pools.append(
        {
            "posting_code": "TTSHNeuro",
            "programme_code": "GERI",
            "is_active": True,
        }
    )
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_schedule"][0]["posting_code"] == "TTSHGerMed"


def test_native_resident_cannot_update_external_posting() -> None:
    fake_db = FakeResidentSession()
    client = _client(
        fake_db,
        AuthIdentity(
            role="resident",
            subject_id=fake_db.resident_id,
            programme_code="GRM",
        ),
    )

    response = client.put(
        "/external-residents/me/posting",
        json={"programme_code": "GERI", "institution": "KTPH"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("programme_code", "expected_posting_code"),
    TTSH_ACTIVE_REGISTRATION_MAPPINGS,
)
def test_every_active_ttsh_mapping_resolves_to_the_approved_posting(
    programme_code: str,
    expected_posting_code: str,
) -> None:
    fake_db = FakeResidentSession()

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Approved Mapping Resident",
            "mcr": f"TST{programme_code}9A"[:20],
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(
                programme_code=programme_code,
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["posting_schedule"][0]["posting_code"] == (
        expected_posting_code
    )


@pytest.mark.parametrize(
    "programme_code",
    TTSH_INACTIVE_REGISTRATION_PROGRAMMES,
)
def test_inactive_mapping_is_omitted_from_options_and_registration_rejected(
    programme_code: str,
) -> None:
    fake_db = FakeResidentSession()

    options = _client(fake_db).get("/external-residents/registration-options")
    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Inactive Mapping Resident",
            "mcr": f"TST{programme_code}8A"[:20],
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(
                programme_code=programme_code,
            ),
        },
    )

    assert options.status_code == 200
    assert all(
        row["programme_code"] != programme_code
        for row in options.json()["programmes"]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_INACTIVE_DETAIL


@pytest.mark.parametrize(
    "programme_code",
    TTSH_INACTIVE_REGISTRATION_PROGRAMMES,
)
def test_inactive_mapping_cannot_replace_posting_schedule(
    programme_code: str,
) -> None:
    fake_db = FakeResidentSession()
    before = deepcopy(fake_db.external_resident_postings)
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": _registration_schedule(
                programme_code=programme_code,
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_INACTIVE_DETAIL
    assert fake_db.external_resident_postings == before


def test_future_institutions_appear_from_mapping_data_only() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(
        fake_db,
        institution_code="KTPH",
        posting_code="KTPHGerMed",
    )
    _configure_mapping(
        fake_db,
        programme_code="DR",
        institution_code="WH",
        posting_code=None,
        status="pending",
    )

    response = _client(fake_db).get("/external-residents/registration-options")

    assert response.status_code == 200
    assert {row["code"] for row in response.json()["institutions"]} == {
        "TTSH",
        "KTPH",
        "WH",
    }
    geri = next(
        row
        for row in response.json()["programmes"]
        if row["programme_code"] == "GERI"
    )
    assert any(
        row
        == {
            "institution_code": "KTPH",
            "available": True,
            "status": "active",
        }
        for row in geri["institutions"]
    )


def test_future_pending_mapping_remains_unavailable() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(
        fake_db,
        programme_code="DR",
        institution_code="WH",
        posting_code=None,
        status="pending",
    )

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Future Pending Mapping Resident",
            "mcr": "TSTPENDING1A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(
                programme_code="DR",
                institution="WH",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_PENDING_DETAIL


def test_mixed_active_inactive_registration_is_atomic() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    residents_before = deepcopy(fake_db.external_residents)
    postings_before = deepcopy(fake_db.external_resident_postings)

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Mixed Mapping Resident",
            "mcr": "TSTMIXED001A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "programme_code": "FM",
                    "institution": "TTSH",
                },
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_INACTIVE_DETAIL
    assert fake_db.external_residents == residents_before
    assert fake_db.external_resident_postings == postings_before


def test_mixed_active_inactive_schedule_replacement_keeps_prior_rows() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)
    before = deepcopy(fake_db.external_resident_postings)
    client = _client(
        fake_db,
        AuthIdentity(
            role="external_resident",
            subject_id=fake_db.external_resident_id,
            home_cluster="NUH",
        ),
    )

    response = client.put(
        "/external-residents/me/posting-schedule",
        json={
            "posting_schedule": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "programme_code": "GERI",
                    "institution": "TTSH",
                },
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "programme_code": "FM",
                    "institution": "TTSH",
                },
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == MAPPING_INACTIVE_DETAIL
    assert fake_db.external_resident_postings == before


def test_client_cannot_include_posting_code_in_schedule_row() -> None:
    fake_db = FakeResidentSession()
    _configure_mapping(fake_db)

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Untrusted Posting Resident",
            "mcr": "TSTUNTRUST1A",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    **_registration_schedule()[0],
                    "posting_code": "TTSHNeuro",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert not any(
        row["mcr"] == "TSTUNTRUST1A"
        for row in fake_db.external_residents
    )


def test_active_mapping_does_not_mutate_native_secretary_or_compliance_configuration() -> None:
    fake_db = FakeResidentSession()
    native_programmes = deepcopy(fake_db.programmes)
    native_postings = deepcopy(fake_db.resident_postings)
    secretary_pools = deepcopy(fake_db.secretary_programme_pools)
    posting_codes = deepcopy(fake_db.posting_codes)
    teaching_targets = deepcopy(fake_db.teaching_targets)
    teaching_catalogue = deepcopy(fake_db.catalogue)
    teaching_events = deepcopy(fake_db.events)
    weekend_exceptions = deepcopy(fake_db.weekend_exceptions)
    global_session_types = deepcopy(fake_db.global_session_types)
    _configure_mapping(fake_db)

    response = _client(fake_db).post(
        "/external-residents/register",
        json={
            "name": "Isolated Mapping Resident",
            "mcr": "TSTISOLATE1A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(),
        },
    )

    assert response.status_code == 200
    assert fake_db.programmes == native_programmes
    assert fake_db.resident_postings == native_postings
    assert fake_db.secretary_programme_pools == secretary_pools
    assert fake_db.posting_codes == posting_codes
    assert fake_db.teaching_targets == teaching_targets
    assert fake_db.catalogue == teaching_catalogue
    assert fake_db.events == teaching_events
    assert fake_db.weekend_exceptions == weekend_exceptions
    assert fake_db.global_session_types == global_session_types


def test_embedded_control_character_in_mapping_input_is_rejected() -> None:
    response = _client(FakeResidentSession()).post(
        "/external-residents/register",
        json={
            "name": "Control Character Resident",
            "mcr": "TSTCONTROL1A",
            "home_cluster": "NUH",
            "posting_schedule": _registration_schedule(institution="TT\u0007SH"),
        },
    )

    assert response.status_code == 422
    assert "control characters" in response.json()["detail"]
