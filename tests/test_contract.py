"""Every endpoint answers in the shape the frontend's contract describes."""

from fastapi.testclient import TestClient

from tests.contract import assert_matches_contract


def test_products_search(client: TestClient, viewer: dict[str, str]) -> None:
    response = client.get("/products/search", params={"query": "dev"}, headers=viewer)
    assert response.status_code == 200
    assert_matches_contract("get", "/products/search", response.json())


def test_customers_search(client: TestClient, viewer: dict[str, str]) -> None:
    response = client.get("/customers/search", params={"query": "a"}, headers=viewer)
    assert response.status_code == 200
    assert_matches_contract("get", "/customers/search", response.json())


def test_invoice_list(client: TestClient, viewer: dict[str, str]) -> None:
    response = client.get("/invoices", params={"per_page": 100}, headers=viewer)
    assert response.status_code == 200
    assert_matches_contract("get", "/invoices", response.json())


def test_invoice_get_create_and_update(client: TestClient, accountant: dict[str, str]) -> None:
    response = client.get("/invoices/1", headers=accountant)
    assert_matches_contract("get", "/invoices/{id}", response.json())

    created = client.post(
        "/invoices",
        json={"invoice": {"customer_id": 1, "invoice_lines_attributes": [{"product_id": 2}]}},
        headers=accountant,
    )
    assert created.status_code == 200
    assert_matches_contract("post", "/invoices", created.json())

    updated = client.put(
        f"/invoices/{created.json()['id']}",
        json={"invoice": {"id": created.json()["id"], "date": None}},
        headers=accountant,
    )
    assert updated.status_code == 200
    assert_matches_contract("put", "/invoices/{id}", updated.json())


def test_invoice_without_customer_or_dates(client: TestClient, accountant: dict[str, str]) -> None:
    """Nullable fields stay valid when empty."""
    created = client.post("/invoices", json={"invoice": {"customer_id": 3}}, headers=accountant)
    invoice_id = created.json()["id"]
    updated = client.put(
        f"/invoices/{invoice_id}",
        json={"invoice": {"customer_id": None, "date": None, "deadline": None}},
        headers=accountant,
    )
    body = updated.json()
    assert (body["customer_id"], body["total"]) == (None, "0.00")
    assert "customer" not in body
    assert_matches_contract("put", "/invoices/{id}", body)
