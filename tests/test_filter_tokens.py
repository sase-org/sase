"""Unit coverage for shared filter-token helpers."""

from __future__ import annotations

import pytest

from sase.filter_tokens import toggle_flag_token


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "monitor"),
        ("   ", "monitor"),
        ("monitor", "-monitor"),
        ("-monitor", ""),
        ("MONITOR", "-monitor"),
        ("-Monitor", ""),
    ],
)
def test_toggle_flag_token_cycles_from_empty(text: str, expected: str) -> None:
    assert toggle_flag_token(text, "monitor") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('"just check" -min:300', '"just check" -min:300 monitor'),
        ('"just check" -min:300 monitor', '"just check" -min:300 -monitor'),
        ('"just check" -min:300 -monitor', '"just check" -min:300'),
        ('"just check" monitor -min:300', '"just check" -monitor -min:300'),
        ('"just check" -monitor -min:300', '"just check" -min:300'),
        ("name:sync", "name:sync monitor"),
        ("name:sync monitor", "name:sync -monitor"),
        ("name:sync -monitor", "name:sync"),
    ],
)
def test_toggle_flag_token_rewrites_only_the_flag_among_other_terms(
    text: str, expected: str
) -> None:
    assert toggle_flag_token(text, "monitor") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("monitor:true", "-monitor"),
        ("monitor:false", ""),
        ("-monitor:true", ""),
        ("-monitor:false", "-monitor"),
        ("name:sync monitor:false", "name:sync"),
        ("name:sync monitor:true", "name:sync -monitor"),
        ("name:sync -monitor:true", "name:sync"),
        ("Monitor:True", "-monitor"),
        ("MONITOR:FALSE", ""),
    ],
)
def test_toggle_flag_token_normalizes_explicit_boolean_spellings(
    text: str, expected: str
) -> None:
    assert toggle_flag_token(text, "monitor") == expected


def test_toggle_flag_token_is_quote_aware() -> None:
    assert toggle_flag_token('"monitor"', "monitor") == '"monitor" monitor'
    assert toggle_flag_token('-"monitor"', "monitor") == '-"monitor" monitor'
    assert (
        toggle_flag_token('"just check" "monitor"', "monitor")
        == '"just check" "monitor" monitor'
    )


def test_toggle_flag_token_preserves_surrounding_whitespace_on_replace() -> None:
    assert toggle_flag_token("sidecar:false  monitor  since:24h", "monitor") == (
        "sidecar:false  -monitor  since:24h"
    )
    assert toggle_flag_token("sidecar:false  -monitor  since:24h", "monitor") == (
        "sidecar:false  since:24h"
    )
