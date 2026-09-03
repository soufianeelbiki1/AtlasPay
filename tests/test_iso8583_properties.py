"""Property-based invariants for the ISO 8583 profile codec."""

from hypothesis import given
from hypothesis import strategies as st

from app.iso8583 import ISO8583Codec, ISO8583Message


@st.composite
def _messages(draw) -> ISO8583Message:
    """Build valid messages while varying every profile encoding boundary."""
    amount = draw(st.integers(min_value=0, max_value=999_999_999_999))
    fields: dict[int, str | bytes] = {
        2: str(draw(st.integers(min_value=1, max_value=10**19 - 1))),
        3: "000000",
        4: f"{amount:012d}",
        7: "0101123456",
        11: "123456",
        37: "ABC123456789",
        39: "00",
        41: "TERM0001",
        42: "MERCHANT0000001",
        49: "840",
        52: b"12345678",
        55: draw(st.binary(min_size=1, max_size=128)),
    }
    if draw(st.booleans()):
        fields[70] = "301"
    return ISO8583Message(mti="0100", fields=fields)


@given(message=_messages())
def test_iso8583_round_trip_preserves_profile_values(message: ISO8583Message) -> None:
    """Encoding and decoding is lossless for all supported value shapes."""
    codec = ISO8583Codec()

    encoded = codec.encode(message)
    decoded = codec.decode(encoded)

    assert decoded == message
