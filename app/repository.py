from typing import Protocol

from app.models import Payment


class PaymentRepository(Protocol):
    def save(self, payment: Payment) -> Payment: ...

    def get(self, payment_id: str) -> Payment | None: ...


class InMemoryPaymentRepository:
    def __init__(self) -> None:
        self._payments: dict[str, Payment] = {}

    def save(self, payment: Payment) -> Payment:
        self._payments[payment.id] = payment
        return payment

    def get(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)
