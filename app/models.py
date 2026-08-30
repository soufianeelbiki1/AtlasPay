from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class PaymentStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PARTIALLY_CAPTURED = "partially_captured"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentOperationType(StrEnum):
    AUTHORIZE = "authorize"
    CAPTURE = "capture"
    REFUND = "refund"


class CreatePaymentRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in the currency's minor unit")
    currency: str = Field(min_length=3, max_length=3)
    merchant_reference: str = Field(min_length=1, max_length=128)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class PaymentOperationRequest(BaseModel):
    amount: int = Field(gt=0, description="Operation amount in the currency's minor unit")


class PaymentOperation(BaseModel):
    id: str
    payment_id: str
    operation_type: PaymentOperationType
    amount: int
    journal_id: str | None = None


class Payment(BaseModel):
    id: str = Field(default_factory=lambda: f"pay_{uuid4().hex}")
    amount: int
    currency: str
    merchant_reference: str
    status: PaymentStatus = PaymentStatus.PENDING
    authorized_amount: int = 0
    captured_amount: int = 0
    refunded_amount: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
