from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class PaymentStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    REVERSED = "reversed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CreatePaymentRequest(BaseModel):
    amount: int = Field(gt=0, description="Amount in the currency's minor unit")
    currency: str = Field(min_length=3, max_length=3)
    merchant_reference: str = Field(min_length=1, max_length=128)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class Payment(BaseModel):
    id: str = Field(default_factory=lambda: f"pay_{uuid4().hex}")
    amount: int
    currency: str
    merchant_reference: str
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
