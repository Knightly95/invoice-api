"""The FastAPI application: routes for the contract in `contract/schema.yml`."""

from typing import Annotated

from fastapi import Depends, FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import ColumnClause, Text, literal_column, or_, select, text
from sqlalchemy.orm import Session

from invoice_api import invoices
from invoice_api.auth import CanRead, CanWrite, issue_token
from invoice_api.config import get_settings
from invoice_api.db import get_session
from invoice_api.errors import register_error_handlers
from invoice_api.models import Customer, Product
from invoice_api.queries import (
    PageRequest,
    contains,
    count,
    invoices_with_totals,
    parse_filter,
    parse_sort,
)
from invoice_api.schemas import (
    CustomerOut,
    CustomerPage,
    InvoiceOut,
    InvoicePage,
    InvoiceRequest,
    ProductOut,
    ProductPage,
    SessionOut,
    SessionRequest,
)

DbSession = Annotated[Session, Depends(get_session)]
# A literal ' ' rather than a bound parameter, so the expression matches the index's.
SPACE: ColumnClause[str] = literal_column("' '", Text())
PageParam = Annotated[int | None, Query()]

app = FastAPI(
    title="Invoice API",
    version="1.0.0",
    description=(
        "Invoices, customers and products for the "
        "[Invoice Editor](https://knightly95.github.io/invoice-editor/). "
        "Get a token from `POST /sessions`, then send it in the `X-SESSION` header."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-SESSION"],
)
register_error_handlers(app)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", tags=["service"])
def health(session: DbSession) -> dict[str, str]:
    """Liveness check for the host; also proves the database answers."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/sessions", tags=["sessions"])
def create_session(body: SessionRequest) -> SessionOut:
    """Demo sign-in: a token for the chosen role, valid for a few hours."""
    return issue_token(body.role)


@app.get("/products/search", tags=["products"])
def search_products(
    session: DbSession,
    _: CanRead,
    query: str | None = None,
    page: PageParam = None,
    per_page: PageParam = None,
) -> ProductPage:
    request = PageRequest.of(page, per_page)
    statement = select(Product)
    if pattern := contains(query):
        statement = statement.where(Product.label.ilike(pattern))
    total = count(session, statement)
    rows = session.scalars(
        statement.order_by(Product.id).offset(request.offset).limit(request.per_page)
    )
    return ProductPage(
        pagination=request.pagination(total),
        products=[ProductOut.of(product) for product in rows],
    )


@app.get("/customers/search", tags=["customers"])
def search_customers(
    session: DbSession,
    _: CanRead,
    query: str | None = None,
    page: PageParam = None,
    per_page: PageParam = None,
) -> CustomerPage:
    request = PageRequest.of(page, per_page)
    statement = select(Customer)
    if pattern := contains(query):
        # Matches "Camille Dupont" and "Dupont Camille" alike. The expressions
        # are the same as the trigram indexes', so the planner can use them.
        statement = statement.where(
            or_(
                (Customer.first_name + SPACE + Customer.last_name).ilike(pattern),
                (Customer.last_name + SPACE + Customer.first_name).ilike(pattern),
            )
        )
    total = count(session, statement)
    rows = session.scalars(
        statement.order_by(Customer.id).offset(request.offset).limit(request.per_page)
    )
    return CustomerPage(
        pagination=request.pagination(total),
        customers=[CustomerOut.model_validate(customer) for customer in rows],
    )


@app.get("/invoices", tags=["invoices"])
def list_invoices(
    session: DbSession,
    _: CanRead,
    page: PageParam = None,
    per_page: PageParam = None,
    filter: str | None = None,  # the contract's name, although it shadows a builtin
    sort: str | None = None,
) -> InvoicePage:
    request = PageRequest.of(page, per_page)
    statement = invoices_with_totals().where(*parse_filter(filter))
    total = count(session, statement)
    rows = session.scalars(
        statement.order_by(*parse_sort(sort))
        .offset(request.offset)
        .limit(request.per_page)
        .options(*invoices.FULL_INVOICE)
    ).unique()
    return InvoicePage(
        pagination=request.pagination(total),
        invoices=[InvoiceOut.of(invoice) for invoice in rows],
    )


@app.post("/invoices", tags=["invoices"])
def create_invoice(session: DbSession, _: CanWrite, body: InvoiceRequest) -> InvoiceOut:
    # 200, not 201: the frontend's contract says so.
    return InvoiceOut.of(invoices.create_invoice(session, body.invoice))


@app.get("/invoices/{invoice_id}", tags=["invoices"])
def get_invoice(session: DbSession, _: CanRead, invoice_id: int) -> InvoiceOut:
    return InvoiceOut.of(invoices.get_invoice(session, invoice_id))


@app.put("/invoices/{invoice_id}", tags=["invoices"])
def update_invoice(
    session: DbSession, _: CanWrite, invoice_id: int, body: InvoiceRequest
) -> InvoiceOut:
    return InvoiceOut.of(invoices.update_invoice(session, invoice_id, body.invoice))


@app.delete("/invoices/{invoice_id}", status_code=204, tags=["invoices"])
def delete_invoice(session: DbSession, _: CanWrite, invoice_id: int) -> Response:
    invoices.delete_invoice(session, invoice_id)
    return Response(status_code=204)
