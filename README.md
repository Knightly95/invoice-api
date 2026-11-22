# invoice-api

[![CI](https://github.com/Knightly95/invoice-api/actions/workflows/ci.yml/badge.svg)](https://github.com/Knightly95/invoice-api/actions/workflows/ci.yml)

The backend for [Invoice Editor](https://github.com/Knightly95/invoice-editor): a REST API for invoices, customers and products, written in **Python** with **FastAPI**, **PostgreSQL**, **SQLAlchemy 2** and **Alembic**.

It implements the OpenAPI contract the frontend already uses ([contract/schema.yml](contract/schema.yml)). The frontend works against it with no changes: set its `REACT_APP_API_URL`, and the list, sorting, invoice pages and edits all go to this API.

## What it shows

- **The frontend's contract, checked by tests:** every endpoint's response is validated against the frontend's OpenAPI file, including nullable fields and money as strings.

- **Totals that can't go stale:** invoice totals are summed in SQL from current product prices, and sorting and filtering use the same computed values. The original API stored totals at creation time and never updated them (issues BI-1 and BI-2 in the frontend's `backend_issues.md`). The new tests prove both are gone.

- **Rules in two places:** the API enforces the invoicing rules (only a finalized invoice can be paid, a finalized invoice can only be marked as paid, it can't be deleted). The database enforces the critical ones with `CHECK` and foreign-key constraints.

- **Transactions and row locks:** every change is all-or-nothing, and updates lock the invoice (`SELECT … FOR UPDATE`), so two simultaneous saves can't overwrite each other.

- **Search that can use indexes:** case-insensitive "contains" search on products and customers, with trigram (GIN) indexes. Customers match in either name order.

- **Roles:** sessions are signed tokens (JWT) with a role. Viewers can read; accountants can also create, change and delete.

- **Migrations:** Alembic, tested in both directions.

- **The same demo data as the frontend:** the seed ports the frontend's random-number generator bit for bit, and a test compares the result with an export of the frontend's data.

[docs/database.md](docs/database.md) explains every database decision with the real SQL.

## Endpoints

Interactive documentation is at `/docs` once the API runs.

| Method and path | Role | What it does |
| --- | --- | --- |
| `POST /sessions` | anyone | Demo sign-in: `{"role": "viewer" \| "accountant"}` returns a token |
| `GET /invoices` | viewer | List with `page`, `per_page`, `filter` and `sort` |
| `GET /invoices/{id}` | viewer | One invoice, with customer, lines and products |
| `POST /invoices` | accountant | Create an invoice and its lines |
| `PUT /invoices/{id}` | accountant | Change fields; add, change or remove lines |
| `DELETE /invoices/{id}` | accountant | Delete a draft |
| `GET /products/search` | viewer | Search products by label |
| `GET /customers/search` | viewer | Search customers by name |
| `GET /health` | anyone | The API and its database answer |

Send the token in the `X-SESSION` header, as the contract says. Errors are `{"message": "..."}` with status 400 (bad filter or sort), 401 (no or bad session), 403 (wrong role), 404 or 422 (a rule was broken).

**Filters** are a JSON list, and every clause must match: `[{"field": "paid", "operator": "eq", "value": false}]`.

- Operators: `eq`, `not_eq`, `gt`, `gteq`, `lt`, `lteq`, `in`, `not_in`.

- Fields: `id`, `customer_id`, `finalized`, `paid`, `date`, `deadline`, `total`, `tax`.

**Sorting:** `sort=+deadline,-total`. Empty values sort last.

## Run it

With Docker. This starts PostgreSQL and the API, applies the migrations and loads the demo data:

```sh
docker compose up --build
```

Open <http://localhost:8000/docs>, call `POST /sessions` and click **Authorize**… or use curl:

```sh
token=$(curl -s -X POST localhost:8000/sessions -H 'Content-Type: application/json' \
  -d '{"role":"accountant"}' | jq -r .token)
curl -s "localhost:8000/invoices?per_page=5&sort=-total" -H "X-SESSION: $token" | jq
```

To run the frontend against it, start [invoice-editor](https://github.com/Knightly95/invoice-editor) with the API's address and a token:

```sh
REACT_APP_API_URL=http://localhost:8000 REACT_APP_API_TOKEN=$token yarn start
```

Without Docker, and for tests, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Tests

```sh
uv run pytest --cov
```

The 91 tests run against a real PostgreSQL. Each test runs in a transaction that is rolled back, so tests don't affect each other. They cover:

- the contract shapes;
- filters, sorting and pages;
- every invoicing rule;
- search, roles and sessions;
- the seed matching the frontend;
- the database constraints, indexes and row locks;
- migrations both ways;
- the number of queries per page.

CI runs:

- `ruff` (lint and format) and `mypy` in strict mode;
- the tests with at least 90% coverage;
- a build of the Docker image, started together with PostgreSQL and checked with a smoke test.

## Project layout

```text
src/invoice_api/
  main.py        routes
  invoices.py    invoice rules, transactions and locking
  queries.py     filters, sorting, pagination and the totals query
  models.py      tables (SQLAlchemy)
  schemas.py     request and response bodies (Pydantic), shaped like the contract
  auth.py        sessions and roles
  seed.py        demo data, the same as the frontend's
migrations/      Alembic migrations
contract/        the frontend's OpenAPI contract
docs/            database.md: the database decisions, explained
```

## Hosting

The demo is set up for free hosting: the API on Render (see [render.yaml](render.yaml)) and PostgreSQL on Supabase. Free services sleep when idle, so the first request after a while can take about a minute. A nightly workflow resets the demo data.

## How AI was used

I built this API with an AI coding agent (Claude Code), as a project to put my Python and PostgreSQL work in public.

**What the agent did:** wrote the code, tests, migrations and documentation to my brief: implement the frontend's existing contract in Python, with the database doing the work.

**How it is checked:**

- The contract tests validate every response against the frontend's own OpenAPI file.
- The real frontend was run against the API in a browser: the list, sorting by total, the invoice page and marking an invoice as paid or unpaid.
- Changes go through pull requests. I review and merge them.
