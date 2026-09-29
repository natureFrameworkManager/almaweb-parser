#!/usr/bin/env python3
"""Regression tests for the text-separator / prerequisite fixes.

Runs with plain Python (no pytest dependency):

    python analysis/test_text_structure.py

Exits non-zero if any assertion fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.parser.module_parser import _split_prerequisite, parse_prerequisites  # noqa: E402
from src.parser.utils import text_with_structure  # noqa: E402


def _tag(html: str):
    return BeautifulSoup(html, "html.parser").find(True)


def test_structure_preserved_and_not_glued() -> None:
    tag = _tag("<div>Zielgruppe: D/KE <br/>Prüfungsleistungen erbringen.<br/>Ende</div>")
    assert text_with_structure(tag) == "Zielgruppe: D/KE\nPrüfungsleistungen erbringen.\nEnde"
    # inline boundaries must become a space, not glue words together
    assert text_with_structure(_tag("<div><span>A</span><span>B</span></div>")) == "A B"
    # a single line stays a single line
    assert text_with_structure(_tag("<div>nur eine Zeile</div>")) == "nur eine Zeile"
    print("ok: text_with_structure")


def test_prerequisites_keep_all_keys() -> None:
    value = (
        "Staatsexamen Lehramt an Gymnasien Französisch: Abschluss der Module 04-007-1601\n"
        "Staatsexamen Lehramt an Oberschulen Französisch: Abschluss der Module 04-007-1602"
    )
    result = parse_prerequisites(value)
    assert set(result) == {
        "Staatsexamen Lehramt an Gymnasien Französisch",
        "Staatsexamen Lehramt an Oberschulen Französisch",
    }, result
    assert result["Staatsexamen Lehramt an Oberschulen Französisch"] == "Abschluss der Module 04-007-1602"
    print("ok: prerequisites keep all keys")


def test_prerequisites_colon_inside_parentheses() -> None:
    value = (
        "Master of Science Betriebswirtschaftslehre (ab WS 2017/18) "
        "(Schwerpunkt: Nachhaltigkeitsmanagement): keine"
    )
    result = parse_prerequisites(value)
    assert result == {
        "Master of Science Betriebswirtschaftslehre (ab WS 2017/18) "
        "(Schwerpunkt: Nachhaltigkeitsmanagement)": "keine"
    }, result
    assert _split_prerequisite("keine Doppelpunkt Zeile") is None
    print("ok: colon inside parentheses")


def test_prerequisites_no_general_overwrite() -> None:
    result = parse_prerequisites("ohne Angabe\nnoch eine allgemeine Zeile")
    assert result == {"allgemein": "ohne Angabe noch eine allgemeine Zeile"}, result
    # duplicate context merges instead of dropping
    assert parse_prerequisites("X: a\nX: b") == {"X": "a b"}
    print("ok: allgemein / duplicate keys")


def main() -> int:
    test_structure_preserved_and_not_glued()
    test_prerequisites_keep_all_keys()
    test_prerequisites_colon_inside_parentheses()
    test_prerequisites_no_general_overwrite()
    print("all tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
