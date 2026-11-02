"""P5.4 (ADR-029): sealed inbound text. Bound to its message, readable only with a listed key, never plaintext."""

import json

from app.contacts.addresses import parse_keyring
from app.whatsapp import content

KEYS = parse_keyring("k2:" + "b" * 40 + ",k1:" + "a" * 40)
AAD = content.aad("00000000-0000-0000-0000-000000000001", "wamid.SYN1")


def test_round_trip_under_the_newest_key_and_no_plaintext_in_the_record() -> None:
    sealed = content.seal(KEYS, AAD, "fees ke baare mein batayein — شکریہ")
    assert sealed["key_id"] == "k2" and "fees" not in json.dumps(sealed) and sealed["truncated"] is False
    assert content.unseal(KEYS, AAD, sealed) == "fees ke baare mein batayein — شکریہ"


def test_another_message_tampering_or_a_missing_key_cannot_read_it() -> None:
    sealed = content.seal(KEYS, AAD, "hello")
    assert content.unseal(KEYS, content.aad("00000000-0000-0000-0000-000000000001", "wamid.SYN2"), sealed) is None
    flipped = dict(sealed, ct=("A" if sealed["ct"][0] != "A" else "B") + sealed["ct"][1:])
    assert content.unseal(KEYS, AAD, flipped) is None
    assert content.unseal(parse_keyring("k3:" + "c" * 40), AAD, sealed) is None  # rotated out
    assert content.unseal(None, AAD, sealed) is None
    assert content.unseal(KEYS, AAD, {"key_id": "k2"}) is None and content.unseal(KEYS, AAD, "junk") is None


def test_an_older_listed_key_still_reads_and_long_or_broken_text_is_bounded() -> None:
    old = content.seal(parse_keyring("k1:" + "a" * 40), AAD, "old")
    assert content.unseal(KEYS, AAD, old) == "old"
    long = content.seal(KEYS, AAD, "x" * 5000)
    assert long["truncated"] is True and content.unseal(KEYS, AAD, long) == "x" * content.MAX_TEXT_CHARS
    assert content.clean("a\x00b\ud800c") == "a�b�c"
