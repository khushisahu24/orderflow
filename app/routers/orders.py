from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.errors import NotFoundError
from app.models import Order
from app.schemas import OrderCreate, OrderOut, OrderStatus, OrderStatusUpdate, Page
from app.security import AnyUser
from app.services import orders as order_service

router = APIRouter(prefix="/orders", tags=["orders"])

DbSession = Annotated[Session, Depends(get_session)]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Optional. Retrying with the same key and body returns the original order.",
    ),
]


@router.post(
    "",
    response_model=OrderOut,
    status_code=201,
    responses={200: {"description": "Replay of an earlier request with the same Idempotency-Key"}},
)
def create_order(
    body: OrderCreate,
    response: Response,
    session: DbSession,
    _: AnyUser,
    idempotency_key: IdempotencyKey = None,
) -> Order:
    placed = order_service.place_order(session, body, idempotency_key)
    if placed.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return placed.order


@router.get("", response_model=Page[OrderOut])
def list_orders(
    session: DbSession,
    _: AnyUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: OrderStatus | None = None,
    customer_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    filters = []
    if status is not None:
        filters.append(Order.status == status)
    if customer_id is not None:
        filters.append(Order.customer_id == customer_id)
    total = session.scalar(select(func.count()).select_from(Order).where(*filters)) or 0
    items = session.scalars(
        select(Order)
        .where(*filters)
        .options(selectinload(Order.items))
        .order_by(Order.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, session: DbSession, _: AnyUser) -> Order:
    order = session.scalars(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    ).one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    return order


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_order_status(
    order_id: int, body: OrderStatusUpdate, session: DbSession, _: AnyUser
) -> Order:
    return order_service.change_status(session, order_id, body.status)
