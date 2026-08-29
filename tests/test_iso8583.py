import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.iso8583 import (
    DEFAULT_FIELD_SPECS,
    ISO8583Codec,
    ISO8583CodecError,
    ISO8583Message,
)

codec = ISO8583Codec()


def _digits(length: int) -> st.SearchStrategy[str]:
    return st.text(
        alphabet=st.characters(min_codepoint=48, max_codepoint=57), min_size=length, max_size=length
    )


def _printable(length: int) -> st.SearchStrategy[str]:
    return st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        min_size=length,
        max_size=length,
    )


@st.composite
def iso_messages(draw: st.DrawFn) -> ISO8583Message:
    fields: dict[int, str | bytes] = {
        3: draw(_digits(6)),
        11: draw(_digits(6)),
    }
    optional_values: dict[int, st.SearchStrategy[str | bytes]] = {
        2: st.one_of(
            st.none(), _digits(1).flatmap(lambda first: _digits(18).map(lambda rest: first + rest))
        ),
        4: st.one_of(st.none(), _digits(12)),
        37: st.one_of(st.none(), _printable(12)),
        55: st.one_of(st.none(), st.binary(min_size=1, max_size=64)),
        70: st.one_of(st.none(), _digits(3)),
    }
    for number, strategy in optional_values.items():
        value = draw(strategy)
        if value is not None:
            fields[number] = value
    return ISO8583Message(
        mti=draw(st.sampled_from(("0200", "0400", "0800", "0810"))), fields=fields
    )


@given(iso_messages())
def test_valid_messages_round_trip(message: ISO8583Message) -> None:
    assert codec.decode(codec.encode(message)) == message


def test_secondary_bitmap_is_emitted_for_de70() -> None:
    message = ISO8583Message("0800", {70: "001"})

    encoded = codec.encode(message)

    assert len(encoded) == 4 + 8 + 8 + 3
    assert encoded[4] & 0x80  # Primary bitmap announces the secondary bitmap.
    assert encoded[12] & 0x04  # DE70 is bit six of the secondary bitmap.
    assert codec.decode(encoded) == message


def test_llvar_and_lllvar_prefixes_count_the_encoded_value() -> None:
    message = ISO8583Message("0200", {2: "123456", 55: b"\x9f\x02\x06"})

    encoded = codec.encode(message)

    data_start = 4 + 8
    assert encoded[data_start : data_start + 2] == b"06"
    assert encoded[data_start + 2 : data_start + 8] == b"123456"
    assert encoded[data_start + 8 : data_start + 11] == b"003"
    assert codec.decode(encoded) == message


def test_fixed_fields_and_numeric_values_are_strict() -> None:
    with pytest.raises(ISO8583CodecError, match="DE3 requires exactly 6"):
        codec.encode(ISO8583Message("0200", {3: "123"}))

    with pytest.raises(ISO8583CodecError, match="DE3 must contain only ASCII digits"):
        codec.encode(ISO8583Message("0200", {3: "12A456"}))

    with pytest.raises(ISO8583CodecError, match="MTI must be exactly four ASCII digits"):
        codec.encode(ISO8583Message("200", {3: "000000"}))


def test_decode_rejects_invalid_length_prefix_and_trailing_bytes() -> None:
    bitmap_for_de2 = bytes.fromhex("4000000000000000")
    with pytest.raises(ISO8583CodecError, match="length prefix must be ASCII digits"):
        codec.decode(b"0200" + bitmap_for_de2 + b"A1")

    with pytest.raises(ISO8583CodecError, match="value is truncated"):
        codec.decode(b"0200" + bitmap_for_de2 + b"19")

    bitmap_with_secondary = bytes.fromhex("8000000000000000")
    with pytest.raises(ISO8583CodecError, match="Secondary bitmap indicator"):
        codec.decode(b"0200" + bitmap_with_secondary)

    valid = codec.encode(ISO8583Message("0200", {3: "000000"}))
    with pytest.raises(ISO8583CodecError, match="Unexpected trailing bytes"):
        codec.decode(valid + b"x")


def test_unregistered_fields_fail_closed() -> None:
    with pytest.raises(ISO8583CodecError, match="No field specification registered for DE5"):
        codec.encode(ISO8583Message("0200", {5: "000000000000"}))

    custom_codec = ISO8583Codec({70: DEFAULT_FIELD_SPECS[70]})
    with pytest.raises(ISO8583CodecError, match="No field specification registered for DE3"):
        custom_codec.decode(codec.encode(ISO8583Message("0800", {3: "000000"})))
