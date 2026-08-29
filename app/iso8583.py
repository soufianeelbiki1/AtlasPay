"""Strict, dependency-free ISO 8583 message codecs.

The codec deliberately models a message without a transport header. It uses
an ASCII MTI, binary 64/128-bit bitmaps, and ASCII length prefixes for LLVAR
and LLLVAR fields. Network-specific framing and encoding profiles belong at a
transport boundary, not inside this message codec.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeAlias


class ISO8583CodecError(ValueError):
    """Raised when an ISO 8583 message violates the configured field profile."""


FieldDataType: TypeAlias = Literal["n", "ans", "binary"]
LengthType: TypeAlias = Literal["fixed", "llvar", "lllvar"]
FieldValue: TypeAlias = str | bytes


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Encoding rules for one ISO 8583 data element.

    ``max_length`` is measured in ASCII bytes for text/numeric fields and raw
    bytes for binary fields. Variable fields may set ``min_length`` to enforce
    profile requirements such as a non-empty PAN.
    """

    number: int
    data_type: FieldDataType
    length_type: LengthType
    max_length: int
    min_length: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not 2 <= self.number <= 128:
            raise ValueError("ISO 8583 data element numbers must be between 2 and 128")
        if self.max_length <= 0:
            raise ValueError("max_length must be positive")
        if self.min_length < 0 or self.min_length > self.max_length:
            raise ValueError("min_length must be between zero and max_length")
        if self.length_type == "fixed" and self.min_length != 0:
            raise ValueError("fixed fields cannot define min_length")
        if self.length_type == "llvar" and self.max_length > 99:
            raise ValueError("LLVAR max_length cannot exceed 99")
        if self.length_type == "lllvar" and self.max_length > 999:
            raise ValueError("LLLVAR max_length cannot exceed 999")

    @property
    def length_prefix_width(self) -> int:
        if self.length_type == "llvar":
            return 2
        if self.length_type == "lllvar":
            return 3
        return 0


# This is a small, explicit profile rather than a claim that every network
# uses identical encodings. Applications can provide a network-specific
# mapping to ISO8583Codec when their profile differs.
DEFAULT_FIELD_SPECS: Mapping[int, FieldSpec] = MappingProxyType(
    {
        2: FieldSpec(2, "n", "llvar", 19, min_length=1, description="Primary account number"),
        3: FieldSpec(3, "n", "fixed", 6, description="Processing code"),
        4: FieldSpec(4, "n", "fixed", 12, description="Transaction amount"),
        7: FieldSpec(7, "n", "fixed", 10, description="Transmission date and time"),
        11: FieldSpec(11, "n", "fixed", 6, description="Systems trace audit number"),
        12: FieldSpec(12, "n", "fixed", 6, description="Local transaction time"),
        13: FieldSpec(13, "n", "fixed", 4, description="Local transaction date"),
        37: FieldSpec(37, "ans", "fixed", 12, description="Retrieval reference number"),
        38: FieldSpec(38, "ans", "fixed", 6, description="Authorization identification response"),
        39: FieldSpec(39, "ans", "fixed", 2, description="Response code"),
        41: FieldSpec(41, "ans", "fixed", 8, description="Card acceptor terminal identification"),
        42: FieldSpec(42, "ans", "fixed", 15, description="Card acceptor identification code"),
        49: FieldSpec(49, "n", "fixed", 3, description="Transaction currency code"),
        52: FieldSpec(52, "binary", "fixed", 8, description="Personal identification number data"),
        55: FieldSpec(
            55, "binary", "lllvar", 999, min_length=1, description="ICC system-related data"
        ),
        70: FieldSpec(70, "n", "fixed", 3, description="Network management information code"),
    }
)


@dataclass(frozen=True, slots=True)
class ISO8583Message:
    """An ISO 8583 message with a four-digit MTI and decoded data elements."""

    mti: str
    fields: Mapping[int, FieldValue]


class ISO8583Codec:
    """Encode and decode messages for an explicit ISO 8583 field profile."""

    def __init__(self, field_specs: Mapping[int, FieldSpec] = DEFAULT_FIELD_SPECS) -> None:
        self._field_specs = dict(field_specs)
        for number, spec in self._field_specs.items():
            if number != spec.number:
                raise ValueError(f"Field spec key {number} does not match DE{spec.number}")

    def encode(self, message: ISO8583Message) -> bytes:
        mti = _encode_mti(message.mti)
        if not isinstance(message.fields, Mapping):
            raise ISO8583CodecError("fields must be a mapping")

        normalized_fields: dict[int, bytes] = {}
        for number, value in message.fields.items():
            _validate_field_number(number)
            spec = self._field_specs.get(number)
            if spec is None:
                raise ISO8583CodecError(f"No field specification registered for DE{number}")
            normalized_fields[number] = _encode_field(spec, value)

        bitmap = _encode_bitmap(normalized_fields)
        return (
            mti
            + bitmap
            + b"".join(normalized_fields[number] for number in sorted(normalized_fields))
        )

    def decode(self, payload: bytes | bytearray | memoryview) -> ISO8583Message:
        raw = bytes(payload)
        if len(raw) < 12:
            raise ISO8583CodecError("Message must contain a 4-byte MTI and primary bitmap")

        mti = _decode_mti(raw[:4])
        primary = int.from_bytes(raw[4:12], "big")
        has_secondary = bool(primary & (1 << 63))
        bitmap_end = 20 if has_secondary else 12
        if len(raw) < bitmap_end:
            raise ISO8583CodecError("Secondary bitmap indicator is set but bitmap is truncated")

        field_numbers = _decode_field_numbers(primary, raw[12:20] if has_secondary else b"")
        offset = bitmap_end
        fields: dict[int, FieldValue] = {}
        for number in field_numbers:
            spec = self._field_specs.get(number)
            if spec is None:
                raise ISO8583CodecError(f"No field specification registered for DE{number}")
            value, offset = _decode_field(spec, raw, offset)
            fields[number] = value

        if offset != len(raw):
            raise ISO8583CodecError(
                f"Unexpected trailing bytes after DE{field_numbers[-1] if field_numbers else 0}"
            )

        return ISO8583Message(mti=mti, fields=fields)


def _encode_mti(mti: str) -> bytes:
    if not isinstance(mti, str) or len(mti) != 4 or not mti.isascii() or not mti.isdecimal():
        raise ISO8583CodecError("MTI must be exactly four ASCII digits")
    return mti.encode("ascii")


def _decode_mti(raw: bytes) -> str:
    try:
        mti = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ISO8583CodecError("MTI must be ASCII") from exc
    _encode_mti(mti)
    return mti


def _validate_field_number(number: int) -> None:
    if isinstance(number, bool) or not isinstance(number, int) or not 2 <= number <= 128:
        raise ISO8583CodecError("Data element numbers must be integers between 2 and 128")


def _encode_bitmap(fields: Mapping[int, bytes]) -> bytes:
    primary = 0
    secondary = 0
    has_secondary = any(number > 64 for number in fields)
    if has_secondary:
        primary |= 1 << 63

    for number in fields:
        if number <= 64:
            primary |= 1 << (64 - number)
        else:
            secondary |= 1 << (128 - number)

    encoded = primary.to_bytes(8, "big")
    return encoded + (secondary.to_bytes(8, "big") if has_secondary else b"")


def _decode_field_numbers(primary: int, secondary_raw: bytes) -> list[int]:
    numbers: list[int] = []
    for bit in range(64):
        if primary & (1 << (63 - bit)):
            number = bit + 1
            if number != 1:  # DE1 is the secondary bitmap indicator, not data.
                numbers.append(number)

    if secondary_raw:
        secondary = int.from_bytes(secondary_raw, "big")
        for bit in range(64):
            if secondary & (1 << (63 - bit)):
                numbers.append(bit + 65)
    return numbers


def _encode_field(spec: FieldSpec, value: FieldValue) -> bytes:
    raw = _coerce_and_validate_value(spec, value)
    length = len(raw)
    if spec.length_type == "fixed":
        if length != spec.max_length:
            raise ISO8583CodecError(
                f"DE{spec.number} requires exactly {spec.max_length} bytes; received {length}"
            )
        return raw

    if not spec.min_length <= length <= spec.max_length:
        raise ISO8583CodecError(
            f"DE{spec.number} length must be between {spec.min_length} and {spec.max_length}; "
            f"received {length}"
        )
    width = spec.length_prefix_width
    return f"{length:0{width}d}".encode("ascii") + raw


def _decode_field(spec: FieldSpec, payload: bytes, offset: int) -> tuple[FieldValue, int]:
    if spec.length_type == "fixed":
        length = spec.max_length
    else:
        width = spec.length_prefix_width
        prefix_end = offset + width
        if prefix_end > len(payload):
            raise ISO8583CodecError(f"DE{spec.number} length prefix is truncated")
        prefix = payload[offset:prefix_end]
        if not prefix.isascii() or not prefix.isdigit():
            raise ISO8583CodecError(f"DE{spec.number} length prefix must be ASCII digits")
        length = int(prefix)
        if not spec.min_length <= length <= spec.max_length:
            raise ISO8583CodecError(
                f"DE{spec.number} length must be between {spec.min_length} and {spec.max_length}; "
                f"received {length}"
            )
        offset = prefix_end

    end = offset + length
    if end > len(payload):
        raise ISO8583CodecError(f"DE{spec.number} value is truncated")
    raw = payload[offset:end]
    value = _coerce_and_validate_decoded_value(spec, raw)
    return value, end


def _coerce_and_validate_value(spec: FieldSpec, value: FieldValue) -> bytes:
    if spec.data_type == "binary":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise ISO8583CodecError(f"DE{spec.number} requires bytes")
        return bytes(value)

    if not isinstance(value, str):
        raise ISO8583CodecError(f"DE{spec.number} requires a string")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ISO8583CodecError(f"DE{spec.number} must contain ASCII characters") from exc
    _validate_text_bytes(spec, raw)
    return raw


def _coerce_and_validate_decoded_value(spec: FieldSpec, raw: bytes) -> FieldValue:
    if spec.data_type == "binary":
        return raw
    _validate_text_bytes(spec, raw)
    return raw.decode("ascii")


def _validate_text_bytes(spec: FieldSpec, raw: bytes) -> None:
    if spec.data_type == "n" and any(byte < 48 or byte > 57 for byte in raw):
        raise ISO8583CodecError(f"DE{spec.number} must contain only ASCII digits")
    if spec.data_type == "ans" and any(byte < 0x20 or byte > 0x7E for byte in raw):
        raise ISO8583CodecError(f"DE{spec.number} must contain printable ASCII characters")
