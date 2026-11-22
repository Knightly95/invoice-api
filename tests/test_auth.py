"""Sessions and roles: viewers read, accountants also write."""

import datetime as dt

import jwt
import pytest
from fastapi.testclient import TestClient

from invoice_api.auth import issue_token
from invoice_api.config import Settings
from invoice_api.schemas import Role

Headers = dict[str, str]


def test_sessions_hand_out_a_token_for_a_role(client: TestClient) -> None:
    response = client.post("/sessions", json={"role": "viewer"})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "viewer"
    reads = client.get("/invoices/1", headers={"X-SESSION": body["token"]})
    assert reads.status_code == 200


def test_unknown_roles_are_rejected(client: TestClient) -> None:
    response = client.post("/sessions", json={"role": "admin"})
    assert response.status_code == 422
    assert response.json()["message"].startswith("role:")


@pytest.mark.parametrize(
    "path", ["/invoices", "/invoices/1", "/products/search", "/customers/search"]
)
def test_reading_needs_a_session(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert "X-SESSION" in response.json()["message"]


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        jwt.encode(
            {"role": "accountant", "aud": "invoice-api"}, "wrong-secret-wrong-secret-wrong-secret"
        ),
    ],
)
def test_invalid_tokens_are_rejected(client: TestClient, token: str) -> None:
    response = client.get("/invoices", headers={"X-SESSION": token})
    assert response.status_code == 401
    assert response.json() == {"message": "Invalid session"}


def test_expired_tokens_are_rejected(client: TestClient) -> None:
    old = issue_token(Role.ACCOUNTANT, now=dt.datetime.now(dt.UTC) - dt.timedelta(days=2))
    response = client.get("/invoices", headers={"X-SESSION": old.token})
    assert response.status_code == 401
    assert "expired" in response.json()["message"]


def test_viewers_cannot_change_invoices(client: TestClient, viewer: Headers) -> None:
    attempts = [
        client.post("/invoices", json={"invoice": {"customer_id": 1}}, headers=viewer),
        client.put("/invoices/1", json={"invoice": {"date": None}}, headers=viewer),
        client.delete("/invoices/1", headers=viewer),
    ]
    for response in attempts:
        assert response.status_code == 403
        assert response.json() == {"message": "Only an accountant can change invoices"}
    assert client.get("/invoices/1", headers=viewer).json()["date"] is not None


def test_health_needs_no_session(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_root_points_to_the_docs(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_browsers_on_the_demo_site_may_call_the_api(client: TestClient) -> None:
    response = client.options(
        "/invoices",
        headers={
            "Origin": "https://knightly95.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-SESSION",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://knightly95.github.io"


def test_production_refuses_a_weak_secret() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production", secret_key="short")
    assert Settings(environment="production", secret_key="x" * 40).secret_key == "x" * 40


def test_host_database_urls_use_the_psycopg_driver() -> None:
    for url in ("postgres://u:p@host/db", "postgresql://u:p@host/db"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@host/db"
