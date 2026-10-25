"""Login, roles, and customer rules against PostgreSQL."""

import pytest
from sqlalchemy import text

from tests.support import ADMIN_EMAIL, STAFF_EMAIL, admin_auth, auth, create_customer

pytestmark = pytest.mark.integration


def test_health_is_public_and_ready_checks_the_database(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}


def test_missing_token_is_rejected(client):
    response = client.get("/customers")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated."


def test_wrong_password_is_rejected_without_a_token(client):
    response = client.post(
        "/auth/login",
        json={"email": STAFF_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_create_customer_trims_name_lowercases_email_and_matches_the_row(client):
    created = client.post(
        "/customers",
        headers=auth(client),
        json={"name": "  Asha Rao  ", "email": "Asha@Example.com"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Asha Rao"
    assert body["email"] == "asha@example.com"

    fetched = client.get(f"/customers/{body['id']}", headers=auth(client))
    assert fetched.status_code == 200
    assert fetched.json()["email"] == body["email"]

    with client.app.state.engine.connect() as connection:
        row = connection.execute(
            text("SELECT name, email FROM customers WHERE id = :id"),
            {"id": body["id"]},
        ).one()
    assert row.name == "Asha Rao"
    assert row.email == "asha@example.com"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Asha"},
        {"email": "asha@example.com"},
        {"name": "Asha", "email": "not-an-email"},
        {"name": "   ", "email": "asha@example.com"},
        {"name": "A" * 101, "email": "asha@example.com"},
        {"name": "Asha", "email": "asha@example.com", "role": "admin"},
    ],
)
def test_invalid_customer_is_rejected_and_not_stored(client, payload):
    response = client.post("/customers", headers=auth(client), json=payload)
    assert response.status_code == 422, response.text
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM customers")).scalar()
    assert count == 0


def test_duplicate_email_returns_409_and_keeps_one_row(client):
    create_customer(client, email="asha@example.com")
    duplicate = client.post(
        "/customers",
        headers=auth(client),
        json={"name": "Other", "email": "ASHA@example.com"},
    )
    assert duplicate.status_code == 409, duplicate.text
    with client.app.state.engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM customers")).scalar()
    assert count == 1


def test_sql_like_name_is_stored_as_text(client):
    hostile = "Robert'); DROP TABLE customers; --"
    created = create_customer(client, name=hostile, email="robert@example.com")
    assert created["name"] == hostile
    with client.app.state.engine.connect() as connection:
        still_there = connection.execute(text("SELECT count(*) FROM customers")).scalar()
    assert still_there == 1


def test_customer_list_is_paged(client):
    for index in range(3):
        create_customer(client, name=f"Person {index}", email=f"p{index}@example.com")
    page = client.get("/customers?limit=2&offset=0", headers=auth(client))
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == [1, 2]
    second = client.get("/customers?limit=2&offset=2", headers=auth(client))
    assert [item["id"] for item in second.json()["items"]] == [3]


def test_staff_cannot_delete_a_customer_and_admin_can_until_an_order_exists(client):
    customer = create_customer(client)
    product = client.post(
        "/products",
        headers=admin_auth(client),
        json={"sku": "MUG-1", "name": "Mug", "price": "10.00", "stock_quantity": 2},
    )
    assert product.status_code == 201, product.text

    forbidden = client.delete(f"/customers/{customer['id']}", headers=auth(client))
    assert forbidden.status_code == 403

    deleted = client.delete(f"/customers/{customer['id']}", headers=admin_auth(client))
    assert deleted.status_code == 204

    again = create_customer(client, email="second@example.com")
    ordered = client.post(
        "/orders",
        headers=auth(client),
        json={
            "customer_id": again["id"],
            "items": [{"product_id": product.json()["id"], "quantity": 1}],
        },
    )
    assert ordered.status_code == 201, ordered.text
    blocked = client.delete(f"/customers/{again['id']}", headers=admin_auth(client))
    assert blocked.status_code == 409

    me = client.get("/auth/me", headers=auth(client, ADMIN_EMAIL))
    assert me.json()["role"] == "admin"
