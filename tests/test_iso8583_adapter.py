import pytest

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso8583 import ISO8583Message
from app.iso8583_adapter import (
    ISO8583MappingError,
    authorization_from_iso8583,
    authorization_to_iso8583,
    correlates_response,
    correlation_key,
)


def _authorization_message(**overrides: str | bytes) -> ISO8583Message:
    fields: dict[int, str | bytes] = {
        2: "4761739001010010",
        3: "000000",
        4: "000000012900",
        11: "123456",
        37: "ABC123456789",
        41: "TERM0001",
        42: "MERCHANT0000001",
        49: "504",
        55: b"\x9f\x02\x06\x00\x00\x00\x01\x29\x00",
    }
    field_numbers = {
        "pan": 2,
        "processing_code": 3,
        "amount": 4,
        "stan": 11,
        "rrn": 37,
        "terminal_id": 41,
        "merchant_id": 42,
        "currency": 49,
        "icc_data": 55,
    }
    for name, value in overrides.items():
        fields[field_numbers[name]] = value
    return ISO8583Message("0200", fields)


def test_authorization_maps_to_canonical_model_and_back() -> None:
    message = _authorization_message()

    canonical = authorization_from_iso8583(message)

    assert canonical == AuthorizationRequest(
        amount_minor=12_900,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(
            pan="4761739001010010",
            icc_data=b"\x9f\x02\x06\x00\x00\x00\x01\x29\x00",
        ),
        correlation=NetworkCorrelation(stan="123456", rrn="ABC123456789"),
    )
    assert authorization_to_iso8583(canonical) == message


def test_mapping_rejects_unsupported_processing_code_and_currency() -> None:
    with pytest.raises(ISO8583MappingError, match="processing code"):
        authorization_from_iso8583(_authorization_message(processing_code="200000"))

    with pytest.raises(ISO8583MappingError, match="numeric currency code"):
        authorization_from_iso8583(_authorization_message(currency="999"))


def test_mapping_rejects_missing_required_correlation_field() -> None:
    message = _authorization_message()
    fields = dict(message.fields)
    fields.pop(37)

    with pytest.raises(ISO8583MappingError, match="Required DE37 is missing"):
        authorization_from_iso8583(ISO8583Message(message.mti, fields))


def test_response_correlation_requires_expected_mti_stan_and_rrn() -> None:
    request = _authorization_message()
    response = ISO8583Message(
        "0210",
        {
            11: "123456",
            37: "ABC123456789",
            39: "00",
        },
    )

    assert correlation_key(request) == NetworkCorrelation(stan="123456", rrn="ABC123456789")
    assert correlates_response(request, response)
    assert not correlates_response(
        request, ISO8583Message("0210", {11: "654321", 37: "ABC123456789"})
    )
    assert not correlates_response(
        request, ISO8583Message("0200", {11: "123456", 37: "ABC123456789"})
    )


def test_canonical_to_iso8583_enforces_network_field_widths() -> None:
    request = AuthorizationRequest(
        amount_minor=100,
        currency="USD",
        merchant_id="too-short",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan="4761739001010010"),
        correlation=NetworkCorrelation(stan="123456", rrn="ABC123456789"),
    )

    with pytest.raises(ISO8583MappingError, match="merchant_id"):
        authorization_to_iso8583(request)
