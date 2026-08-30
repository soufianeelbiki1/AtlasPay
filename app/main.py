import os

from fastapi import FastAPI, Header, HTTPException, status

from app.models import CreatePaymentRequest, Payment
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
