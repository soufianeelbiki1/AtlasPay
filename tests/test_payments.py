from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_and_fetch_payment() -> None:
    response = client.post(
        "/v1/payments",
        json={
            "amount": 12900,
            "currency": "mad",
            "merchant_reference": "order-123",
        },
    )

    assert response.status_code == 201
    payment = response.json()
    assert payment["amount"] == 12900
    assert payment["currency"] == "MAD"
    assert payment["status"] == "pending"

    fetched = client.get(f"/v1/payments/{payment['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payment["id"]


def test_idempotency_returns_same_payment() -> None:
    payload = {
        "amount": 5000,
        "currency": "MAD",
        "merchant_reference": "order-idempotent",
    }
    headers = {"Idempotency-Key": "checkout-abc"}

    first = client.post("/v1/payments", json=payload, headers=headers)
    second = client.post("/v1/payments", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_rejects_different_payload() -> None:
    headers = {"Idempotency-Key": "checkout-conflict"}

    first = client.post(
        "/v1/payments",
        json={"amount": 1000, "currency": "MAD", "merchant_reference": "order-a"},
        headers=headers,
    )
    second = client.post(
        "/v1/payments",
        json={"amount": 2000, "currency": "MAD", "merchant_reference": "order-b"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
