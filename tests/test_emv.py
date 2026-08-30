import pytest

from app.emv import EMVTLVError, decode_de55, decode_tvr, find_tags, parse_ber_tlv


def test_de55_parses_known_and_unknown_tags_without_guessing() -> None:
    payload = bytes.fromhex(
        "9F0206000000012500"
        "5F2A020504"
        "95050000008000"
        "DF0102AABB"
    )

    items = decode_de55(payload)

    assert [item.tag for item in items] == ["9F02", "5F2A", "95", "DF01"]
    assert items[0].name == "Amount, Authorised (Numeric)"
    assert items[-1].name is None
    assert items[-1].value == bytes.fromhex("AABB")


def test_constructed_templates_are_parsed_recursively() -> None:
    payload = bytes.fromhex("77119F02060000000125009F3602002A")

    (template,) = parse_ber_tlv(payload)

    assert template.tag == "77"
    assert template.constructed is True
    assert [child.tag for child in template.children] == ["9F02", "9F36"]
    assert find_tags((template,), "9f36")[0].value == bytes.fromhex("002A")


def test_duplicate_tags_are_preserved() -> None:
    items = parse_ber_tlv(bytes.fromhex("9F360200019F36020002"))

    matches = find_tags(items, "9F36")

    assert [item.value for item in matches] == [bytes.fromhex("0001"), bytes.fromhex("0002")]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (bytes.fromhex("9F"), "tag is truncated"),
        (bytes.fromhex("9F0280"), "indefinite BER lengths"),
        (bytes.fromhex("9F02810100"), "long-form length is non-canonical"),
        (bytes.fromhex("9F02060000"), "value is truncated"),
        (bytes.fromhex("00"), "padding bytes"),
    ],
)
def test_malformed_tlv_fails_closed(payload: bytes, message: str) -> None:
    with pytest.raises(EMVTLVError, match=message):
        parse_ber_tlv(payload)


def test_tvr_decodes_named_failure_bits() -> None:
    tvr = decode_tvr(bytes.fromhex("A000008040"))

    assert tvr.hex == "A000008040"
    assert tvr.failures == (
        "Offline data authentication was not performed",
        "ICC data missing",
        "Transaction exceeds floor limit",
        "Issuer authentication failed",
    )


def test_tvr_requires_exactly_five_bytes() -> None:
    with pytest.raises(EMVTLVError, match="exactly 5 bytes"):
        decode_tvr(bytes.fromhex("00000000"))
