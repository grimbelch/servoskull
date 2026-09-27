"""Unit tests for config.identity_name (run: python -m pytest tests)."""

import pytest

from core import config


@pytest.mark.parametrize("raw, expected", [
    ("Sean", "Sean"),
    ("  tara  ", "tara"),
    ("Mary-Jane O'Brien", "Mary-Jane O'Brien"),
    ("R2 D2", "R2 D2"),
    ("Sean\n", "Sean"),
    ("x" * 40, "x" * 40),
])
def test_accepts_ordinary_names(raw, expected):
    assert config.identity_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "..", ".", "", None, "../etc", "a/b", "a\\b", "-Sean", "12345", "x" * 41, "Sean; rm -rf",
])
def test_rejects_paths_and_junk(raw):
    assert config.identity_name(raw) is None
