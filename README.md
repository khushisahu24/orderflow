# OrderFlow

OrderFlow is a small order-management API and the automated tests that check it. The API is the system under test. The tests call it over HTTP and then read PostgreSQL to confirm the rows match.

A customer orders one or more products. The server calculates the total, stores the price that was charged, and reduces stock in the same database transaction. Cancelling an order puts the stock back. Two orders cannot both take the last unit.

**Stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL, PyJWT, bcrypt, Pytest, Ruff, mypy, GitHub Actions.

A one-page view of the request path and the run steps is in [docs/how-it-works.png](docs/how-it-works.png).

## Read the repository in this order

| Order | File | What it covers |
| --- | --- | --- |
| 1 | `docs/business-rules.md` | The rules the code is expected to enforce |
| 2 | `docs/architecture.md` | Diagrams, tables, and every endpoint |
| 3 | `app/models.py` | The tables, keys, and database constraints |
| 4 | `app/schemas.py` | The JSON each endpoint accepts and returns |
| 5 | `app/routers/` | One file per URL group: health, login, customers, products, orders |
| 6 | `app/services/orders.py` | The order transaction, stock lock, and idempotency |
| 7 | `tests/` | Unit rules, API tests, and one full order story |

`app/main.py` only wires those pieces together. `alembic/versions/0001_initial_schema.py` creates the tables. `docs/project-guide.md` follows one order through the files.

## Run it

You need Python 3.11 or newer and PostgreSQL (the project is tested on 18). Any terminal works; nothing depends on a particular editor.

**1. Create two databases** in PostgreSQL, for example with `psql`:

```sql
CREATE USER orderflow WITH PASSWORD 'orderflow';
CREATE DATABASE orderflow OWNER orderflow;
CREATE DATABASE orderflow_test OWNER orderflow;
```

**2. Configure.** Copy `.env.example` to `.env` and adjust the database URLs if yours differ. Change `ORDERFLOW_JWT_SECRET` and the two user passwords before using the API anywhere other than your own computer; the values in `.env.example` are local placeholders. `.env` is ignored by git.

**3. Install, migrate, seed, and start.**

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\seed.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/seed.py
.venv/bin/python -m uvicorn app.main:app --reload
```

**4. Try it.** Open http://127.0.0.1:8000/docs, call `POST /auth/login`, copy the `access_token`, and press **Authorize**. On Windows, `scripts\try-api.ps1` logs in, creates a customer and a product, and places an order.

| Email | Password in `.env.example` | Role |
| --- | --- | --- |
| admin@orderflow.example | local-admin-change-me | admin: products, stock, delete customer |
| staff@orderflow.example | local-staff-change-me | staff: customers and orders |

The `.example` domain is used because the email checker rejects the reserved `.test` domain.

## Run the tests

The tests use `ORDERFLOW_TEST_DATABASE_URL`, or `postgresql+psycopg://postgres@127.0.0.1:5432/orderflow_test` when that variable is unset. Each test empties that database first, so never point it at data you want to keep. The seed script refuses to write to a database whose name starts with `orderflow_test`.

```bash
python -m pytest            # all tests
python -m pytest -m unit    # only rules with no database
python -m ruff check app tests
python -m mypy
```

Use the virtual environment's Python (`.venv/bin/python` or `.\.venv\Scripts\python.exe`) if it is not activated.

| Folder | What it checks |
| --- | --- |
| `tests/unit` | Totals, allowed status changes, and the idempotency fingerprint, with no database |
| `tests/integration` | HTTP status codes, roles, and the matching SQL rows, including two concurrent orders |
| `tests/e2e` | One order from login through delivery |

`.github/workflows/ci.yml` runs Ruff, mypy, and Pytest against a PostgreSQL 18 service on every push and pull request, and uploads a JUnit report.

## What is implemented

- Customers: create, list, get, update, delete. Delete is admin-only and is refused when the customer has orders.
- Products: create, list with filter and sort, update name, price, and active flag. Stock changes only through an adjustment or an order, and every change is recorded in `inventory_movements`.
- Orders: several products, server-side total, stock check, status sequence, cancellation restores stock.
- The price on an order line is copied at purchase time. A later catalog price change does not rewrite it.
- Optional `Idempotency-Key` header. The same key and body returns the original order. The same key with a different body returns 409.
- Login with bcrypt password hashes and a short-lived JWT. Staff and admin roles are checked on each request.
- SQL is sent through SQLAlchemy parameters. A name that looks like SQL is stored as text.
- Errors return `{"detail": ...}` and do not include SQL or connection strings. Every response carries an `X-Request-ID`.

Passing these tests does not mean the API has had a full security review. There is no rate limit. Tokens are not revoked before they expire; a deactivated user is rejected because the role and active flag are read from the database on each request.

## Layout

```text
app/                 API code
  routers/           HTTP endpoints
  services/orders.py order transaction
  models.py          tables
  schemas.py         JSON models
  domain.py          rules with no database
  security.py        passwords, tokens, roles
alembic/             schema migrations
scripts/             seed users, try the API
tests/               unit, integration, and end-to-end tests
docs/                business rules, architecture, request walkthrough
.github/workflows/   CI
```
