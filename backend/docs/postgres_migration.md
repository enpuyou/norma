# Postgres Migration Path

This project now supports PostgreSQL runtime via `DATABASE_URL`.

## 1) Start Postgres

Use the root compose stack:

```bash
docker compose up -d db
```

## 2) Configure backend

Set:

```bash
DATABASE_URL=postgresql+asyncpg://norma:norma@localhost:5432/norma
```

## 3) Initialize schema

Start backend once; `init_db()` creates tables in the target database.

## 4) Optional data migration from SQLite

Use a one-time export/import script or SQL dump tooling to copy data from `norma.db` into Postgres.

## Notes

- Async engine uses `postgresql+asyncpg`.
- Sync callbacks use `postgresql+psycopg2` conversion internally.
- SQLite-specific `PRAGMA` additive migrations are skipped on Postgres.
