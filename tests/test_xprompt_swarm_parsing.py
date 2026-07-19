"""Tests for xprompt swarm parsing helpers."""

from __future__ import annotations

from sase.agent.xprompt_swarm import (
    _extract_top_level_xprompt_reference,
    xprompt_has_segment_separators,
)

from tests._xprompt_swarm_helpers import patch_vcs_patterns, xp

# --- xprompt_has_segment_separators ---


def test_has_separators_simple() -> None:
    assert xprompt_has_segment_separators(xp("x", "a\n---\nb")) is True


def test_has_separators_none() -> None:
    assert xprompt_has_segment_separators(xp("x", "just one segment")) is False


def test_has_separators_inside_fence_ignored() -> None:
    body = "before\n```\ncode\n---\nmore\n```\nafter"
    assert xprompt_has_segment_separators(xp("x", body)) is False


# --- extract_top_level_xprompt_reference ---


def test_extract_simple_reference() -> None:
    call = _extract_top_level_xprompt_reference("#foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.marker.value == "#"
    assert call.positional_args == []


def test_extract_standalone_reference() -> None:
    call = _extract_top_level_xprompt_reference("#!foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.marker.value == "#!"


def test_extract_with_args() -> None:
    call = _extract_top_level_xprompt_reference("#!foo(a, b)", {"foo"})
    assert call is not None
    assert call.positional_args == ["a", "b"]


def test_extract_with_named_args() -> None:
    call = _extract_top_level_xprompt_reference("#foo(name=val)", {"foo"})
    assert call is not None
    assert call.named_args == {"name": "val"}


def test_extract_with_leading_directives() -> None:
    call = _extract_top_level_xprompt_reference("%id:custom\n%wait\n#foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.leading_directives == ["%id:custom", "%wait"]


def test_extract_with_same_line_directives_before_vcs_ref() -> None:
    with patch_vcs_patterns():
        call = _extract_top_level_xprompt_reference(
            "%i:custom %model:opus #gh:sase #!foo", {"foo"}
        )
    assert call is not None
    assert call.name == "foo"
    assert call.leading_directives == ["%i:custom", "%model:opus"]
    assert call.leading_vcs_ref_text == "#gh:sase"


def test_extract_returns_none_for_prose() -> None:
    assert _extract_top_level_xprompt_reference("Hello #foo and stuff", {"foo"}) is None


def test_extract_returns_none_for_trailing_prose() -> None:
    assert _extract_top_level_xprompt_reference("#foo and stuff", {"foo"}) is None


def test_extract_returns_none_when_name_unknown() -> None:
    assert _extract_top_level_xprompt_reference("#foo", {"bar"}) is None


def test_extract_colon_arg() -> None:
    call = _extract_top_level_xprompt_reference("#foo:hello", {"foo"})
    assert call is not None
    assert call.positional_args == ["hello"]


def test_extract_with_leading_vcs_ref() -> None:
    with patch_vcs_patterns():
        call = _extract_top_level_xprompt_reference("#gh:sase #!foo", {"foo"})
    assert call is not None
    assert call.name == "foo"
    assert call.leading_vcs_ref_text == "#gh:sase"
