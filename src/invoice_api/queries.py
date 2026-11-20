"""Turns the list parameters (`filter`, `sort`, `page`, `per_page`, `query`)
into SQL. Everything happens in the database: filtering, sorting by the
computed totals, and paging, so page 2 is always what follows page 1.
"""

import datetime as dt
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from invoice_api.errors import BadRequestError
from invoice_api.models import Invoice, InvoiceLine, Product
from invoice_api.schemas import Pagination

DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100

# Each invoice's total and tax, summed from its lines at the current prices.
# Invoices without lines have no row here, hence the COALESCE below.
_line_totals = (
    select(
        InvoiceLine.invoice_id,
        func.sum(InvoiceLine.quantity * Product.unit_price).label("total"),
        func.sum(InvoiceLine.quantity * Product.unit_tax).label("tax"),
    )
    .join(Product, Product.id == InvoiceLine.product_id)
    .group_by(InvoiceLine.invoice_id)
    .subquery("line_totals")
)
INVOICE_TOTAL = func.coalesce(_line_totals.c.total, 0)
INVOICE_TAX = func.coalesce(_line_totals.c.tax, 0)


def invoices_with_totals() -> Select[Invoice]:
    """`SELECT invoices ... LEFT JOIN line_totals`, ready to filter and sort."""
    return select(Invoice).outerjoin(_line_totals, _line_totals.c.invoice_id == Invoice.id)


# ── Filtering and sorting ─────────────────────────────────────────────────


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError


def _parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        return value
    if isinstance(value, str | float) and float(value).is_integer():
        return int(float(value))
    raise ValueError


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError from error


def _parse_date(value: Any) -> dt.date:
    return dt.date.fromisoformat(value)


@dataclass(frozen=True)
class Field:
    column: ColumnElement[Any] | InstrumentedAttribute[Any]
    parse: Callable[[Any], Any]


# The only fields clients may filter and sort on, and how to read their values.
INVOICE_FIELDS: dict[str, Field] = {
    "id": Field(Invoice.id, _parse_int),
    "customer_id": Field(Invoice.customer_id, _parse_int),
    "finalized": Field(Invoice.finalized, _parse_bool),
    "paid": Field(Invoice.paid, _parse_bool),
    "date": Field(Invoice.date, _parse_date),
    "deadline": Field(Invoice.deadline, _parse_date),
    "total": Field(INVOICE_TOTAL, _parse_decimal),
    "tax": Field(INVOICE_TAX, _parse_decimal),
}


def _field(name: Any) -> Field:
    if not isinstance(name, str) or name not in INVOICE_FIELDS:
        allowed = ", ".join(INVOICE_FIELDS)
        raise BadRequestError(f'Unknown field "{name}". Use one of: {allowed}')
    return INVOICE_FIELDS[name]


def _value(field: Field, name: str, raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return field.parse(raw)
    except (TypeError, ValueError) as error:
        raise BadRequestError(f'Invalid value {json.dumps(raw)} for "{name}"') from error


def _condition(clause: Any) -> ColumnElement[bool]:
    if not isinstance(clause, dict):
        raise BadRequestError("Each filter must be an object with field, operator and value")
    name, operator, raw = str(clause.get("field")), clause.get("operator"), clause.get("value")
    field = _field(name)
    column = field.column

    if operator in ("in", "not_in"):
        if not isinstance(raw, list):
            raise BadRequestError(f'"{operator}" needs a list of values')
        values = [_value(field, name, item) for item in raw]
        return column.in_(values) if operator == "in" else column.not_in(values)

    value = _value(field, name, raw)
    condition: ColumnElement[bool]
    match operator:
        # IS (NOT) DISTINCT FROM treats NULL as a value, so "customer is not 5"
        # also matches invoices without a customer.
        case "eq":
            condition = column.is_not_distinct_from(value)
        case "not_eq":
            condition = column.is_distinct_from(value)
        case "gt":
            condition = column > value
        case "gteq":
            condition = column >= value
        case "lt":
            condition = column < value
        case "lteq":
            condition = column <= value
        case _:
            raise BadRequestError(f'Unsupported filter operator "{operator}"')
    return condition


def parse_filter(raw: str | None) -> list[ColumnElement[bool]]:
    """`[{"field": "paid", "operator": "eq", "value": true}, ...]`: all must match."""
    if not raw:
        return []
    try:
        clauses = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BadRequestError("Invalid filter parameter: it must be a JSON array") from error
    if not isinstance(clauses, list):
        raise BadRequestError("Invalid filter parameter: it must be a JSON array")
    return [_condition(clause) for clause in clauses]


def parse_sort(raw: str | None) -> list[ColumnElement[Any]]:
    """`+deadline,-total`. Empty values sort last; ties keep id order."""
    if not raw or not raw.strip():
        return [Invoice.id.desc()]
    order: list[ColumnElement[Any]] = []
    for part in (piece.strip() for piece in raw.split(",")):
        if not part:
            continue
        descending = part.startswith("-")
        column = _field(part.lstrip("+-")).column
        order.append((column.desc() if descending else column.asc()).nulls_last())
    order.append(Invoice.id.asc())
    return order


# ── Pages ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageRequest:
    page: int
    per_page: int

    @classmethod
    def of(cls, page: int | None, per_page: int | None) -> "PageRequest":
        """Out-of-range values are clamped, not rejected."""
        return cls(
            page=max(1, page or 1),
            per_page=min(MAX_PER_PAGE, max(1, per_page or DEFAULT_PER_PAGE)),
        )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def pagination(self, total_entries: int) -> Pagination:
        return Pagination(
            page=self.page,
            page_size=self.per_page,
            total_pages=max(1, math.ceil(total_entries / self.per_page)),
            total_entries=total_entries,
        )


def count(session: Session, query: Select[Any]) -> int:
    """Number of rows the query returns, without fetching them."""
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return total or 0


def contains(text: str | None) -> str | None:
    """`dup` -> `%dup%` for ILIKE, with `%` and `_` in the search taken literally."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
