"""Protocol-independent payment domain models used at AtlasPay boundaries."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkCorrelation:
    """Network trace references retained without coupling the domain to a wire codec."""

    stan: str
    rrn: str

    def __post_init__(self) -> None:
        if len(self.stan) != 6 or not self.stan.isascii() or not self.stan.isdecimal():
            raise ValueError("STAN must be exactly six ASCII digits")
        if len(self.rrn) != 12 or not self.rrn.isascii() or not self.rrn.isprintable():
            raise ValueError("RRN must be exactly twelve printable ASCII characters")


@dataclass(frozen=True, slots=True)
class CardPaymentInstrument:
    """Card data required by the simulated network adapter.

    AtlasPay is a portfolio simulation; production systems should tokenize PAN data
    and apply the relevant PCI DSS controls rather than persist raw account numbers.
    """

    pan: str
    icc_data: bytes | None = None

    def __post_init__(self) -> None:
        if not 12 <= len(self.pan) <= 19 or not self.pan.isascii() or not self.pan.isdecimal():
            raise ValueError("PAN must contain 12 to 19 ASCII digits")
        if self.icc_data is not None and not self.icc_data:
            raise ValueError("ICC data must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """Canonical purchase-authorization request independent of ISO 8583 encoding."""

    amount_minor: int
    currency: str
    merchant_id: str
    terminal_id: str
    instrument: CardPaymentInstrument
    correlation: NetworkCorrelation

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or self.amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter ASCII code")
        if self.currency != self.currency.upper():
            raise ValueError("currency must be uppercase")
        if not self.merchant_id:
            raise ValueError("merchant_id cannot be empty")
        if not self.terminal_id:
            raise ValueError("terminal_id cannot be empty")
