"""Demo data: the same customers, products and invoices as the frontend's
in-browser mock API, so the app looks the same on either backend.

It ports the frontend's seeded random number generator (mulberry32) bit for
bit, and draws the numbers in the same order. tests/test_seed.py compares the
result with a JSON export of the frontend's data.

    uv run python -m invoice_api.seed           # load into an empty database
    uv run python -m invoice_api.seed --reset   # wipe the tables first
    uv run python -m invoice_api.seed --if-empty  # only if there are no customers yet
"""

import argparse
import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, insert, text

from invoice_api.db import get_engine
from invoice_api.models import Customer, Invoice, InvoiceLine, Product
from invoice_api.seed_data import CITIES, FIRST_NAMES, LAST_NAMES, PRODUCT_CATALOG, STREETS

MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    """JavaScript's Math.imul: the low 32 bits of a * b."""
    return (a * b) & MASK


def mulberry32(seed: int) -> Callable[[], float]:
    """The frontend's generator: same seed, same numbers in [0, 1)."""
    state = seed & MASK

    def random() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK
        t = _imul(state ^ (state >> 15), 1 | state)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & MASK) ^ t
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return random


@dataclass
class SeedData:
    customers: list[dict[str, object]] = field(default_factory=list)
    products: list[dict[str, object]] = field(default_factory=list)
    invoices: list[dict[str, object]] = field(default_factory=list)
    lines: list[dict[str, object]] = field(default_factory=list)


def product_prices(price_without_tax: str, vat_rate: str) -> tuple[str, str]:
    """(unit_tax, unit_price), rounded like the frontend and the database."""
    without_tax = Decimal(price_without_tax)
    tax = (without_tax * Decimal(vat_rate) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"{tax:.2f}", f"{without_tax + tax:.2f}"


def build_seed() -> SeedData:
    random = mulberry32(42)

    def pick[T](items: Sequence[T]) -> T:
        return items[int(random() * len(items))]

    def between(low: int, high: int) -> int:
        return low + int(random() * (high - low + 1))

    data = SeedData()

    for customer_id in range(1, 41):
        # Same draw order as the frontend: city, first name, last name, number, street.
        city, zip_code = pick(CITIES)
        first_name = pick(FIRST_NAMES)
        last_name = pick(LAST_NAMES)
        number = between(1, 120)
        street = pick(STREETS)
        data.customers.append(
            {
                "id": customer_id,
                "first_name": first_name,
                "last_name": last_name,
                "address": f"{number} {street}",
                "zip_code": zip_code,
                "city": city,
                "country": "France",
                "country_code": "FR",
            }
        )

    for product_id, (label, unit, vat_rate, price) in enumerate(PRODUCT_CATALOG, start=1):
        data.products.append(
            {
                "id": product_id,
                "label": label,
                "unit": unit,
                "vat_rate": Decimal(vat_rate),
                "unit_price_without_tax": Decimal(price),
            }
        )

    start = dt.date(2025, 1, 6)
    line_id = 1
    for invoice_id in range(1, 61):
        issued = start + dt.timedelta(days=between(0, 640))
        deadline = issued + dt.timedelta(days=pick([15, 30, 45, 60]))
        finalized = random() < 0.65
        # Like `finalized && random() < 0.55`: no number is drawn for drafts.
        paid = finalized and random() < 0.55
        for _ in range(between(1, 4)):
            data.lines.append(
                {
                    "id": line_id,
                    "invoice_id": invoice_id,
                    "product_id": pick(data.products)["id"],
                    "quantity": between(1, 10),
                }
            )
            line_id += 1
        data.invoices.append(
            {
                "id": invoice_id,
                "customer_id": pick(data.customers)["id"],
                "finalized": finalized,
                "paid": paid,
                "date": issued,
                "deadline": deadline,
            }
        )
    return data


TABLES = ("invoice_lines", "invoices", "products", "customers")


def load(connection: Connection, *, reset: bool = False) -> None:
    """Insert the demo data in one transaction (the caller commits)."""
    if reset:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    data = build_seed()
    connection.execute(insert(Customer), data.customers)
    connection.execute(insert(Product), data.products)
    connection.execute(insert(Invoice), data.invoices)
    connection.execute(insert(InvoiceLine), data.lines)
    # The rows above have explicit ids, so move each id sequence past them.
    for table in TABLES:
        connection.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT coalesce(max(id), 0) + 1 FROM {table}), false)"
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the demo data.")
    parser.add_argument("--reset", action="store_true", help="delete all data first")
    parser.add_argument("--if-empty", action="store_true", help="skip if there is data already")
    args = parser.parse_args()
    with get_engine().begin() as connection:
        if args.if_empty and connection.scalar(text("SELECT count(*) FROM customers")):
            print("The database has data already; nothing loaded.")
            return
        load(connection, reset=args.reset)
    print("Demo data loaded: 40 customers, 25 products, 60 invoices.")


if __name__ == "__main__":
    main()
