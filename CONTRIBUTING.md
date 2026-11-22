# Contributing

## Setup

You need [uv](https://docs.astral.sh/uv/) and Docker (for PostgreSQL).

```sh
uv sync                                   # Python 3.12+ and the dependencies
docker run -d --name invoice-api-db -p 5433:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=invoice_api postgres:17-alpine
uv run alembic upgrade head               # create the tables
uv run python -m invoice_api.seed         # load the demo data
uv run uvicorn invoice_api.main:app --reload
```

The defaults point at `localhost:5433`. Copy `.env.example` to `.env` to change them.

## Checks

Run these before opening a pull request; CI runs the same:

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

The tests create their own database, `invoice_api_test`, on the same server. Set `TEST_DATABASE_URL` to use another.

## Conventions

- **Python:**
  - type hints everywhere (`mypy --strict`);
  - `ruff` formats, with lines of up to 100 characters.
- **The contract comes first:** the API implements the frontend's [contract/schema.yml](contract/schema.yml).
  - Don't change a response shape without changing the frontend's contract too.
  - `tests/test_contract.py` must keep passing.
- **Errors:** raise `NotFoundError`, `UnprocessableError` or `BadRequestError` from `errors.py`. They become `{"message": ...}` responses.
- **Schema changes:**
  - only through a new Alembic migration, with a working `downgrade()`;
  - update `models.py` to match.
- **Money:** `NUMERIC` in the database, `Decimal` in Python, two-decimal strings in JSON. Never `float`.
- **Business rules:** `invoices.py` holds them. Add a test for each new rule, and a database constraint when it protects stored data.
- **Commits:** small and focused. Pull requests describe what changed and how it was tested.
