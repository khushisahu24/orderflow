from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ConflictError, NotFoundError
from app.models import Customer, Order
from app.schemas import CustomerCreate, CustomerOut, CustomerUpdate, Page
from app.security import AdminUser, AnyUser

router = APIRouter(prefix="/customers", tags=["customers"])

DbSession = Annotated[Session, Depends(get_session)]
DUPLICATE_EMAIL = "A customer with this email already exists."


def _get_or_404(session: Session, customer_id: int) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


def _email_taken(session: Session, email: str, exclude_id: int | None = None) -> bool:
    query = select(exists().where(Customer.email == email))
    if exclude_id is not None:
        query = select(exists().where(Customer.email == email, Customer.id != exclude_id))
    return bool(session.scalar(query))


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerCreate, session: DbSession, _: AnyUser) -> Customer:
    if _email_taken(session, body.email):
        raise ConflictError(DUPLICATE_EMAIL)
    customer = Customer(name=body.name, email=body.email)
    session.add(customer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError(DUPLICATE_EMAIL) from None
    session.refresh(customer)
    return customer


@router.get("", response_model=Page[CustomerOut])
def list_customers(
    session: DbSession,
    _: AnyUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    total = session.scalar(select(func.count()).select_from(Customer)) or 0
    items = session.scalars(
        select(Customer).order_by(Customer.id).limit(limit).offset(offset)
    ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, session: DbSession, _: AnyUser) -> Customer:
    return _get_or_404(session, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int, body: CustomerUpdate, session: DbSession, _: AnyUser
) -> Customer:
    customer = _get_or_404(session, customer_id)
    if body.email is not None and _email_taken(session, body.email, exclude_id=customer_id):
        raise ConflictError(DUPLICATE_EMAIL)
    if body.name is not None:
        customer.name = body.name
    if body.email is not None:
        customer.email = body.email
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError(DUPLICATE_EMAIL) from None
    session.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: int, session: DbSession, _: AdminUser) -> Response:
    customer = _get_or_404(session, customer_id)
    if session.scalar(select(exists().where(Order.customer_id == customer_id))):
        raise ConflictError("Customer has orders and cannot be deleted.")
    session.delete(customer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("Customer has orders and cannot be deleted.") from None
    return Response(status_code=204)
