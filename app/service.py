from app.models import CreatePaymentRequest, Payment
from app.repository import IdempotencyConflictError, PaymentRepository


class PaymentService:
    def __init__(self, repository: PaymentRepository) -> None:
        self.repository = repository

    def create_payment(
        self,
        request: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> Payment:
        return self.repository.create_payment(request, idempotency_key)

    def get_payment(self, payment_id: str) -> Payment | None:
        return self.repository.get(payment_id)


__all__ = ["IdempotencyConflictError", "PaymentService"]
