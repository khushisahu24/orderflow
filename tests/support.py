"""Small helpers so the tests read like the requests they send."""

from fastapi.testclient import TestClient

PASSWORD = "local-password"
ADMIN_EMAIL = "admin@orderflow.example"
STAFF_EMAIL = "staff@orderflow.example"


def token(client: TestClient, email: str = STAFF_EMAIL, password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(client: TestClient, email: str = STAFF_EMAIL) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(client, email)}"}


def admin_auth(client: TestClient) -> dict[str, str]:
    return auth(client, ADMIN_EMAIL)


def create_customer(
    client: TestClient, name: str = "Asha Rao", email: str = "asha@example.com"
) -> dict:
    response = client.post(
        "/customers",
        headers=auth(client),
        json={"name": name, "email": email},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_product(
    client: TestClient,
    sku: str = "MUG-1",
    name: str = "Mug",
    price: str = "10.00",
    stock: int = 5,
) -> dict:
    response = client.post(
        "/products",
        headers=admin_auth(client),
        json={"sku": sku, "name": name, "price": price, "stock_quantity": stock},
    )
    assert response.status_code == 201, response.text
    return response.json()
