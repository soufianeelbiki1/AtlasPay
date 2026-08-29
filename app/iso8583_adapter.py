"""ISO 8583 boundary adapter for the canonical AtlasPay payment model."""

from collections.abc import Mapping

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso8583 import FieldValue, ISO8583Message


class ISO8583MappingError(ValueError):
    """Raised when a valid ISO 8583 message cannot be mapped to the canonical model."""


NUMERIC_TO_ALPHA_CURRENCY: Mapping[str, str] = {
    "504": "MAD",
    "840": "USD",
    "978": "EUR",
}
ALPHA_TO_NUMERIC_CURRENCY: Mapping[str, str] = {
    alpha: numeric for numeric, alpha in NUMERIC_TO_ALPHA_CURRENCY.items()
}

_RESPONSE_MTI = {
    "0200": "0210",
    "0400": "0410",
    "0800": "0810",
}


def authorization_from_iso8583(message: ISO8583Message) -> AuthorizationRequest:
    """Map an ISO 8583 purchase authorization request into the canonical model."""

    if message.mti != "0200":
        raise ISO8583MappingError(f"Expected authorization MTI 0200; received {message.mti}")

    processing_code = _required_text(message.fields, 3)
    if processing_code != "000000":
        raise ISO8583MappingError(
            f"Unsupported DE3 processing code {processing_code}; only purchase 000000 is mapped"
        )

    amount_text = _required_text(message.fields, 4)
    amount_minor = int(amount_text)
    if amount_minor <= 0:
        raise ISO8583MappingError("DE4 transaction amount must be greater than zero")

    currency_numeric = _required_text(message.fields, 49)
    try:
        currency = NUMERIC_TO_ALPHA_CURRENCY[currency_numeric]
    except KeyError as exc:
        raise ISO8583MappingError(
            f"Unsupported DE49 numeric currency code {currency_numeric}"
        ) from exc

    icc_value = message.fields.get(55)
    if icc_value is not None and not isinstance(icc_value, bytes):
        raise ISO8583MappingError("DE55 must be binary ICC data")

    return AuthorizationRequest(
        amount_minor=amount_minor,
        currency=currency,
        merchant_id=_required_text(message.fields, 42),
        terminal_id=_required_text(message.fields, 41),
        instrument=CardPaymentInstrument(
            pan=_required_text(message.fields, 2),
            icc_data=icc_value,
        ),
        correlation=NetworkCorrelation(
            stan=_required_text(message.fields, 11),
            rrn=_required_text(message.fields, 37),
        ),
    )


def authorization_to_iso8583(request: AuthorizationRequest) -> ISO8583Message:
    """Map a canonical purchase authorization to the explicit ISO 8583 profile."""

    try:
        currency_numeric = ALPHA_TO_NUMERIC_CURRENCY[request.currency]
    except KeyError as exc:
        raise ISO8583MappingError(
            f"Unsupported canonical currency {request.currency}"
        ) from exc

    if request.amount_minor > 999_999_999_999:
        raise ISO8583MappingError("amount_minor exceeds the 12-digit DE4 profile")
    if len(request.terminal_id) != 8:
        raise ISO8583MappingError("terminal_id must be exactly 8 characters for DE41")
    if len(request.merchant_id) != 15:
        raise ISO8583MappingError("merchant_id must be exactly 15 characters for DE42")

    fields: dict[int, FieldValue] = {
        2: request.instrument.pan,
        3: "000000",
        4: f"{request.amount_minor:012d}",
        11: request.correlation.stan,
        37: request.correlation.rrn,
        41: request.terminal_id,
        42: request.merchant_id,
        49: currency_numeric,
    }
    if request.instrument.icc_data is not None:
        fields[55] = request.instrument.icc_data

    return ISO8583Message(mti="0200", fields=fields)


def correlation_key(message: ISO8583Message) -> NetworkCorrelation:
    """Extract the switch correlation key from DE11 STAN and DE37 RRN."""

    return NetworkCorrelation(
        stan=_required_text(message.fields, 11),
        rrn=_required_text(message.fields, 37),
    )


def correlates_response(request: ISO8583Message, response: ISO8583Message) -> bool:
    """Return whether a response has the expected MTI and the same STAN/RRN pair."""

    expected_mti = _RESPONSE_MTI.get(request.mti)
    if expected_mti is None or response.mti != expected_mti:
        return False
    try:
        return correlation_key(request) == correlation_key(response)
    except (ISO8583MappingError, ValueError):
        return False


def _required_text(fields: Mapping[int, FieldValue], number: int) -> str:
    try:
        value = fields[number]
    except KeyError as exc:
        raise ISO8583MappingError(f"Required DE{number} is missing") from exc
    if not isinstance(value, str):
        raise ISO8583MappingError(f"DE{number} must be text for canonical mapping")
    return value
