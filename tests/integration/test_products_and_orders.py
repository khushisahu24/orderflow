"""Products, stock, order totals, status changes, and database checks."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.support import admin_auth, auth, create_customer, create_product

pytestmark = pytest.mark.integration


def _stock(client, product_id: int) -> int:
    with client.app.state.engine.connect() as connection:
        return connection.execute(
            text("SELECT stock_quantity FROM products WHERE id = :id"),
            {"id": product_id},
        ).scalar_one()


def _movement_sum(client, product_id: int) -> int:
    with client.app.state.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT COALESCE(SUM(quantity_change), 0) "
                "FROM inventory_movements WHERE product_id = :id"
            ),
            {"id": product_id},
        ).scalar_one()


def test_product_rules_and_listing(client):
    rejected = client.post(
        "/products",
        headers=admin_auth(client),
        json={"sku": "bad", "name": "Mug", "price": "0", "stock_quantity": 1},
    )
    assert rejected.status_code == 422, rejected.text

    staff_attempt = client.post(
        "/products",
        headers=auth(client),
        json={"sku": "MUG-1", "name": "Mug", "price": "10.00", "stock_quantity": 1},
    )
    assert staff_attempt.status_code == 403

    first = create_product(client, sku="mug-1", price="12.50", stock=4)
    assert first["sku"] == "MUG-1"
    assert first["price"] == "12.50"
    duplicate = client.post(
        "/products",
        headers=admin_auth(client),
        json={"sku": "MUG-1", "name": "Other", "price": "5.00", "stock_quantity": 1},
    )
    assert duplicate.status_code == 409

    below_zero = client.post(
        f"/products/{first['id']}/stock-adjustments",
        headers=admin_auth(client),
        json={"quantity_change": -5},
    )
    assert below_zero.status_code == 409
    assert _stock(client, first["id"]) == 4

    adjusted = client.post(
        f"/products/{first['id']}/stock-adjustments",
        headers=admin_auth(client),
        json={"quantity_change": -1, "note": "damaged"},
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["stock_quantity"] == 3
    assert _stock(client, first["id"]) == _movement_sum(client, first["id"])

    create_product(client, sku="CUP-2", name="Blue cup", price="4.00", stock=0)
    listed = client.get(
        "/products?q=cup&sort_by=price&sort_order=asc&in_stock=false",
        headers=auth(client),
    )
    assert listed.status_code == 200, listed.text
    assert [item["sku"] for item in listed.json()["items"]] == ["CUP-2"]


def test_order_total_stock_and_cancellation_match_the_database(client):
    customer = create_customer(client)
    mug = create_product(client, sku="MUG-1", price="10.00", stock=5)
    cup = create_product(client, sku="CUP-2", price="3.50", stock=5)

    created = client.post(
        "/orders",
        headers=auth(client),
        json={
            "customer_id": customer["id"],
            "items": [
                {"product_id": mug["id"], "quantity": 2},
                {"product_id": cup["id"], "quantity": 1},
            ],
        },
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "pending"
    assert Decimal(order["total_amount"]) == Decimal("23.50")
    prices = {item["product_id"]: item["unit_price"] for item in order["items"]}
    assert prices[mug["id"]] == "10.00"

    assert _stock(client, mug["id"]) == 3
    assert _stock(client, mug["id"]) == _movement_sum(client, mug["id"])

    client.patch(
        f"/products/{mug['id']}",
        headers=admin_auth(client),
        json={"price": "99.00"},
    )
    reread = client.get(f"/orders/{order['id']}", headers=auth(client))
    stored_price = next(
        item["unit_price"] for item in reread.json()["items"] if item["product_id"] == mug["id"]
    )
    assert stored_price == "10.00"

    too_many = client.post(
        "/orders",
        headers=auth(client),
        json={"customer_id": customer["id"], "items": [{"product_id": mug["id"], "quantity": 4}]},
    )
    assert too_many.status_code == 409, too_many.text
    assert _stock(client, mug["id"]) == 3

    skipped = client.patch(
        f"/orders/{order['id']}/status",
        headers=auth(client),
        json={"status": "delivered"},
    )
    assert skipped.status_code == 409

    for target in ("confirmed", "shipped", "delivered"):
        step = client.patch(
            f"/orders/{order['id']}/status",
            headers=auth(client),
            json={"status": target},
        )
        assert step.status_code == 200, step.text
        assert step.json()["status"] == target

    second = client.post(
        "/orders",
        headers=auth(client),
        json={"customer_id": customer["id"], "items": [{"product_id": mug["id"], "quantity": 1}]},
    )
    assert second.status_code == 201, second.text
    cancelled = client.patch(
        f"/orders/{second.json()['id']}/status",
        headers=auth(client),
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert _stock(client, mug["id"]) == 3
    assert _stock(client, mug["id"]) == _movement_sum(client, mug["id"])


def test_rejected_order_does_not_leave_rows(client):
    customer = create_customer(client)
    missing = client.post(
        "/orders",
        headers=auth(client),
        json={"customer_id": customer["id"], "items": [{"product_id": 999, "quantity": 1}]},
    )
    assert missing.status_code == 422, missing.text
    with client.app.state.engine.connect() as connection:
        orders = connection.execute(text("SELECT count(*) FROM orders")).scalar()
        items = connection.execute(text("SELECT count(*) FROM order_items")).scalar()
    assert orders == 0
    assert items == 0


def test_same_idempotency_key_returns_the_original_order(client):
    customer = create_customer(client)
    product = create_product(client, stock=5)
    payload = {
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 1}],
    }
    headers = {**auth(client), "Idempotency-Key": "order-try-1"}
    first = client.post("/orders", headers=headers, json=payload)
    second = client.post("/orders", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.headers["idempotent-replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]
    assert _stock(client, product["id"]) == 4

    changed = client.post(
        "/orders",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 2}],
        },
    )
    assert changed.status_code == 409
