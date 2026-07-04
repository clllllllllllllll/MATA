from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.auth_stub import AuthIdentity
from app.middleware.errors import install_error_handlers
from app.routers import external_residents
from tests.resident_fakes import FakeResidentSession


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

    app.dependency_overrides[external_residents.get_db_session] = _db_override
    app.include_router(external_residents.router)
    return TestClient(app)


def test_external_registration_succeeds_for_nuh() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "NUH Resident",
            "mcr": "E11111A",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["home_cluster"] == "NUH"
    assert payload["resident"]["mcr"] == "E11111A"


def test_external_registration_succeeds_for_singhealth() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "SH Resident",
            "mcr": "E22222B",
            "home_cluster": "SingHealth",
            "current_nhg_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 200
    assert response.json()["resident"]["home_cluster"] == "SingHealth"


def test_external_registration_creates_initial_posting_history_row() -> None:
    fake_db = FakeResidentSession()
    before = len(fake_db.external_resident_postings)
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "History Resident",
            "mcr": "E33333C",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "KTPHGerMed",
        },
    )

    assert response.status_code == 200
    assert len(fake_db.external_resident_postings) == before + 1
    row = fake_db.external_resident_postings[-1]
    assert row["posting_code"] == "KTPHGerMed"
    assert row["is_current"] is True
    assert row["end_date"] is None


def test_external_registration_creates_forecast_posting_schedule_rows() -> None:
    fake_db = FakeResidentSession()
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
                    "programme_code": "GRM",
                    "institution": "TTSH",
                    "posting_code": "TTSHCardio",
                },
                {
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-31",
                    "programme_code": "GRM",
                    "institution": "KTPH",
                    "posting_code": "KTPHGerMed",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resident"]["current_nhg_posting_code"] == "TTSHCardio"
    assert [row["posting_code"] for row in payload["posting_schedule"]] == [
        "TTSHCardio",
        "KTPHGerMed",
    ]
    assert len(fake_db.external_resident_postings) == before + 2
    assert fake_db.external_resident_postings[-2]["start_date"] == date(2026, 7, 1)
    assert fake_db.external_resident_postings[-2]["end_date"] == date(2026, 7, 31)


def test_external_registration_rejects_overlapping_forecast_rows() -> None:
    fake_db = FakeResidentSession()
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
                    "programme_code": "GRM",
                    "institution": "TTSH",
                    "posting_code": "TTSHCardio",
                },
                {
                    "start_date": "2026-07-15",
                    "end_date": "2026-08-15",
                    "programme_code": "GRM",
                    "institution": "KTPH",
                    "posting_code": "KTPHGerMed",
                },
            ],
        },
    )

    assert response.status_code == 422


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
                    "programme_code": "GRM",
                    "institution": "TTSH",
                    "posting_code": "TTSHCardio",
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
                    "posting_code": "TTSHCardio",
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
                    "programme_code": "GRM",
                    "institution": "SGH",
                    "posting_code": "TTSHCardio",
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
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Conflict Native",
            "mcr": "M12345A",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 409


def test_external_registration_rejects_mcr_already_in_external_residents() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Conflict External",
            "mcr": "E12345A",
            "home_cluster": "NUH",
            "current_nhg_posting_code": "TTSHCardio",
        },
    )

    assert response.status_code == 409


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


def test_external_registration_rejects_invalid_forecast_posting() -> None:
    fake_db = FakeResidentSession()
    client = _client(fake_db)

    response = client.post(
        "/external-residents/register",
        json={
            "name": "Bad Schedule Posting",
            "mcr": "E55556E",
            "home_cluster": "NUH",
            "posting_schedule": [
                {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "programme_code": "GRM",
                    "institution": "TTSH",
                    "posting_code": "UNKNOWN",
                },
            ],
        },
    )

    assert response.status_code == 422


def test_external_posting_update_closes_old_and_creates_new_current_row() -> None:
    fake_db = FakeResidentSession()
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
        json={"current_nhg_posting_code": "KTPHGerMed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is True
    assert payload["resident"]["current_nhg_posting_code"] == "KTPHGerMed"
    assert current_row["is_current"] is False
    assert current_row["end_date"] is not None
    assert len(fake_db.external_resident_postings) == before + 1
    assert fake_db.external_resident_postings[-1]["is_current"] is True


def test_external_posting_update_same_posting_is_idempotent() -> None:
    fake_db = FakeResidentSession()
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
        json={"current_nhg_posting_code": "TTSHCardio"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is False
    assert len(fake_db.external_resident_postings) == before


def test_external_posting_schedule_update_replaces_rows() -> None:
    fake_db = FakeResidentSession()
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
                    "programme_code": "GRM",
                    "institution": "TTSH",
                    "posting_code": "TTSHCardio",
                },
                {
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-31",
                    "programme_code": "GRM",
                    "institution": "KTPH",
                    "posting_code": "KTPHGerMed",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is True
    assert payload["resident"]["current_nhg_posting_code"] == "TTSHCardio"
    assert [row["posting_code"] for row in payload["posting_schedule"]] == [
        "TTSHCardio",
        "KTPHGerMed",
    ]
    rows = [
        row
        for row in fake_db.external_resident_postings
        if row["external_resident_id"] == fake_db.external_resident_id
    ]
    assert [row["posting_code"] for row in rows] == ["TTSHCardio", "KTPHGerMed"]


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
        json={"current_nhg_posting_code": "KTPHGerMed"},
    )

    assert response.status_code == 403
