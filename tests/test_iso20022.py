import pytest

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso20022 import (
    ISO20022CardAuthorization,
    ISO20022MappingError,
    MappingLossCode,
    authorization_from_iso20022,
    authorization_to_iso20022,
)
from app.iso8583_adapter import authorization_from_iso8583, authorization_to_iso8583


def canonical(*, icc_data: bytes | None = None) -> AuthorizationRequest:
    return AuthorizationRequest(
        amount_minor=12_900,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(
            pan="4761739001010010",
            icc_data=icc_data,
        ),
        correlation=NetworkCorrelation(stan="123456", rrn="ABC123456789"),
    )


def test_canonical_to_iso20022_reports_network_specific_loss() -> None:
    projection = authorization_to_iso20022(canonical(), message_id="msg-001")

    assert projection.authorization.transaction_id == "ABC123456789"
    assert projection.authorization.amount_minor == 12_900
    assert {loss.code for loss in projection.losses} == {
        MappingLossCode.STAN_IS_NETWORK_SPECIFIC,
    }


def test_de55_loss_is_explicit_in_iso20022_projection() -> None:
    projection = authorization_to_iso20022(
        canonical(icc_data=bytes.fromhex("9F0206000000012900")),
        message_id="msg-002",
    )

    assert {loss.code for loss in projection.losses} == {
        MappingLossCode.STAN_IS_NETWORK_SPECIFIC,
        MappingLossCode.ICC_DATA_NOT_PROJECTED,
    }


def test_iso20022_subset_round_trips_through_canonical_with_allocated_stan() -> None:
    message = ISO20022CardAuthorization(
        message_id="msg-003",
        transaction_id="ABC123456789",
        amount_minor=12_900,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        pan="4761739001010010",
    )

    mapped = authorization_from_iso20022(message, stan="654321")

    assert mapped == AuthorizationRequest(
        amount_minor=12_900,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan="4761739001010010"),
        correlation=NetworkCorrelation(stan="654321", rrn="ABC123456789"),
    )


def test_iso8583_to_canonical_to_iso20022_documents_de55_loss() -> None:
    source = authorization_to_iso8583(
        canonical(icc_data=bytes.fromhex("9F0206000000012900"))
    )
    mapped = authorization_from_iso8583(source)
    projection = authorization_to_iso20022(mapped, message_id="bridge-001")

    assert projection.authorization.amount_minor == mapped.amount_minor
    assert projection.authorization.currency == mapped.currency
    assert MappingLossCode.ICC_DATA_NOT_PROJECTED in {
        loss.code for loss in projection.losses
    }


def test_iso20022_to_canonical_to_iso8583_requires_iso8583_field_widths() -> None:
    message = ISO20022CardAuthorization(
        message_id="msg-004",
        transaction_id="ABC123456789",
        amount_minor=500,
        currency="USD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        pan="4761739001010010",
    )

    canonical_request = authorization_from_iso20022(message, stan="123456")
    iso8583 = authorization_to_iso8583(canonical_request)

    assert iso8583.fields[4] == "000000000500"
    assert iso8583.fields[49] == "840"
    assert 55 not in iso8583.fields


def test_iso20022_transaction_id_that_cannot_fit_rrn_fails_closed() -> None:
    message = ISO20022CardAuthorization(
        message_id="msg-005",
        transaction_id="transaction-id-longer-than-rrn",
        amount_minor=500,
        currency="EUR",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        pan="4761739001010010",
    )

    with pytest.raises(ISO20022MappingError, match="12-character RRN"):
        authorization_from_iso20022(message, stan="123456")
