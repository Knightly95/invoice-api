# Notes for coding agents

REST API for invoices, customers and products: Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2 (typed ORM), Alembic and Pydantic 2. It implements the OpenAPI contract of the frontend, [invoice-editor](https://github.com/Knightly95/invoice-editor), copied to `contract/schema.yml`.

## Commands

```sh
uv sync
uv run alembic upgrade head
uv run python -m invoice_api.seed [--reset | --if-empty]
uv run uvicorn invoice_api.main:app --reload
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
docker compose up --build        # API and PostgreSQL together
```

The tests need PostgreSQL (default `localhost:5433`, user and password `postgres`). They create `invoice_api_test` and `invoice_api_migrations` themselves.

## Where things are

- `main.py`: routes only. Business logic lives in `invoices.py`, SQL building in `queries.py`.
- `models.py` and `migrations/versions/` must describe the same schema.
- `schemas.py`: response shapes follow the contract exactly. Money and VAT rates are strings, and `customer` is left out (not `null`) when an invoice has none.
- `seed_data.py` is generated from the frontend's `src/mockApi/seed.ts`. Don't edit it by hand; `tests/test_seed.py` compares the seed with `tests/fixtures/frontend_seed.json`.
- `docs/database.md` explains the schema, indexes, transactions and queries. Update it when they change.

## Rules

- Keep the behaviour identical to the frontend's in-browser mock API (`src/mockApi/handlers.ts` in invoice-editor). The frontend must work against either.
- Every change that writes data goes through `transaction()` in `invoices.py`. Updates and deletes lock the invoice row first.
- Relationships are `lazy="raise"`: load what a response needs with `FULL_INVOICE`, never with one query per row.
- Schema changes need a migration with a working `downgrade()`. `test_migrations_upgrade_downgrade_and_upgrade_again` checks it.
- Never commit secrets or real connection strings. Production settings come from environment variables (`render.yaml`).
- Work on a branch and open a pull request; don't push to `main`.
