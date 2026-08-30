import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.models import CreatePaymentRequest
from app.repository import IdempotencyConflictError, PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def repository() -> PostgresPaymentRepository:
    assert DATABASE_URL is not None
    return PostgresPaymentRepository(DATABASE_URL)


def test_idempotency_survives_repository_instances() -> None:
    first_repository = repository()
    second_repository = repository()
    request = CreatePaymentRequest(
        amount=1499,
        currency="mad",
        merchant_reference=f"restart-{uuid4().hex}",
    )
    key = f"restart-{uuid4().hex}"

    first = first_repository.create_payment(request, key)
    second = second_repository.create_payment(request, key)

    assert second.id == first.id
    assert second_repository.get(first.id) == first


def test_idempotency_conflict_is_durable() -> None:
    store = repository()
    key = f"conflict-{uuid4().hex}"
    first = CreatePaymentRequest(
        amount=1000,
        currency="MAD",
        merchant_reference=f"first-{uuid4().hex}",
    )
    different = CreatePaymentRequest(
        amount=2000,
        currency="MAD",
        merchant_reference=f"second-{uuid4().hex}",
    )

    store.create_payment(first, key)

    with pytest.raises(IdempotencyConflictError):
        store.create_payment(different, key)


def test_concurrent_workers_converge_on_one_payment() -> None:
    request = CreatePaymentRequest(
        amount=7250,
        currency="MAD",
        merchant_reference=f"concurrent-{uuid4().hex}",
    )
    key = f"concurrent-{uuid4().hex}"

    def create_once(_: int) -> str:
        return repository().create_payment(request, key).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        payment_ids = list(executor.map(create_once, range(16)))

    assert len(set(payment_ids)) == 1
