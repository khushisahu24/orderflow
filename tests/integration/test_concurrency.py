"""Two orders at the same time must not both take the last unit."""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.support import auth, create_customer, create_product

pytestmark = pytest.mark.integration


def test_only_one_order_gets_the_last_item(client):
    customer = create_customer(client)
    product = create_product(client, stock=1)
    headers = auth(client)
    payload = {
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 1}],
    }
    barrier = threading.Barrier(2)
    results: list[int] = []

    def place_order() -> None:
        local = TestClient(client.app)
        barrier.wait()
        response = local.post("/orders", headers=headers, json=payload)
        results.append(response.status_code)

    threads = [threading.Thread(target=place_order) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [201, 409], results
    with client.app.state.engine.connect() as connection:
        stock = connection.execute(
            text("SELECT stock_quantity FROM products WHERE id = :id"),
            {"id": product["id"]},
        ).scalar_one()
        orders = connection.execute(text("SELECT count(*) FROM orders")).scalar_one()
    assert stock == 0
    assert orders == 1
