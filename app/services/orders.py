"""Order placement and status changes.

Both operations run in one transaction. Product rows are locked with
`SELECT ... FOR UPDATE` in ascending id order before stock is read, so two
concurrent orders for the last unit cannot both succeed, and two orders
touching the same products always lock them in the same order (no deadlock).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import domain
from app.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Customer, InventoryMovement, Order, OrderItem, Product
from app.schemas import OrderCreate


@dataclass
class PlacedOrder:
    order: Order
    replayed: bool


def _load_order(session: Session, order_id: int) -> Order | None:
    return session.scalars(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    ).one_or_none()


def _find_by_key(session: Session, key: str) -> Order | None:
    return session.scalars(
        select(Order).where(Order.idempotency_key == key).options(selectinload(Order.items))
    ).one_or_none()


def _replay(existing: Order, request_hash: str) -> PlacedOrder:
    if existing.request_hash != request_hash:
        raise ConflictError("Idempotency-Key was already used for a different order request.")
    return PlacedOrder(order=existing, replayed=True)


def place_order(
    session: Session, data: OrderCreate, idempotency_key: str | None
) -> PlacedOrder:
    request_hash = domain.order_request_hash(
        data.customer_id, ((item.product_id, item.quantity) for item in data.items)
    )

    if idempotency_key is not None:
        existing = _find_by_key(session, idempotency_key)
        if existing is not None:
            return _replay(existing, request_hash)

    if session.get(Customer, data.customer_id) is None:
        raise UnprocessableError(f"Customer {data.customer_id} does not exist.")

    requested = {item.product_id: item.quantity for item in data.items}
    products = session.scalars(
        select(Product)
        .where(Product.id.in_(requested))
        .order_by(Product.id)
        .with_for_update()
    ).all()
    by_id = {product.id: product for product in products}

    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise UnprocessableError(f"Product {missing[0]} does not exist.")

    for product_id, quantity in requested.items():
        product = by_id[product_id]
        if not product.is_active:
            raise ConflictError(f"Product {product_id} is not available for sale.")
        if product.stock_quantity < quantity:
            raise ConflictError(
                f"Insufficient stock for product {product_id}: "
                f"requested {quantity}, available {product.stock_quantity}."
            )

    order = Order(
        customer_id=data.customer_id,
        status="pending",
        total_amount=domain.order_total(
            (by_id[pid].price, qty) for pid, qty in requested.items()
        ),
        idempotency_key=idempotency_key,
        request_hash=request_hash if idempotency_key is not None else None,
    )
    for item in data.items:
        product = by_id[item.product_id]
        order.items.append(
            OrderItem(
                product_id=product.id,
                quantity=item.quantity,
                unit_price=product.price,
                line_total=domain.line_total(product.price, item.quantity),
            )
        )
        product.stock_quantity -= item.quantity
    session.add(order)
    session.flush()

    for item in data.items:
        session.add(
            InventoryMovement(
                product_id=item.product_id,
                order_id=order.id,
                quantity_change=-item.quantity,
                reason="order_reserved",
            )
        )

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if idempotency_key is not None:
            existing = _find_by_key(session, idempotency_key)
            if existing is not None:
                return _replay(existing, request_hash)
        raise

    loaded = _load_order(session, order.id)
    assert loaded is not None
    return PlacedOrder(order=loaded, replayed=False)


def change_status(session: Session, order_id: int, target: str) -> Order:
    order = session.scalars(
        select(Order).where(Order.id == order_id).with_for_update()
    ).one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")

    if not domain.can_transition(order.status, target):
        raise ConflictError(f"Cannot change order status from {order.status} to {target}.")

    if target == domain.STOCK_RESTORING_TARGET:
        items = session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).all()
        quantities = {item.product_id: item.quantity for item in items}
        products = session.scalars(
            select(Product)
            .where(Product.id.in_(quantities))
            .order_by(Product.id)
            .with_for_update()
        ).all()
        for product in products:
            product.stock_quantity += quantities[product.id]
            session.add(
                InventoryMovement(
                    product_id=product.id,
                    order_id=order.id,
                    quantity_change=quantities[product.id],
                    reason="order_cancelled",
                )
            )

    order.status = target
    session.commit()
    loaded = _load_order(session, order.id)
    assert loaded is not None
    return loaded
