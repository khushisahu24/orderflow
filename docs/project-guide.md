# How an OrderFlow request is handled

Checked locally on 24 October 2026: 24 Pytest tests passed. Ruff and mypy reported no issues. The GitHub Actions file is present and has not been run.

Use this after the README. It follows one order through the files.

1. The caller sends `POST /orders` with `Authorization: Bearer <token>` and a JSON body: a customer id and a list of product ids and quantities.
2. `app/main.py` gives the request an id, then FastAPI routes it to `app/routers/orders.py`.
3. `app/security.py` reads the token, loads the user from `users`, and rejects a missing token (401) or a role that is not allowed (403).
4. `app/schemas.py` checks the JSON. A missing field, a quantity of 0, or a repeated product returns 422 before any order row is written.
5. `app/services/orders.py` opens the work:
   - if an `Idempotency-Key` was used before with the same body, it returns that order
   - it locks the product rows in id order
   - it rejects a missing customer, an inactive product, or insufficient stock
   - it copies the current price onto each order line and reduces `stock_quantity`
   - it inserts matching `inventory_movements` rows
   - it commits once. A failure rolls the whole attempt back
6. The response is the order, including the total. A test that needs to prove the database then runs its own SQL. The JSON body is not treated as proof of the row.

Status changes use the same service. The allowed moves are the dictionary in `app/domain.py`. Cancellation is the only move that puts stock back.

The tables and the constraints that repeat these rules inside PostgreSQL are in `app/models.py` and `alembic/versions/0001_initial_schema.py`.
