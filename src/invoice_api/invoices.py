"""Invoice rules. The same rules as the frontend's in-browser mock API, so the
app behaves the same against either:

- a finalized invoice can only be marked as paid;
- only a finalized invoice can be paid;
- a finalized invoice can't be deleted;
- customers and products must exist, and a line can only be changed on its
  own invoice.

Each change runs in one transaction. Updates lock the invoice row first
(`SELECT ... FOR UPDATE`), so two people saving the same invoice at once
can't overwrite each other's lines.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.interfaces import LoaderOption

from invoice_api.errors import NotFoundError, UnprocessableError
from invoice_api.models import Customer, Invoice, InvoiceLine, Product
from invoice_api.schemas import InvoiceInput, InvoiceLineInput


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    """Commit the work done inside, or undo all of it if anything fails."""
    try:
        yield
        session.commit()
    except BaseException:
        session.rollback()
        raise


# Everything an invoice response needs, loaded in 3 queries instead of 1 per line.
FULL_INVOICE: list[LoaderOption] = [
    joinedload(Invoice.customer),
    selectinload(Invoice.lines).joinedload(InvoiceLine.product),
]

# Fields a finalized invoice still accepts.
_ALLOWED_WHEN_FINALIZED = {"paid", "finalized"}


def get_invoice(session: Session, invoice_id: int, *, for_update: bool = False) -> Invoice:
    query = select(Invoice).where(Invoice.id == invoice_id).options(*FULL_INVOICE)
    if for_update:
        # Lock only the invoice row, not the customer joined to it.
        query = query.with_for_update(of=Invoice)
    invoice = session.scalars(query).unique().one_or_none()
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    return invoice


def _check_rules(session: Session, invoice: Invoice, data: InvoiceInput) -> None:
    sent = data.model_fields_set
    if invoice.finalized and (sent - _ALLOWED_WHEN_FINALIZED or data.finalized is False):
        raise UnprocessableError("A finalized invoice can only be marked as paid")
    finalized = data.finalized if data.finalized is not None else invoice.finalized
    if data.paid and not finalized:
        raise UnprocessableError("Only a finalized invoice can be marked as paid")
    if data.customer_id is not None and session.get(Customer, data.customer_id) is None:
        raise UnprocessableError(f"Customer {data.customer_id} does not exist")


def _product(session: Session, product_id: int | None) -> Product:
    if product_id is None:
        raise UnprocessableError("product_id is required for a new invoice line")
    product = session.get(Product, product_id)
    if product is None:
        raise UnprocessableError(f"Product {product_id} does not exist")
    return product


def _apply_lines(session: Session, invoice: Invoice, changes: list[InvoiceLineInput]) -> None:
    for change in changes:
        if change.id is None:
            if not change.destroy:
                invoice.lines.append(
                    InvoiceLine(
                        product=_product(session, change.product_id),
                        quantity=change.quantity or 1,
                    )
                )
            continue

        line = next((line for line in invoice.lines if line.id == change.id), None)
        if line is None:
            raise UnprocessableError(f"Invoice line {change.id} not found")
        if change.destroy:
            invoice.lines.remove(line)
            continue
        if change.product_id is not None:
            line.product = _product(session, change.product_id)
        if change.quantity is not None:
            line.quantity = change.quantity


def _apply(session: Session, invoice: Invoice, data: InvoiceInput) -> None:
    _check_rules(session, invoice, data)
    sent = data.model_fields_set
    if "customer_id" in sent:
        invoice.customer_id = data.customer_id
    if data.finalized is not None:
        invoice.finalized = data.finalized
    if data.paid is not None:
        invoice.paid = data.paid
    if "date" in sent:
        invoice.date = data.date
    if "deadline" in sent:
        invoice.deadline = data.deadline
    _apply_lines(session, invoice, data.invoice_lines_attributes)


def create_invoice(session: Session, data: InvoiceInput) -> Invoice:
    if data.customer_id is None:
        raise UnprocessableError("customer_id is required")
    with transaction(session):
        # Start as an empty draft, then apply the request like an update, so a
        # new invoice passes exactly the same checks.
        invoice = Invoice(finalized=False, paid=False, lines=[])
        _apply(session, invoice, data)
        session.add(invoice)
    session.expire_all()
    return get_invoice(session, invoice.id)


def update_invoice(session: Session, invoice_id: int, data: InvoiceInput) -> Invoice:
    with transaction(session):
        invoice = get_invoice(session, invoice_id, for_update=True)
        _apply(session, invoice, data)
    session.expire_all()
    return get_invoice(session, invoice_id)


def delete_invoice(session: Session, invoice_id: int) -> None:
    with transaction(session):
        invoice = get_invoice(session, invoice_id, for_update=True)
        if invoice.finalized:
            raise UnprocessableError("A finalized invoice cannot be deleted")
        session.delete(invoice)
