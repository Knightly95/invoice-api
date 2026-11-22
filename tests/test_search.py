"""Product and customer search, as the invoice form's search boxes use it."""

from fastapi.testclient import TestClient

Headers = dict[str, str]


def test_products_contain_the_text_in_any_case(client: TestClient, viewer: Headers) -> None:
    body = client.get("/products/search", params={"query": "DEVELOP"}, headers=viewer).json()
    assert [product["label"] for product in body["products"]] == [
        "Frontend development",
        "Backend development",
    ]
    assert body["pagination"]["total_entries"] == 2


def test_products_without_a_query_are_paged(client: TestClient, viewer: Headers) -> None:
    body = client.get("/products/search", params={"per_page": 10, "page": 3}, headers=viewer).json()
    assert [product["id"] for product in body["products"]] == [21, 22, 23, 24, 25]
    assert body["pagination"] == {
        "page": 3,
        "page_size": 10,
        "total_pages": 3,
        "total_entries": 25,
    }


def test_product_prices_are_strings_with_two_decimals(client: TestClient, viewer: Headers) -> None:
    body = client.get("/products/search", params={"query": "handbook"}, headers=viewer).json()
    assert body["products"] == [
        {
            "id": 14,
            "label": "Accounting handbook",
            "vat_rate": "5.5",
            "unit": "piece",
            "unit_price": "33.76",
            "unit_price_without_tax": "32.00",
            "unit_tax": "1.76",
        }
    ]


def test_percent_and_underscore_are_taken_literally(client: TestClient, viewer: Headers) -> None:
    for query in ("%", "_"):
        body = client.get("/products/search", params={"query": query}, headers=viewer).json()
        assert body["products"] == []


def test_customers_match_either_name_order(client: TestClient, viewer: Headers) -> None:
    first = client.get("/customers/search", params={"per_page": 1}, headers=viewer).json()
    customer = first["customers"][0]
    for query in (
        f"{customer['first_name']} {customer['last_name']}",
        f"{customer['last_name']} {customer['first_name']}",
        customer["last_name"].lower(),
    ):
        body = client.get("/customers/search", params={"query": query}, headers=viewer).json()
        assert customer in body["customers"], query


def test_blank_query_returns_everyone(client: TestClient, viewer: Headers) -> None:
    body = client.get("/customers/search", params={"query": "  "}, headers=viewer).json()
    assert body["pagination"]["total_entries"] == 40
