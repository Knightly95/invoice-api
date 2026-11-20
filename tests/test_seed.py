"""The seed must match the frontend's demo data exactly (exported from
invoice-editor's src/mockApi/seed.ts to tests/fixtures/frontend_seed.json)."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from invoice_api.models import Product
from invoice_api.schemas import money, vat_rate
from invoice_api.seed import build_seed, mulberry32, product_prices

FRONTEND = json.loads(
    (Path(__file__).parent / "fixtures" / "frontend_seed.json").read_text(encoding="utf8")
)


def test_random_numbers_match_javascript() -> None:
    # First values of mulberry32(42) in JavaScript.
    random = mulberry32(42)
    first = [random() for _ in range(3)]
    assert first == [0.6011037519201636, 0.44829055899754167, 0.8524657934904099]


def test_customers_match_the_frontend() -> None:
    assert build_seed().customers == FRONTEND["customers"]


def test_invoices_and_lines_match_the_frontend() -> None:
    data = build_seed()
    lines_by_invoice: dict[Any, list[dict[str, object]]] = {}
    for line in data.lines:
        lines_by_invoice.setdefault(line["invoice_id"], []).append(line)
    ours = [
        {
            **invoice,
            "date": str(invoice["date"]),
            "deadline": str(invoice["deadline"]),
            "invoice_lines": lines_by_invoice[invoice["id"]],
        }
        for invoice in data.invoices
    ]
    assert ours == FRONTEND["invoices"]


def test_product_prices_match_the_frontend() -> None:
    for ours, theirs in zip(build_seed().products, FRONTEND["products"], strict=True):
        tax, price = product_prices(str(ours["unit_price_without_tax"]), str(ours["vat_rate"]))
        assert (ours["id"], ours["label"], ours["unit"]) == (
            theirs["id"],
            theirs["label"],
            theirs["unit"],
        )
        assert (tax, price) == (theirs["unit_tax"], theirs["unit_price"])


def test_database_computes_the_same_prices(db: Session) -> None:
    """PostgreSQL's generated columns round exactly like the frontend."""
    products = db.scalars(select(Product).order_by(Product.id)).all()
    for product, theirs in zip(products, FRONTEND["products"], strict=True):
        assert vat_rate(product.vat_rate) == theirs["vat_rate"]
        assert money(product.unit_price_without_tax) == theirs["unit_price_without_tax"]
        assert money(product.unit_tax) == theirs["unit_tax"]
        assert money(product.unit_price) == theirs["unit_price"]
