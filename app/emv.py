"""Strict EMV BER-TLV parsing and explainable DE55 helpers.

ISO 8583 DE55 remains opaque binary at the wire-codec boundary. This module
interprets that payload as EMV BER-TLV only when a caller explicitly opts in.
Unknown tags are preserved rather than guessed.
"""

from dataclasses import dataclass

MAX_TAG_BYTES = 4
MAX_LENGTH_BYTES = 3
MAX_NESTING_DEPTH = 8

EMV_TAG_NAMES: dict[str, str] = {
    "5F2A": "Transaction Currency Code",
    "82": "Application Interchange Profile",
    "84": "Dedicated File Name",
    "95": "Terminal Verification Results",
    "9A": "Transaction Date",
    "9C": "Transaction Type",
    "9F02": "Amount, Authorised (Numeric)",
    "9F03": "Amount, Other (Numeric)",
    "9F10": "Issuer Application Data",
    "9F1A": "Terminal Country Code",
    "9F26": "Application Cryptogram",
    "9F27": "Cryptogram Information Data",
    "9F33": "Terminal Capabilities",
    "9F34": "Cardholder Verification Method Results",
    "9F35": "Terminal Type",
    "9F36": "Application Transaction Counter",
    "9F37": "Unpredictable Number",
    "9F41": "Transaction Sequence Counter",
}

_TVR_BITS: tuple[tuple[str | None, ...], ...] = (
    (
        "Offline data authentication was not performed",
        "Static data authentication failed",
        "ICC data missing",
        "Card appears on terminal exception file",
        "Dynamic data authentication failed",
        "Combined DDA/application cryptogram generation failed",
        None,
        None,
    ),
    (
        "ICC and terminal have different application versions",
        "Expired application",
        "Application not yet effective",
        "Requested service not allowed for card product",
        "New card",
        None,
        None,
        None,
    ),
    (
        "Cardholder verification was not successful",
        "Unrecognized cardholder verification method",
        "PIN try limit exceeded",
        "PIN entry required and PIN pad not present or not working",
        "PIN entry required, PIN pad present, but PIN was not entered",
        "Online PIN entered",
        None,
        None,
    ),
    (
        "Transaction exceeds floor limit",
        "Lower consecutive offline limit exceeded",
        "Upper consecutive offline limit exceeded",
        "Transaction selected randomly for online processing",
        "Merchant forced transaction online",
        None,
        None,
        None,
    ),
    (
        "Default TDOL used",
        "Issuer authentication failed",
        "Script processing failed before final GENERATE AC",
        "Script processing failed after final GENERATE AC",
        None,
        None,
        None,
        None,
    ),
)


class EMVTLVError(ValueError):
    """Raised when BER-TLV data is malformed or violates AtlasPay limits."""


@dataclass(frozen=True, slots=True)
class BerTlv:
    tag: str
    value: bytes
    constructed: bool
    children: tuple["BerTlv", ...] = ()

    @property
    def name(self) -> str | None:
        return EMV_TAG_NAMES.get(self.tag)


@dataclass(frozen=True, slots=True)
class TVR:
    raw: bytes
    failures: tuple[str, ...]

    @property
    def hex(self) -> str:
        return self.raw.hex().upper()


def parse_ber_tlv(payload: bytes | bytearray | memoryview) -> tuple[BerTlv, ...]:
    """Parse a complete BER-TLV payload and reject malformed/trailing data."""

    raw = bytes(payload)
    if not raw:
        raise EMVTLVError("BER-TLV payload must not be empty")
    items, offset = _parse_items(raw, 0, len(raw), depth=0)
    if offset != len(raw):
        raise EMVTLVError("unexpected trailing BER-TLV bytes")
    return items


def decode_de55(payload: bytes | bytearray | memoryview) -> tuple[BerTlv, ...]:
    """Decode ISO 8583 DE55 as EMV BER-TLV without changing ISO 8583 semantics."""

    return parse_ber_tlv(payload)


def decode_tvr(value: bytes | bytearray | memoryview) -> TVR:
    """Decode EMV tag 95 (Terminal Verification Results) into named set bits."""

    raw = bytes(value)
    if len(raw) != 5:
        raise EMVTLVError("TVR must contain exactly 5 bytes")

    failures: list[str] = []
    for byte_index, byte in enumerate(raw):
        names = _TVR_BITS[byte_index]
        for bit_index, name in enumerate(names):
            mask = 1 << (7 - bit_index)
            if byte & mask and name is not None:
                failures.append(name)
    return TVR(raw=raw, failures=tuple(failures))


def find_tags(items: tuple[BerTlv, ...], tag: str) -> tuple[BerTlv, ...]:
    """Find all matching tags recursively without collapsing duplicates."""

    normalized = tag.upper()
    matches: list[BerTlv] = []
    for item in items:
        if item.tag == normalized:
            matches.append(item)
        if item.children:
            matches.extend(find_tags(item.children, normalized))
    return tuple(matches)


def _parse_items(
    payload: bytes,
    offset: int,
    limit: int,
    *,
    depth: int,
) -> tuple[tuple[BerTlv, ...], int]:
    if depth > MAX_NESTING_DEPTH:
        raise EMVTLVError("BER-TLV nesting exceeds configured depth limit")

    items: list[BerTlv] = []
    while offset < limit:
        tag, constructed, offset = _read_tag(payload, offset, limit)
        length, offset = _read_length(payload, offset, limit)
        end = offset + length
        if end > limit:
            raise EMVTLVError(f"tag {tag} value is truncated")

        value = payload[offset:end]
        children: tuple[BerTlv, ...] = ()
        if constructed:
            if not value:
                raise EMVTLVError(f"constructed tag {tag} must not be empty")
            children, child_end = _parse_items(value, 0, len(value), depth=depth + 1)
            if child_end != len(value):
                raise EMVTLVError(f"constructed tag {tag} contains trailing bytes")

        items.append(BerTlv(tag=tag, value=value, constructed=constructed, children=children))
        offset = end

    return tuple(items), offset


def _read_tag(payload: bytes, offset: int, limit: int) -> tuple[str, bool, int]:
    if offset >= limit:
        raise EMVTLVError("BER-TLV tag is truncated")

    first = payload[offset]
    if first in (0x00, 0xFF):
        raise EMVTLVError("BER-TLV padding bytes are not valid tags")
    constructed = bool(first & 0x20)
    tag_bytes = bytearray((first,))
    offset += 1

    if first & 0x1F == 0x1F:
        while True:
            if offset >= limit:
                raise EMVTLVError("multi-byte BER-TLV tag is truncated")
            if len(tag_bytes) >= MAX_TAG_BYTES:
                raise EMVTLVError("BER-TLV tag exceeds configured width limit")
            current = payload[offset]
            if len(tag_bytes) == 1 and current & 0x7F == 0:
                raise EMVTLVError("BER-TLV tag uses non-canonical continuation byte")
            tag_bytes.append(current)
            offset += 1
            if current & 0x80 == 0:
                break

    return tag_bytes.hex().upper(), constructed, offset


def _read_length(payload: bytes, offset: int, limit: int) -> tuple[int, int]:
    if offset >= limit:
        raise EMVTLVError("BER-TLV length is truncated")

    first = payload[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    if first == 0x80:
        raise EMVTLVError("indefinite BER lengths are not allowed")

    width = first & 0x7F
    if width == 0 or width > MAX_LENGTH_BYTES:
        raise EMVTLVError("BER-TLV length width exceeds configured limit")
    end = offset + width
    if end > limit:
        raise EMVTLVError("BER-TLV long-form length is truncated")
    encoded = payload[offset:end]
    if encoded[0] == 0:
        raise EMVTLVError("BER-TLV length must use minimal encoding")

    length = int.from_bytes(encoded, "big")
    if length < 0x80:
        raise EMVTLVError("BER-TLV long-form length is non-canonical")
    return length, end
