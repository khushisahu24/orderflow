from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import InventoryMovement, Product
from app.schemas import Page, ProductCreate, ProductOut, ProductUpdate, StockAdjustment
from app.security import AdminUser, AnyUser

router = APIRouter(prefix="/products", tags=["products"])

DbSession = Annotated[Session, Depends(get_session)]
DUPLICATE_SKU = "A product with this SKU already exists."

SORTABLE_COLUMNS = {
    "id": Product.id,
    "name": Product.name,
    "price": Product.price,
    "stock_quantity": Product.stock_quantity,
    "created_at": Product.created_at,
}


def _get_or_404(session: Session, product_id: int, lock: bool = False) -> Product:
    query = select(Product).where(Product.id == product_id)
    if lock:
        query = query.with_for_update()
    product = session.scalars(query).one_or_none()
    if product is None:
        raise NotFoundError("Product not found.")
    return product


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, session: DbSession, _: AdminUser) -> Product:
    if session.scalar(select(exists().where(Product.sku == body.sku))):
        raise ConflictError(DUPLICATE_SKU)
    product = Product(**body.model_dump())
    session.add(product)
    session.flush()
    if product.stock_quantity > 0:
        session.add(
            InventoryMovement(
                product_id=product.id,
                quantity_change=product.stock_quantity,
                reason="initial_stock",
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError(DUPLICATE_SKU) from None
    session.refresh(product)
    return product


@router.get("", response_model=Page[ProductOut])
def list_products(
    session: DbSession,
    _: AnyUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    is_active: bool | None = None,
    in_stock: bool | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: Literal["id", "name", "price", "stock_quantity", "created_at"] = "id",
    sort_order: Literal["asc", "desc"] = "asc",
) -> dict[str, object]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise UnprocessableError("min_price cannot be greater than max_price.")

    filters: list[ColumnElement[bool]] = []
    if is_active is not None:
        filters.append(Product.is_active.is_(is_active))
    if in_stock is True:
        filters.append(Product.stock_quantity > 0)
    elif in_stock is False:
        filters.append(Product.stock_quantity == 0)
    if min_price is not None:
        filters.append(Product.price >= min_price)
    if max_price is not None:
        filters.append(Product.price <= max_price)
    if q is not None:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Product.name.ilike(f"%{escaped}%", escape="\\"))

    column = SORTABLE_COLUMNS[sort_by]
    ordering = column.asc() if sort_order == "asc" else column.desc()

    total = session.scalar(select(func.count()).select_from(Product).where(*filters)) or 0
    items = session.scalars(
        select(Product)
        .where(*filters)
        .order_by(ordering, Product.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, session: DbSession, _: AnyUser) -> Product:
    return _get_or_404(session, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, body: ProductUpdate, session: DbSession, _: AdminUser
) -> Product:
    product = _get_or_404(session, product_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(product, field, value)
    session.commit()
    session.refresh(product)
    return product


@router.post("/{product_id}/stock-adjustments", response_model=ProductOut)
def adjust_stock(
    product_id: int, body: StockAdjustment, session: DbSession, _: AdminUser
) -> Product:
    product = _get_or_404(session, product_id, lock=True)
    new_quantity = product.stock_quantity + body.quantity_change
    if new_quantity < 0:
        raise ConflictError(
            f"Stock cannot go below 0: current {product.stock_quantity}, "
            f"change {body.quantity_change}."
        )
    product.stock_quantity = new_quantity
    session.add(
        InventoryMovement(
            product_id=product.id,
            quantity_change=body.quantity_change,
            reason="adjustment",
            note=body.note,
        )
    )
    session.commit()
    session.refresh(product)
    return product
