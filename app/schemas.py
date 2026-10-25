"""Request and response models.

Request models use `extra="forbid"`: an unknown field such as `unit_price`
on an order item returns 422 instead of being silently ignored. Money is a
Decimal and is serialised as a JSON string, e.g. "19.99", so no precision is
lost to floating point.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

T = TypeVar("T")

Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Name200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Price = Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), max_digits=10, decimal_places=2)]
OrderStatus = Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# Auth -----------------------------------------------------------------------


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str


# Customers ------------------------------------------------------------------


class CustomerCreate(RequestModel):
    name: Name100
    email: EmailStr

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class CustomerUpdate(RequestModel):
    name: Name100 | None = None
    email: EmailStr | None = None

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "CustomerUpdate":
        if self.name is None and self.email is None:
            raise ValueError("Provide at least one of: name, email")
        return self


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime
    updated_at: datetime


# Products -------------------------------------------------------------------


class ProductCreate(RequestModel):
    sku: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9-]{3,32}$")]
    name: Name200
    price: Price
    stock_quantity: int = Field(ge=0, le=1_000_000)
    is_active: bool = True

    @field_validator("sku")
    @classmethod
    def uppercase_sku(cls, value: str) -> str:
        return value.upper()


class ProductUpdate(RequestModel):
    """Stock is deliberately absent: it changes only through stock
    adjustments or orders, so every change is recorded."""

    name: Name200 | None = None
    price: Price | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ProductUpdate":
        if self.name is None and self.price is None and self.is_active is None:
            raise ValueError("Provide at least one of: name, price, is_active")
        return self


class StockAdjustment(RequestModel):
    quantity_change: int = Field(ge=-1_000_000, le=1_000_000)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    @field_validator("quantity_change")
    @classmethod
    def not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_change cannot be 0")
        return value


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    price: Decimal
    stock_quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# Orders ---------------------------------------------------------------------

MAX_QUANTITY_PER_LINE = 100
MAX_LINES_PER_ORDER = 50


class OrderItemIn(RequestModel):
    product_id: int = Field(ge=1)
    quantity: int = Field(ge=1, le=MAX_QUANTITY_PER_LINE)


class OrderCreate(RequestModel):
    customer_id: int = Field(ge=1)
    items: list[OrderItemIn] = Field(min_length=1, max_length=MAX_LINES_PER_ORDER)

    @field_validator("items")
    @classmethod
    def unique_products(cls, items: list[OrderItemIn]) -> list[OrderItemIn]:
        product_ids = [item.product_id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product may appear only once; combine the quantities")
        return items


class OrderStatusUpdate(RequestModel):
    status: OrderStatus


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: str
    total_amount: Decimal
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime
