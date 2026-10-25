"""Pure business rules with no database or HTTP dependency.

Unit tests exercise these functions directly.
"""

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"shipped", "cancelled"}),
    "shipped": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}

STOCK_RESTORING_TARGET = "cancelled"


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def line_total(unit_price: Decimal, quantity: int) -> Decimal:
    return (unit_price * quantity).quantize(Decimal("0.01"))


def order_total(lines: Iterable[tuple[Decimal, int]]) -> Decimal:
    return sum(
        (line_total(price, quantity) for price, quantity in lines), Decimal("0.00")
    )


def order_request_hash(customer_id: int, items: Iterable[tuple[int, int]]) -> str:
    """Fingerprint of an order request, independent of item order.

    Used to tell a genuine retry (same Idempotency-Key, same request) from a
    key reused for a different order.
    """
    canonical = {
        "customer_id": customer_id,
        "items": sorted([product_id, quantity] for product_id, quantity in items),
    }
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
