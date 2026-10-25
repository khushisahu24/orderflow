"""One complete order, told in the order a caller would do it.

This is the end-to-end check: login, create data, place an order, move it
through its statuses, and confirm the database agrees.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.support import STAFF_EMAIL, admin_auth

pytestmark = pytest.mark.e2e


def test_a_customer_order_from_login_to_delivery(client):
    login = client.post(
        "/auth/login", json={"email": STAFF_EMAIL, "password": "local-password"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    customer = client.post(
        "/customers",
        headers=headers,
        json={"name": "Meera Shah", "email": "meera@example.com"},
    )
    assert customer.status_code == 201, customer.text

    product = client.post(
        "/products",
        headers=admin_auth(client),
        json={"sku": "BOOK-1", "name": "Notebook", "price": "8.00", "stock_quantity": 10},
    )
    assert product.status_code == 201, product.text

    order = client.post(
        "/orders",
        headers=headers,
        json={
            "customer_id": customer.json()["id"],
            "items": [{"product_id": product.json()["id"], "quantity": 3}],
        },
    )
    assert order.status_code == 201, order.text
    assert Decimal(order.json()["total_amount"]) == Decimal("24.00")

    current = order.json()
    for status in ("confirmed", "shipped", "delivered"):
        current = client.patch(
            f"/orders/{current['id']}/status",
            headers=headers,
            json={"status": status},
        )
        assert current.status_code == 200, current.text
        current = current.json()
    assert current["status"] == "delivered"

    with client.app.state.engine.connect() as connection:
        stock = connection.execute(
            text("SELECT stock_quantity FROM products WHERE sku = 'BOOK-1'")
        ).scalar_one()
        movement = connection.execute(
            text("SELECT SUM(quantity_change) FROM inventory_movements")
        ).scalar_one()
    assert stock == 7
    assert movement == 7
