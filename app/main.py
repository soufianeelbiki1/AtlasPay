import os

from fastapi import FastAPI, Header, HTTPException, status

from app.models import CreatePaymentRequest, Payment
from app.operational_snapshot import (
    OperationalSnapshot,
    OperationalSnapshotReader,
    PostgresOperationalSnapshotReader,
    UnavailableOperationalSnapshotReader,
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


def build_operational_snapshot_reader() -> OperationalSnapshotReader:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return PostgresOperationalSnapshotReader(database_url)
    return UnavailableOperationalSnapshotReader(
        "DATABASE_URL is not configured; durable operational sections cannot be measured"
    )


repository = build_repository()
service = PaymentService(repository)
operational_snapshot_reader = build_operational_snapshot_reader()


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/v1/ops/snapshot",
    response_model=OperationalSnapshot,
    tags=["operations"],
)
def get_operational_snapshot() -> OperationalSnapshot:
    """Return versioned read-only operator state without fabricating unavailable metrics."""

    return operational_snapshot_reader.read()


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
