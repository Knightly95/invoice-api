"""The database itself: migrations both ways, constraints, indexes and locks."""

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from invoice_api import invoices
from invoice_api.schemas import InvoiceInput
from tests.conftest import TEST_DATABASE_URL, downgrade, ensure_database, migrate, reset_schema

TABLES = {"customers", "products", "invoices", "invoice_lines"}


@pytest.fixture
def scratch_engine() -> Iterator[Engine]:
    """An empty database of its own, so migrations can run both ways."""
    url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/invoice_api_migrations"
    ensure_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        reset_schema(connection)
    yield engine
    engine.dispose()


def test_migrations_upgrade_downgrade_and_upgrade_again(scratch_engine: Engine) -> None:
    with scratch_engine.begin() as connection:
        migrate(connection)
        assert set(inspect(connection).get_table_names()) >= TABLES
        downgrade(connection, "base")
        assert not TABLES & set(inspect(connection).get_table_names())
        migrate(connection)
        assert set(inspect(connection).get_table_names()) >= TABLES


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE invoices SET paid = true, finalized = false WHERE id = 1",
        "UPDATE invoice_lines SET quantity = 0 WHERE id = 1",
        "UPDATE products SET vat_rate = 7 WHERE id = 1",
        "DELETE FROM products WHERE id IN (SELECT product_id FROM invoice_lines)",
        "DELETE FROM customers WHERE id = (SELECT customer_id FROM invoices WHERE id = 1)",
    ],
)
def test_the_database_enforces_the_rules_too(db: Session, statement: str) -> None:
    """Even a script that skips the API can't store a paid draft, a zero
    quantity, an unknown VAT rate, or remove a product or customer in use."""
    with pytest.raises(IntegrityError):
        db.execute(text(statement))
        db.flush()


def test_generated_prices_follow_the_price(db: Session) -> None:
    db.execute(text("UPDATE products SET unit_price_without_tax = 100 WHERE id = 1"))
    row = db.execute(text("SELECT unit_tax, unit_price FROM products WHERE id = 1")).one()
    assert (str(row.unit_tax), str(row.unit_price)) == ("20.00", "120.00")


def test_searches_can_use_the_trigram_indexes(db: Session) -> None:
    """With sequential scans off, PostgreSQL picks the GIN index. (On 40 rows
    it rightly prefers a plain scan; the index pays off on large tables.)"""
    db.execute(text("SET LOCAL enable_seqscan = off"))
    plans = [
        db.execute(text(f"EXPLAIN {query}")).scalars().all()
        for query in (
            "SELECT * FROM products WHERE label ILIKE '%develop%'",
            "SELECT * FROM customers WHERE (first_name || ' ' || last_name) ILIKE '%mart%'",
        )
    ]
    for plan in plans:
        assert any("trgm" in line for line in plan), "\n".join(plan)


def test_a_locked_invoice_waits_instead_of_being_overwritten(engine: Engine) -> None:
    """While one transaction is changing invoice 1, another update of it waits
    for the lock; here it gives up after 200 ms rather than overwrite."""
    holding = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SELECT id FROM invoices WHERE id = 1 FOR UPDATE"))
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert holding.wait(5)
        with engine.connect() as connection:
            connection.execute(text("SET lock_timeout = '200ms'"))
            connection.commit()
            with (
                Session(bind=connection) as session,
                pytest.raises(OperationalError, match="lock timeout"),
            ):
                invoices.update_invoice(session, 1, InvoiceInput(date=None))
    finally:
        release.set()
        holder.join()
