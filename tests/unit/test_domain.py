"""Rules that do not need a database or a running API."""

from decimal import Decimal

import pytest

from app.domain import can_transition, line_total, order_request_hash, order_total

pytestmark = pytest.mark.unit


def test_order_total_is_the_sum_of_price_times_quantity():
    total = order_total([(Decimal("10.00"), 2), (Decimal("3.50"), 1)])
    assert total == Decimal("23.50")
    assert line_total(Decimal("10.00"), 2) == Decimal("20.00")


def test_allowed_and_forbidden_status_changes():
    assert can_transition("pending", "confirmed")
    assert can_transition("pending", "cancelled")
    assert can_transition("confirmed", "shipped")
    assert can_transition("shipped", "delivered")
    assert not can_transition("pending", "delivered")
    assert not can_transition("delivered", "cancelled")
    assert not can_transition("cancelled", "pending")


def test_request_hash_ignores_item_order_and_changes_when_quantity_changes():
    first = order_request_hash(1, [(2, 1), (9, 3)])
    reordered = order_request_hash(1, [(9, 3), (2, 1)])
    different_quantity = order_request_hash(1, [(2, 2), (9, 3)])
    assert first == reordered
    assert first != different_quantity
