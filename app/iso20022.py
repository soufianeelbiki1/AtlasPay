"""ISO 20022 card-authorization projection around AtlasPay's canonical model.

This module models the subset of ISO 20022 card-payment concepts AtlasPay can
currently represent without claiming XML/XSD conformance. Concrete caaa-family
document adapters belong outside this mapping layer.

The projection carries a loss report because ISO 8583 DE55 and network-specific
trace semantics do not map losslessly into this intentionally narrow model.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation


class ISO20022MappingError(ValueError):
    """Raised when the supported ISO 20022 projection cannot represent a request."""


class MappingLossCode(StrEnum):
    ICC_DATA_NOT_PROJECTED = "icc_data_not_projected"
    STAN_IS_NETWORK_SPECIFIC = "stan_is_network_specific"


@dataclass(frozen=True, slots=True)
class MappingLoss:
    code: MappingLossCode
    detail: str


@dataclass(frozen=True, slots=True)
class ISO20022CardAuthorization:
    """Schema-neutral subset for a card authorization request."""

    message_id: str
    transaction_id: str
    amount_minor: int
    currency: str
    merchant_id: str
    terminal_id: str
    pan: str

    def __post_init__(self) -> None:
        for name, value in (
            ("message_id", self.message_id),
            ("transaction_id", self.transaction_id),
            ("merchant_id", self.merchant_id),
            ("terminal_id", self.terminal_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        if isinstance(self.amount_minor, bool) or self.amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter ASCII code")
        if self.currency != self.currency.upper():
            raise ValueError("currency must be uppercase")
        if not 12 <= len(self.pan) <= 19 or not self.pan.isascii() or not self.pan.isdecimal():
            raise ValueError("pan must contain 12 to 19 ASCII digits")


@dataclass(frozen=True, slots=True)
class ISO20022Projection:
    authorization: ISO20022CardAuthorization
    losses: tuple[MappingLoss, ...]


def authorization_to_iso20022(
    request: AuthorizationRequest,
    *,
    message_id: str,
) -> ISO20022Projection:
    """Project a canonical authorization into the supported ISO 20022 subset."""

    losses = [
        MappingLoss(
            MappingLossCode.STAN_IS_NETWORK_SPECIFIC,
            "STAN is retained in AtlasPay canonical correlation but is not projected into "
            "the schema-neutral ISO 20022 authorization subset.",
        )
    ]
    if request.instrument.icc_data is not None:
        losses.append(
            MappingLoss(
                MappingLossCode.ICC_DATA_NOT_PROJECTED,
                "ISO 8583 DE55/EMV bytes are not copied into the supported ISO 20022 "
                "projection; a concrete card-message adapter must map supported EMV "
                "elements explicitly.",
            )
        )

    return ISO20022Projection(
        authorization=ISO20022CardAuthorization(
            message_id=message_id,
            transaction_id=request.correlation.rrn,
            amount_minor=request.amount_minor,
            currency=request.currency,
            merchant_id=request.merchant_id,
            terminal_id=request.terminal_id,
            pan=request.instrument.pan,
        ),
        losses=tuple(losses),
    )


def authorization_from_iso20022(
    message: ISO20022CardAuthorization,
    *,
    stan: str,
) -> AuthorizationRequest:
    """Map the supported ISO 20022 subset into the canonical authorization model."""

    try:
        correlation = NetworkCorrelation(stan=stan, rrn=message.transaction_id)
    except ValueError as exc:
        raise ISO20022MappingError(
            "ISO 20022 transaction_id must fit AtlasPay's current 12-character RRN "
            "correlation profile and stan must be six digits"
        ) from exc

    try:
        return AuthorizationRequest(
            amount_minor=message.amount_minor,
            currency=message.currency,
            merchant_id=message.merchant_id,
            terminal_id=message.terminal_id,
            instrument=CardPaymentInstrument(pan=message.pan),
            correlation=correlation,
        )
    except ValueError as exc:
        raise ISO20022MappingError(str(exc)) from exc
