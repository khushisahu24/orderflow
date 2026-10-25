# Business rules

These are the rules the current code enforces. The tests in `tests/` check them through HTTP and, where the database matters, through SQL.

## Users and access

| Action | admin | staff | no token |
| --- | --- | --- | --- |
| Health, version, readiness, login | yes | yes | yes |
| Create and update customers, list and get records, place and update orders | yes | yes | 401 |
| Create or update products, adjust stock, delete a customer | yes | 403 | 401 |

Passwords are stored as bcrypt hashes. A login returns a bearer token. A wrong email and a wrong password both return 401 with `Incorrect email or password.`

## Customers

| Rule | Result |
| --- | --- |
| Name is required, trimmed, 1 to 100 characters | otherwise 422 |
| Email is required, valid, and stored in lowercase | otherwise 422 |
| The same email, ignoring letter case | 409, and the first row stays |
| Unknown extra fields | 422 |
| Unknown id | 404 |
| Delete when the customer has no orders | 204, admin only |
| Delete when the customer has an order | 409. The database also uses `ON DELETE RESTRICT` |

## Products and stock

| Rule | Result |
| --- | --- |
| SKU is 3 to 32 letters, digits, or hyphens, stored in uppercase | duplicate SKU is 409 |
| Price is greater than 0 and has at most 2 decimal places | otherwise 422 |
| New stock is 0 or more | otherwise 422 |
| A product update cannot include `stock_quantity` | 422. Stock changes through `POST /products/{id}/stock-adjustments` or an order |
| An adjustment that would make stock negative | 409, and the quantity stays unchanged |
| List filters | `is_active`, `in_stock`, `min_price`, `max_price`, `q` (name search), `sort_by`, `sort_order`, `limit`, `offset` |
| Inactive product on an order | 409 |

Every stock change inserts an `inventory_movements` row. For each product, `stock_quantity` equals the sum of `quantity_change`.

## Orders

An order is created as `pending`. The server copies each product price onto the order line and sets:

`line_total = unit_price * quantity`

`total_amount` is the sum of the line totals. The caller cannot send a price.

| From | Allowed next status |
| --- | --- |
| pending | confirmed, cancelled |
| confirmed | shipped, cancelled |
| shipped | delivered |
| delivered | none |
| cancelled | none |

Any other change returns 409.

Creating an order locks the product rows, checks stock, writes the order, the lines, and the stock movements, then commits. If the request is rejected, none of those rows remain and stock is unchanged.

Cancellation adds the quantities back and writes `order_cancelled` movements.

Quantity per line is 1 to 100. An order has 1 to 50 lines. The same product cannot appear twice in one order; the caller adds the quantities.

A missing customer or product returns 422. More quantity than stock returns 409.

### Idempotency

If `Idempotency-Key` is sent:

| Situation | Result |
| --- | --- |
| First request | 201 and the new order |
| Same key and same customer, products, and quantities | 200, header `Idempotent-Replayed: true`, same order, stock reduced once |
| Same key and a different body | 409 |

### Historical price

`order_items.unit_price` is the catalog price at purchase. Updating the product price later does not change the order line. This is stored on purpose so the charged amount stays accurate.

## Errors

422 means the request itself is invalid. 409 means the request was understood and conflicts with data already stored. 404 means the id is not there. 401 means login is missing or wrong. 403 means the role is not allowed. 503 means PostgreSQL could not be reached. 500 returns `Internal server error.` and the server log records the request id, not the caller's password or token.
