"""Request and response bodies, shaped exactly as the frontend's contract
(`contract/schema.yml`, copied from invoice-editor) describes them.

Money and VAT rates travel as strings ("1980.00", "5.5"), as in the contract,
so no precision is lost in JSON.
"""

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from invoice_api import models


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def vat_rate(value: Decimal) -> str:
    """5.5 -> "5.5", 20.0 -> "20", as the contract's enum spells them."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


# ── Responses ─────────────────────────────────────────────────────────────


class Pagination(BaseModel):
    page: int
    page_size: int
    total_pages: int
    total_entries: int


class ProductOut(BaseModel):
    id: int
    label: str
    vat_rate: str
    unit: str
    unit_price: str
    unit_price_without_tax: str
    unit_tax: str

    @classmethod
    def of(cls, product: models.Product) -> "ProductOut":
        return cls(
            id=product.id,
            label=product.label,
            vat_rate=vat_rate(product.vat_rate),
            unit=product.unit.value,
            unit_price=money(product.unit_price),
            unit_price_without_tax=money(product.unit_price_without_tax),
            unit_tax=money(product.unit_tax),
        )


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    address: str
    zip_code: str
    city: str
    country: str
    country_code: str


class InvoiceLineOut(BaseModel):
    id: int
    invoice_id: int
    product_id: int
    quantity: int
    label: str
    unit: str
    vat_rate: str
    price: str
    tax: str
    product: ProductOut


class InvoiceOut(BaseModel):
    id: int
    customer_id: int | None
    customer: CustomerOut | None
    finalized: bool
    paid: bool
    date: str | None
    deadline: str | None
    total: str
    tax: str
    invoice_lines: list[InvoiceLineOut]

    @model_serializer(mode="wrap")
    def _leave_out_missing_customer(self, handler: SerializerFunctionWrapHandler) -> Any:
        # The contract's `customer` is an object, never null: like the mock,
        # leave it out when the invoice has no customer.
        data = handler(self)
        if data.get("customer") is None:
            data.pop("customer", None)
        return data

    @classmethod
    def of(cls, invoice: models.Invoice) -> "InvoiceOut":
        """Line prices and totals come from the products' current prices."""
        lines = [
            InvoiceLineOut(
                id=line.id,
                invoice_id=line.invoice_id,
                product_id=line.product_id,
                quantity=line.quantity,
                label=line.product.label,
                unit=line.product.unit.value,
                vat_rate=vat_rate(line.product.vat_rate),
                price=money(line.product.unit_price * line.quantity),
                tax=money(line.product.unit_tax * line.quantity),
                product=ProductOut.of(line.product),
            )
            for line in invoice.lines
        ]
        return cls(
            id=invoice.id,
            customer_id=invoice.customer_id,
            customer=CustomerOut.model_validate(invoice.customer) if invoice.customer else None,
            finalized=invoice.finalized,
            paid=invoice.paid,
            date=iso(invoice.date),
            deadline=iso(invoice.deadline),
            total=money(sum((Decimal(line.price) for line in lines), Decimal(0))),
            tax=money(sum((Decimal(line.tax) for line in lines), Decimal(0))),
            invoice_lines=lines,
        )


class ProductPage(BaseModel):
    pagination: Pagination
    products: list[ProductOut]


class CustomerPage(BaseModel):
    pagination: Pagination
    customers: list[CustomerOut]


class InvoicePage(BaseModel):
    pagination: Pagination
    invoices: list[InvoiceOut]


# ── Requests ──────────────────────────────────────────────────────────────


class InvoiceLineInput(BaseModel):
    """With `id`: update that line, or delete it with `_destroy`. Without: a new line."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int | None = None
    destroy: bool = Field(default=False, alias="_destroy")
    product_id: int | None = None
    quantity: int | None = Field(default=None, ge=1)


class InvoiceInput(BaseModel):
    """Only the fields that are sent change; `model_fields_set` tells which."""

    model_config = ConfigDict(extra="ignore")

    customer_id: int | None = None
    finalized: bool | None = None
    paid: bool | None = None
    date: dt.date | None = None
    deadline: dt.date | None = None
    invoice_lines_attributes: list[InvoiceLineInput] = []


class InvoiceRequest(BaseModel):
    invoice: InvoiceInput = InvoiceInput()


# ── Sessions ──────────────────────────────────────────────────────────────


class Role(StrEnum):
    VIEWER = "viewer"
    ACCOUNTANT = "accountant"


class SessionRequest(BaseModel):
    role: Role


class SessionOut(BaseModel):
    token: str
    role: Role
    expires_at: dt.datetime
