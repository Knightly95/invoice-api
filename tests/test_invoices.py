"""Invoice listing (filters, sorting, pages) and the editing rules."""

import itertools
import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

Headers = dict[str, str]


def list_invoices(client: TestClient, headers: Headers, **params: Any) -> dict[str, Any]:
    if "filter" in params and not isinstance(params["filter"], str):
        params["filter"] = json.dumps(params["filter"])
    response = client.get("/invoices", params=params, headers=headers)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def all_invoices(client: TestClient, headers: Headers, **params: Any) -> list[dict[str, Any]]:
    invoices: list[dict[str, Any]] = list_invoices(client, headers, per_page=100, **params)[
        "invoices"
    ]
    return invoices


def create(client: TestClient, headers: Headers, **invoice: Any) -> dict[str, Any]:
    response = client.post("/invoices", json={"invoice": invoice}, headers=headers)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


def update(client: TestClient, headers: Headers, invoice_id: int, **invoice: Any) -> Any:
    return client.put(f"/invoices/{invoice_id}", json={"invoice": invoice}, headers=headers)


# ── Listing ───────────────────────────────────────────────────────────────


def test_lists_newest_first_with_pages(client: TestClient, viewer: Headers) -> None:
    body = list_invoices(client, viewer, page=2, per_page=25)
    assert body["pagination"] == {
        "page": 2,
        "page_size": 25,
        "total_pages": 3,
        "total_entries": 60,
    }
    assert [invoice["id"] for invoice in body["invoices"]] == list(range(35, 10, -1))


def test_clamps_page_size_and_page(client: TestClient, viewer: Headers) -> None:
    body = list_invoices(client, viewer, page=0, per_page=500)
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 100
    assert len(body["invoices"]) == 60


def test_a_page_past_the_end_is_empty(client: TestClient, viewer: Headers) -> None:
    body = list_invoices(client, viewer, page=9)
    assert body["invoices"] == []
    assert body["pagination"]["total_entries"] == 60


@pytest.mark.parametrize(
    ("clause", "check"),
    [
        ({"field": "paid", "operator": "eq", "value": True}, lambda i: i["paid"]),
        ({"field": "finalized", "operator": "eq", "value": False}, lambda i: not i["finalized"]),
        (
            {"field": "customer_id", "operator": "not_eq", "value": 5},
            lambda i: i["customer_id"] != 5,
        ),
        ({"field": "id", "operator": "gt", "value": 50}, lambda i: i["id"] > 50),
        ({"field": "id", "operator": "lteq", "value": "3"}, lambda i: i["id"] <= 3),
        (
            {"field": "customer_id", "operator": "in", "value": [1, 2, 3]},
            lambda i: i["customer_id"] in (1, 2, 3),
        ),
        ({"field": "id", "operator": "not_in", "value": [1, 2]}, lambda i: i["id"] not in (1, 2)),
        (
            {"field": "deadline", "operator": "lt", "value": "2025-06-01"},
            lambda i: i["deadline"] < "2025-06-01",
        ),
        (
            {"field": "total", "operator": "gteq", "value": "5000"},
            lambda i: Decimal(i["total"]) >= 5000,
        ),
        ({"field": "tax", "operator": "lt", "value": 100}, lambda i: Decimal(i["tax"]) < 100),
    ],
)
def test_filters(client: TestClient, viewer: Headers, clause: dict[str, Any], check: Any) -> None:
    matches = all_invoices(client, viewer, filter=[clause])
    everything = all_invoices(client, viewer)
    assert matches, "the seed should have matching invoices"
    assert all(check(invoice) for invoice in matches)
    assert len(matches) == sum(1 for invoice in everything if check(invoice))


def test_filters_combine_with_and(client: TestClient, viewer: Headers) -> None:
    clauses = [
        {"field": "finalized", "operator": "eq", "value": True},
        {"field": "paid", "operator": "eq", "value": False},
    ]
    matches = all_invoices(client, viewer, filter=clauses)
    assert matches
    assert all(invoice["finalized"] and not invoice["paid"] for invoice in matches)


def test_eq_null_finds_invoices_without_a_customer(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1)
    update(client, accountant, invoice["id"], customer_id=None)
    matches = all_invoices(
        client, accountant, filter=[{"field": "customer_id", "operator": "eq", "value": None}]
    )
    assert [match["id"] for match in matches] == [invoice["id"]]
    others = all_invoices(
        client, accountant, filter=[{"field": "customer_id", "operator": "not_eq", "value": 1}]
    )
    assert invoice["id"] in [other["id"] for other in others]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "must be a JSON array"),
        ('{"field": "paid"}', "must be a JSON array"),
        ('[{"field": "secret", "operator": "eq", "value": 1}]', 'Unknown field "secret"'),
        (
            '[{"field": "paid", "operator": "like", "value": true}]',
            'Unsupported filter operator "like"',
        ),
        (
            '[{"field": "date", "operator": "eq", "value": "yesterday"}]',
            'Invalid value "yesterday"',
        ),
        ('[{"field": "paid", "operator": "eq", "value": "yes"}]', 'Invalid value "yes"'),
        ('[{"field": "id", "operator": "in", "value": 3}]', "needs a list"),
        ("[42]", "must be an object"),
    ],
)
def test_rejects_bad_filters(client: TestClient, viewer: Headers, raw: str, message: str) -> None:
    response = client.get("/invoices", params={"filter": raw}, headers=viewer)
    assert response.status_code == 400
    assert message in response.json()["message"]


def test_sorts_by_computed_total_across_pages(client: TestClient, viewer: Headers) -> None:
    """The database sorts by the totals it returns, so pages follow on (the
    frontend's issue BI-2 cannot happen here)."""
    totals: list[Decimal] = []
    for page in (1, 2, 3):
        body = list_invoices(client, viewer, sort="-total", page=page, per_page=25)
        totals += [Decimal(invoice["total"]) for invoice in body["invoices"]]
    assert len(totals) == 60
    assert totals == sorted(totals, reverse=True)


def test_sorts_by_several_fields(client: TestClient, viewer: Headers) -> None:
    invoices = all_invoices(client, viewer, sort="+paid,-deadline")
    for before, after in itertools.pairwise(invoices):
        assert before["paid"] <= after["paid"]
        if before["paid"] == after["paid"]:
            assert before["deadline"] >= after["deadline"]


def test_empty_values_sort_last(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1, deadline=None)
    for sort in ("+deadline", "-deadline"):
        assert all_invoices(client, accountant, sort=sort)[-1]["id"] == invoice["id"]


def test_rejects_sorting_on_unknown_fields(client: TestClient, viewer: Headers) -> None:
    response = client.get("/invoices", params={"sort": "-password"}, headers=viewer)
    assert response.status_code == 400


# ── Reading one ───────────────────────────────────────────────────────────


def test_line_prices_and_totals_add_up(client: TestClient, viewer: Headers) -> None:
    invoice = client.get("/invoices/1", headers=viewer).json()
    lines = invoice["invoice_lines"]
    assert [line["id"] for line in lines] == sorted(line["id"] for line in lines)
    for line in lines:
        assert Decimal(line["price"]) == Decimal(line["product"]["unit_price"]) * line["quantity"]
        assert line["label"] == line["product"]["label"]
    assert Decimal(invoice["total"]) == sum(Decimal(line["price"]) for line in lines)
    assert Decimal(invoice["tax"]) == sum(Decimal(line["tax"]) for line in lines)
    assert invoice["customer"]["id"] == invoice["customer_id"]


def test_unknown_invoice_is_404(client: TestClient, viewer: Headers) -> None:
    response = client.get("/invoices/9999", headers=viewer)
    assert response.status_code == 404
    assert response.json() == {"message": "Invoice 9999 not found"}


# ── Creating ──────────────────────────────────────────────────────────────


def test_creates_a_draft_with_lines(client: TestClient, accountant: Headers) -> None:
    invoice = create(
        client,
        accountant,
        customer_id=4,
        date="2026-11-20",
        deadline="2026-12-20",
        invoice_lines_attributes=[{"product_id": 2, "quantity": 3}, {"product_id": 9}],
    )
    assert invoice["id"] > 60
    assert (invoice["finalized"], invoice["paid"]) == (False, False)
    assert [(line["product_id"], line["quantity"]) for line in invoice["invoice_lines"]] == [
        (2, 3),
        (9, 1),
    ]
    # Frontend development 600.00 + 20% = 720.00 x 3, laptop stand 39.90 + 7.98 = 47.88
    assert invoice["total"] == "2207.88"
    assert invoice["tax"] == "367.98"
    assert client.get(f"/invoices/{invoice['id']}", headers=accountant).json() == invoice


def test_creates_a_finalized_and_paid_invoice(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1, finalized=True, paid=True)
    assert (invoice["finalized"], invoice["paid"]) == (True, True)


@pytest.mark.parametrize(
    ("invoice", "message"),
    [
        ({}, "customer_id is required"),
        ({"customer_id": 999}, "Customer 999 does not exist"),
        ({"customer_id": 1, "paid": True}, "Only a finalized invoice can be marked as paid"),
        (
            {"customer_id": 1, "invoice_lines_attributes": [{"product_id": 999}]},
            "Product 999 does not exist",
        ),
        (
            {"customer_id": 1, "invoice_lines_attributes": [{"quantity": 2}]},
            "product_id is required",
        ),
        (
            {"customer_id": 1, "invoice_lines_attributes": [{"product_id": 1, "quantity": 0}]},
            "quantity",
        ),
        ({"customer_id": 1, "date": "20/11/2026"}, "date"),
    ],
)
def test_create_rejects(
    client: TestClient, accountant: Headers, invoice: dict[str, Any], message: str
) -> None:
    response = client.post("/invoices", json={"invoice": invoice}, headers=accountant)
    assert response.status_code == 422
    assert message in response.json()["message"]


def test_a_rejected_create_leaves_nothing_behind(client: TestClient, accountant: Headers) -> None:
    lines = [{"product_id": 1}, {"product_id": 999}]
    client.post(
        "/invoices",
        json={"invoice": {"customer_id": 1, "invoice_lines_attributes": lines}},
        headers=accountant,
    )
    assert list_invoices(client, accountant)["pagination"]["total_entries"] == 60


# ── Updating ──────────────────────────────────────────────────────────────


def test_updates_fields_and_lines(client: TestClient, accountant: Headers) -> None:
    invoice = create(
        client,
        accountant,
        customer_id=1,
        invoice_lines_attributes=[{"product_id": 1}, {"product_id": 2}, {"product_id": 3}],
    )
    first, second, third = (line["id"] for line in invoice["invoice_lines"])
    response = update(
        client,
        accountant,
        invoice["id"],
        customer_id=2,
        deadline="2027-01-31",
        invoice_lines_attributes=[
            {"id": first, "quantity": 5},
            {"id": second, "_destroy": True},
            {"id": third, "product_id": 4},
            {"product_id": 5, "quantity": 2},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["customer_id"], body["deadline"], body["date"]) == (2, "2027-01-31", None)
    assert [(line["product_id"], line["quantity"]) for line in body["invoice_lines"]] == [
        (1, 5),
        (4, 1),
        (5, 2),
    ]


def test_changing_a_product_recomputes_prices(client: TestClient, accountant: Headers) -> None:
    """The frontend's issue BI-1 (stale totals after a product swap) can't happen."""
    invoice = create(
        client, accountant, customer_id=1, invoice_lines_attributes=[{"product_id": 1}]
    )
    line_id = invoice["invoice_lines"][0]["id"]
    body = update(
        client,
        accountant,
        invoice["id"],
        invoice_lines_attributes=[{"id": line_id, "product_id": 7}],
    ).json()
    assert body["invoice_lines"][0]["price"] == "1440.00"
    assert body["total"] == "1440.00"
    assert body["tax"] == "240.00"


def test_fields_left_out_stay_as_they_are(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1, date="2026-01-01")
    body = update(client, accountant, invoice["id"], deadline="2026-02-01").json()
    assert (body["customer_id"], body["date"]) == (1, "2026-01-01")


def test_a_finalized_invoice_can_only_be_marked_paid(
    client: TestClient, accountant: Headers
) -> None:
    invoice = create(client, accountant, customer_id=1, finalized=True)
    for change in ({"customer_id": 2}, {"finalized": False}, {"date": "2026-01-01"}):
        response = update(client, accountant, invoice["id"], **change)
        assert response.status_code == 422
        assert response.json() == {"message": "A finalized invoice can only be marked as paid"}
    paid = update(client, accountant, invoice["id"], id=invoice["id"], paid=True)
    assert paid.status_code == 200
    assert paid.json()["paid"] is True


def test_a_draft_cannot_be_paid(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1)
    response = update(client, accountant, invoice["id"], paid=True)
    assert response.status_code == 422
    finalized = update(client, accountant, invoice["id"], finalized=True, paid=True)
    assert finalized.json()["paid"] is True


def test_cannot_change_another_invoices_line(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1)
    response = update(
        client, accountant, invoice["id"], invoice_lines_attributes=[{"id": 1, "quantity": 9}]
    )
    assert response.status_code == 422
    assert response.json() == {"message": "Invoice line 1 not found"}


def test_a_rejected_update_changes_nothing(client: TestClient, accountant: Headers) -> None:
    invoice = create(
        client, accountant, customer_id=1, invoice_lines_attributes=[{"product_id": 1}]
    )
    line_id = invoice["invoice_lines"][0]["id"]
    response = update(
        client,
        accountant,
        invoice["id"],
        customer_id=2,
        invoice_lines_attributes=[{"id": line_id, "quantity": 4}, {"product_id": 999}],
    )
    assert response.status_code == 422
    assert client.get(f"/invoices/{invoice['id']}", headers=accountant).json() == invoice


def test_updating_a_missing_invoice_is_404(client: TestClient, accountant: Headers) -> None:
    assert update(client, accountant, 9999, paid=True).status_code == 404


# ── Deleting ──────────────────────────────────────────────────────────────


def test_deletes_a_draft_and_its_lines(client: TestClient, accountant: Headers) -> None:
    invoice = create(
        client, accountant, customer_id=1, invoice_lines_attributes=[{"product_id": 1}]
    )
    response = client.delete(f"/invoices/{invoice['id']}", headers=accountant)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/invoices/{invoice['id']}", headers=accountant).status_code == 404


def test_a_finalized_invoice_cannot_be_deleted(client: TestClient, accountant: Headers) -> None:
    invoice = create(client, accountant, customer_id=1, finalized=True)
    response = client.delete(f"/invoices/{invoice['id']}", headers=accountant)
    assert response.status_code == 422
    assert response.json() == {"message": "A finalized invoice cannot be deleted"}


def test_deleting_a_missing_invoice_is_404(client: TestClient, accountant: Headers) -> None:
    assert client.delete("/invoices/9999", headers=accountant).status_code == 404


def test_a_page_of_invoices_takes_three_queries(
    client: TestClient, viewer: Headers, db: Session
) -> None:
    """Count, invoices with customers, lines with products: no query per row."""
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        body = list_invoices(client, viewer, per_page=25)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert sum(len(invoice["invoice_lines"]) for invoice in body["invoices"]) > 25
    selects = [statement for statement in statements if statement.lstrip().startswith("SELECT")]
    assert len(selects) == 3, "\n\n".join(selects)
