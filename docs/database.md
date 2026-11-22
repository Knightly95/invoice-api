# The database, explained

This guide walks through every database decision in the API, with the real SQL. Each section ends with a question an interviewer might ask.

To follow along, run the database (`docker compose up db`, or the container from [CONTRIBUTING.md](../CONTRIBUTING.md)) and open a SQL shell:

```sh
docker compose exec db psql -U postgres -d invoice_api
```

## 1. The schema

Four tables. Arrows are foreign keys.

```
customers ◄── invoices ◄── invoice_lines ──► products
```

| Table | What a row is | Notable columns |
|---|---|---|
| `customers` | a customer | names, address, country code |
| `products` | something you can invoice | price without tax, VAT rate, and **generated** tax and price |
| `invoices` | an invoice | customer, `finalized`, `paid`, date, deadline |
| `invoice_lines` | one product on one invoice | product, quantity |

The schema is created by a migration, [migrations/versions/0001_initial_schema.py](../migrations/versions/0001_initial_schema.py), not by the application. See section 7.

**Ask yourself:** why is `customer_id` on `invoices` and not a list of invoices on `customers`? (One-to-many: the foreign key lives on the "many" side.)

## 2. Money is `NUMERIC`, never `float`

```sql
unit_price_without_tax NUMERIC(12, 2) NOT NULL
```

`NUMERIC(12, 2)` stores exact decimals: up to 12 digits, 2 after the point. A `float` can't store 0.10 exactly, so sums drift by fractions of a cent. In Python the values arrive as `Decimal`, and the API sends them as strings ("1980.00"), as the contract asks, so JSON never turns them into floats either.

**Ask yourself:** what does `SELECT 0.1::float + 0.2::float = 0.3::float;` return, and why?

## 3. Generated columns: prices that can't disagree

The tax and the price with tax follow from two other columns, so PostgreSQL computes them:

```sql
unit_tax   NUMERIC(12, 2) GENERATED ALWAYS AS
             (round(unit_price_without_tax * vat_rate / 100, 2)) STORED,
unit_price NUMERIC(12, 2) GENERATED ALWAYS AS
             (unit_price_without_tax + round(unit_price_without_tax * vat_rate / 100, 2)) STORED
```

Nobody can store a price that doesn't match its tax, not the API and not a manual `UPDATE`. `round` rounds half away from zero, like the frontend's `big.js`. `tests/test_seed.py` checks that all 25 products get exactly the frontend's prices.

Try it:

```sql
UPDATE products SET unit_price_without_tax = 100 WHERE id = 1;
SELECT unit_tax, unit_price FROM products WHERE id = 1;   -- 20.00, 120.00
```

**Ask yourself:** why is `unit_price` written out in full instead of `unit_price_without_tax + unit_tax`? (A generated column can't refer to another generated column.)

## 4. Totals are computed, not stored

An invoice's total is never saved. It is summed from its lines at the products' current prices whenever it is read:

```sql
SELECT invoices.*
FROM invoices
LEFT OUTER JOIN (
    SELECT invoice_lines.invoice_id,
           sum(invoice_lines.quantity * products.unit_price) AS total,
           sum(invoice_lines.quantity * products.unit_tax)   AS tax
    FROM invoice_lines
    JOIN products ON products.id = invoice_lines.product_id
    GROUP BY invoice_lines.invoice_id
) AS line_totals ON line_totals.invoice_id = invoices.id
WHERE invoices.paid IS NOT DISTINCT FROM false
ORDER BY coalesce(line_totals.total, 0) DESC NULLS LAST, invoices.id ASC
LIMIT 25 OFFSET 0;
```

That is the exact SQL behind `GET /invoices?filter=[{"field":"paid","operator":"eq","value":false}]&sort=-total`, built in [queries.py](../src/invoice_api/queries.py).

- **`JOIN`** keeps only lines whose product exists, which is always true thanks to the foreign key.
- **`GROUP BY` with `sum`** turns many lines into one row per invoice.
- **`LEFT OUTER JOIN`** keeps invoices that have no lines. Their `total` is `NULL`, which `coalesce(..., 0)` turns into 0.
- **Sorting and filtering happen on the same computed value** the response shows, so page 2 really follows page 1.

The original API this frontend was built against stored totals when an invoice was created and never updated them. Swapping a product left the total wrong, and sorting by total used the stale numbers. Those are issues BI-1 and BI-2 in the frontend's `backend_issues.md`, which needs client-side workarounds for them. Here they can't happen, and `test_changing_a_product_recomputes_prices` and `test_sorts_by_computed_total_across_pages` prove it.

**The trade-off:** every list request sums all lines. That is instant at demo size. With millions of lines you would keep a `total` column updated in the same transaction as the lines, or by a trigger, and test that it never drifts.

**Ask yourself:** what would `INNER JOIN line_totals` change? (Invoices without lines would disappear from the list.)

## 5. Constraints: the database keeps the rules too

The API checks the business rules, and the database enforces the most important ones as well. So does a script, a migration or a bug that skips the API:

```sql
CHECK (finalized OR NOT paid)                 -- a draft can't be paid
CHECK (quantity > 0)
CHECK (vat_rate IN (0, 5.5, 10, 20))
CHECK (unit_price_without_tax >= 0)
FOREIGN KEY (product_id)  REFERENCES products  ON DELETE RESTRICT  -- can't delete a product in use
FOREIGN KEY (customer_id) REFERENCES customers ON DELETE RESTRICT
FOREIGN KEY (invoice_id)  REFERENCES invoices  ON DELETE CASCADE   -- deleting an invoice deletes its lines
```

`tests/test_database.py` runs raw SQL against each one and expects it to be refused.

**Ask yourself:** why `RESTRICT` for products but `CASCADE` for invoice lines? (A line is part of its invoice; a product is shared by many invoices.)

## 6. Indexes, and when they help

| Index | Used by |
|---|---|
| Primary keys (automatic) | `GET /invoices/{id}`, every join |
| `invoices(customer_id)` | the customer filter; checking the foreign key when a customer is deleted |
| `invoices(deadline)` | sorting and filtering by deadline |
| `invoice_lines(invoice_id)`, `invoice_lines(product_id)` | loading an invoice's lines; summing totals; the foreign keys |
| GIN trigram on `products(label)` | product search |
| GIN trigram on `(first_name \|\| ' ' \|\| last_name)` and the reverse order | customer search, in both name orders |

PostgreSQL doesn't index foreign keys automatically. Without `invoice_lines(invoice_id)`, loading one invoice's lines scans every line.

**Trigram indexes:** a normal B-tree index can't help `ILIKE '%dup%'`, because the text can match anywhere. The `pg_trgm` extension splits text into three-letter pieces ("dup", "upo", "pon"…) and a GIN index finds rows that share them. The search query uses the same expression as the index, with a literal `' '`, so the planner can match them.

Check it yourself. On 40 rows a plain scan is faster, so PostgreSQL rightly ignores the index unless you forbid scans:

```sql
SET enable_seqscan = off;
EXPLAIN SELECT * FROM customers
WHERE (first_name || ' ' || last_name) ILIKE '%mart%';
-- Bitmap Index Scan on ix_customers_first_last_trgm
```

**Ask yourself:** why not index every column? (Each index slows down writes and takes space; add one for a query you actually run.)

## 7. Migrations with Alembic

The schema changes only through numbered migration files in `migrations/versions/`. Each has an `upgrade()` and a `downgrade()`.

```sh
uv run alembic upgrade head      # apply every migration not applied yet
uv run alembic downgrade -1      # undo the last one
uv run alembic history           # list them
```

Alembic records the current version in the `alembic_version` table. The Docker image runs `alembic upgrade head` before it starts serving. `test_migrations_upgrade_downgrade_and_upgrade_again` applies all migrations, undoes them and applies them again on an empty database, so a broken `downgrade()` fails CI.

For a new column: change [models.py](../src/invoice_api/models.py), run `uv run alembic revision --autogenerate -m "add notes to invoices"`, read and fix what it generated, and add a test.

**Ask yourself:** how do you add a `NOT NULL` column to a table that already has rows? (Add it nullable, or with a default; fill it; then set `NOT NULL`, possibly in separate migrations.)

## 8. Transactions and locking

Every change is one transaction. Creating an invoice with three lines either stores all of it or nothing. If the third product doesn't exist, the invoice and the first two lines are rolled back. See `test_a_rejected_create_leaves_nothing_behind`.

Updates also take a **row lock** first:

```sql
SELECT ... FROM invoices WHERE invoices.id = 15 FOR UPDATE OF invoices;
```

If two people save invoice 15 at the same moment, the second waits until the first commits. It then reads the saved lines, so it can't overwrite them with a stale copy. `test_a_locked_invoice_waits_instead_of_being_overwritten` holds the lock from one connection and shows the other one waiting. That test sets a 200 ms `lock_timeout`, so it gives up instead of hanging.

`FOR UPDATE OF invoices` locks only the invoice row, not the customer row joined to it.

**Ask yourself:** what is a "lost update", and which isolation level would also prevent it? (`REPEATABLE READ` would make the second save fail instead of wait.)

## 9. Pagination

```sql
... ORDER BY ..., invoices.id ASC LIMIT 25 OFFSET 25   -- page 2
SELECT count(*) FROM (...same query without ORDER BY...) -- total_entries
```

- The sort always ends with `id`, so rows with the same total have a fixed order and can't appear on two pages.
- `OFFSET` is simple and fits the frontend's numbered pages, but PostgreSQL still reads and skips every row before the page. For very deep pages, keyset pagination (`WHERE (total, id) < (:last_total, :last_id)`) is faster.

## 10. Loading related rows without N+1 queries

An invoice response needs its customer, its lines and each line's product. Loading each line's product separately would cost one query per line: the N+1 problem. The API asks for everything up front ([invoices.py](../src/invoice_api/invoices.py)):

```python
joinedload(Invoice.customer)  # same query, JOIN
selectinload(Invoice.lines).joinedload(
    InvoiceLine.product
)  # 1 more query: WHERE invoice_id IN (...)
```

A page of 25 invoices takes three queries (count, invoices with customers, lines with products), whatever the number of lines. The relationships are declared `lazy="raise"`, so code that forgets to load something fails in the tests instead of running a hidden query per row.

## Study path

1. Sections 1–3 with `psql` open: create a product and look at its generated columns.
2. Section 4: run the totals query by hand, then change it to an `INNER JOIN` and compare.
3. Sections 5–6: try breaking each constraint; use `EXPLAIN` with `enable_seqscan` on and off.
4. Sections 7–8: add a column with a migration, and open two `psql` windows to watch `FOR UPDATE` wait.
