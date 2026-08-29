from app.models import CreatePaymentRequest, Payment
from app.repository import PaymentRepository


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


class PaymentService:
    def __init__(self, repository: PaymentRepository) -> None:
        self.repository = repository
        self._idempotency: dict[str, tuple[CreatePaymentRequest, str]] = {}

    def create_payment(
        self,
        request: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> Payment:
        if idempotency_key and idempotency_key in self._idempotency:
            previous_request, payment_id = self._idempotency[idempotency_key]
            if previous_request != request:
                raise IdempotencyConflictError(
                    "Idempotency key was already used with a different request"
                )
            payment = self.repository.get(payment_id)
            if payment is None:
                raise RuntimeError("Idempotency record references a missing payment")
            return payment

        payment = Payment(**request.model_dump())
        self.repository.save(payment)

        if idempotency_key:
            self._idempotency[idempotency_key] = (request, payment.id)

        return payment

    def get_payment(self, payment_id: str) -> Payment | None:
        return self.repository.get(payment_id)
