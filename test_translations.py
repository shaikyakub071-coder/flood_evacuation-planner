"""
test_translations.py - checks the English / Telugu / Hindi text.

Run from the project folder with:
    pytest -v
"""

import re
import string

from translations import LANGS, TEXT, translate


def holes(text):
    """Names of the {holes} inside a phrase."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_language_is_listed():
    assert set(LANGS) == set(TEXT) == {"en", "te", "hi"}


def test_every_language_has_every_key():
    for lang in ("te", "hi"):
        assert set(TEXT[lang]) == set(TEXT["en"]), lang


def test_no_empty_translations():
    for lang, words in TEXT.items():
        for key, text in words.items():
            assert text.strip(), f"{lang}.{key} is empty"


def test_placeholders_match_english():
    for lang in ("te", "hi"):
        for key, text in TEXT[lang].items():
            assert holes(text) == holes(TEXT["en"][key]), f"{lang}.{key}"


def test_telugu_and_hindi_really_differ_from_english():
    for lang, block in (("te", "\u0c00-\u0c7f"), ("hi", "\u0900-\u097f")):
        assert re.search(f"[{block}]", TEXT[lang]["find_btn"]), lang


def test_translate_fills_placeholders():
    assert translate("en", "confirm_send", n=5) == \
        "Confirm: Send 5 people to this shelter"
    assert "5" in translate("hi", "confirm_send", n=5)


def test_unknown_language_falls_back_to_english():
    assert translate("xx", "find_btn") == TEXT["en"]["find_btn"]


def test_unknown_key_returns_the_key():
    assert translate("te", "no_such_key") == "no_such_key"
