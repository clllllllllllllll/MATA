# Development Setup (Docker)

## 1. Create local env file

```bash
cp .env.example .env
```

`.env` is local-only and must never be committed.

## 2. Start backend and database

```bash
docker compose up --build
```

## 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

## 4. Run backend tests

```bash
docker compose exec backend pytest -q
```
