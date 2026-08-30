import os

from fastapi import FastAPI, Header, HTTPException, status

from app.models import CreatePaymentRequest, Payment, PaymentOperation, PaymentOperationRequest
from app.payment_accounting import (
    InvalidPaymentTransitionError,
    OperationIdempotencyConflictError,
    PaymentNotFoundError,
    PostgresPaymentAccounting,
)
from app.repository import InMemoryPaymentRepository, PaymentRepository, PostgresPaymentRepository
from app.service import IdempotencyConflictError, PaymentService

app = FastAPI(
    title="AtlasPay",
    version="0.1.0",
    description="Production-minded payment orchestration API",
)


def build_repository() -> PaymentRepository:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return PostgresPaymentRepository(database_url)
    return InMemoryPaymentRepository()


repository = build_repository()
service = PaymentService(repository)
database_url = os.getenv("DATABASE_URL")
accounting_service = PostgresPaymentAccounting(database_url) if database_url else None


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/payments",
    response_model=Payment,
    status_code=status.HTTP_201_CREATED,
    tags=["payments"],
)
def create_payment(
    request: CreatePaymentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Payment:
    try:
        return service.create_payment(request, idempotency_key)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/v1/payments/{payment_id}", response_model=Payment, tags=["payments"])
def get_payment(payment_id: str) -> Payment:
    payment = service.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


def require_accounting_service() -> PostgresPaymentAccounting:
    if accounting_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is required for monetary payment operations",
        )
    return accounting_service


def run_accounting_operation(operation):
    try:
        return operation()
    except PaymentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        ) from exc
    except (InvalidPaymentTransitionError, OperationIdempotencyConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post(
    "/v1/payments/{payment_id}/authorize",
    response_model=PaymentOperation,
    tags=["payments"],
)
def authorize_payment(
    payment_id: str,
    request: PaymentOperationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> PaymentOperation:
    accounting = require_accounting_service()
    return run_accounting_operation(
        lambda: accounting.authorize(
            payment_id=payment_id,
            amount=request.amount,
            idempotency_key=idempotency_key,
        )
    )


@app.post(
    "/v1/payments/{payment_id}/capture",
    response_model=PaymentOperation,
    tags=["payments"],
)
def capture_payment(
    payment_id: str,
    request: PaymentOperationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> PaymentOperation:
    accounting = require_accounting_service()
    return run_accounting_operation(
        lambda: accounting.capture(
            payment_id=payment_id,
            amount=request.amount,
            idempotency_key=idempotency_key,
        )
    )


@app.post(
    "/v1/payments/{payment_id}/refund",
    response_model=PaymentOperation,
    tags=["payments"],
)
def refund_payment(
    payment_id: str,
    request: PaymentOperationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> PaymentOperation:
    accounting = require_accounting_service()
    return run_accounting_operation(
        lambda: accounting.refund(
            payment_id=payment_id,
            amount=request.amount,
            idempotency_key=idempotency_key,
        )
    )
