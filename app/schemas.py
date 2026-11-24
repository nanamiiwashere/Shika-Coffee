from decimal import Decimal
from typing import Annotated, Any, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints

RoleType = Literal["admin", "cashier", "manager"]
OrderType = Literal["dine_in", "take_away"]
OrderStatus = Literal["received", "processing", "ready", "finished"]
PaymentMethod = Literal["cash", "qris", "debit"]
ShiftNoteCategory = Literal["flavor", "maintenance", "service"]

StrippedStr = Annotated[str, BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v)]
EmailMax150 = Annotated[EmailStr, StringConstraints(max_length=150)]
Username = Annotated[str, StringConstraints(min_length=1, max_length=50, pattern=r"^[^\s@]+$")]


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: StrippedStr = Field(min_length=1, max_length=100)
    email: EmailMax150
    username: Username
    password: str = Field(min_length=8, max_length=128)


class UserCreate(BaseModel):
    email: EmailMax150
    username: Username | None = None
    password: str | None = Field(default=None, min_length=8)
    full_name: StrippedStr = Field(min_length=1, max_length=100)
    role: RoleType = "cashier"
    is_active: bool = True


class UserUpdate(BaseModel):
    role: RoleType | None = None
    is_active: bool | None = None
    full_name: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, min_length=8)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: StrippedStr | None = Field(default=None, min_length=1, max_length=100)
    email: EmailMax150 | None = None
    username: Username | None = None
    avatar_url: StrippedStr | None = Field(default=None, max_length=255)
    current_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class ImageUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_data: str = Field(min_length=20, max_length=3_000_000)


AvatarUploadRequest = ImageUploadRequest


class QrisSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    customer_name: StrippedStr = Field(default="Walk-in", min_length=1, max_length=50)
    timeout_seconds: int = Field(default=300, ge=5, le=900)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None


class ProductCreate(BaseModel):
    category_id: int
    sku: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=255)


class ProductUpdate(BaseModel):
    category_id: int | None = None
    sku: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None
    image_url: str | None = Field(default=None, max_length=255)


class UnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    symbol: str = Field(min_length=1, max_length=10)


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    symbol: str | None = Field(default=None, min_length=1, max_length=10)


class RawMaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # blocks direct current_stock injection

    unit_id: int
    sku: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    minimum_stock: Decimal = Field(default=Decimal("10.00"), ge=0, max_digits=12, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=255)


class RawMaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # blocks direct current_stock edits

    unit_id: int | None = None
    sku: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    minimum_stock: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=255)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=25)
    email: EmailMax150 | None = None
    address: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=25)
    email: EmailMax150 | None = None
    address: str | None = None


class RecipeItemCreate(BaseModel):
    raw_material_id: int
    quantity_required: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class RecipeItemUpdate(BaseModel):
    quantity_required: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class SaleItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    notes: str | None = Field(default=None, max_length=200)


class SaleCreate(BaseModel):
    customer_name: StrippedStr = Field(default="Guest", min_length=1, max_length=50)
    order_type: OrderType = "dine_in"
    discount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    tax: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    payment_method: PaymentMethod
    amount_paid: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    items: list[SaleItemIn] = Field(min_length=1)


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_status: OrderStatus


class PurchaseItemIn(BaseModel):
    raw_material_id: int
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class PurchaseCreate(BaseModel):
    supplier_id: int
    notes: str | None = None
    items: list[PurchaseItemIn] = Field(min_length=1)


class StockAdjustmentIn(BaseModel):
    raw_material_id: int
    actual_stock: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    notes: StrippedStr = Field(min_length=1, max_length=255)


class StockWasteIn(BaseModel):
    raw_material_id: int
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    notes: StrippedStr = Field(min_length=1, max_length=255)


class ShiftNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ShiftNoteCategory = "flavor"
    content: StrippedStr = Field(min_length=1, max_length=240)


class ShiftNoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ShiftNoteCategory | None = None
    content: StrippedStr | None = Field(default=None, min_length=1, max_length=240)
    is_done: bool | None = None