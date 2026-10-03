"""Tests for macro swarm edge cases and processor integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.macro_swarm import (
    _MacroSwarmUsageError,
    expand_macro_swarms_with_metadata,
)
from sase.macro.processor import process_macro_references

from tests._macro_swarm_helpers import patch_catalog, patch_vcs_patterns, xp


def expand_macro_swarms(segments: list[str], **kwargs) -> list[str]:
    return [
        segment.prompt
        for segment in expand_macro_swarms_with_metadata(segments, **kwargs)
    ]


def test_expand_depth_cap() -> None:
    """A self-referential macro swarm blows the depth cap."""
    catalog = {"loopy": xp("loopy", "step\n---\n#!loopy")}
    with patch_catalog(catalog):
        with pytest.raises(ValueError, match="exceeded max depth"):
            expand_macro_swarms(["#!loopy"], max_depth=3)


def test_expand_passthrough_unknown_name() -> None:
    """Unknown macro names pass through unchanged (handled later by processor)."""
    with patch_catalog({}):
        out = expand_macro_swarms(["#not_in_catalog"])
    assert out == ["#not_in_catalog"]


def test_expand_no_hashtag_fast_path() -> None:
    """Segments without '#' should not even need the catalog."""
    out = expand_macro_swarms(["plain segment", "another plain"])
    assert out == ["plain segment", "another plain"]


def test_expand_empty_subsegments_dropped() -> None:
    """Empty or whitespace-only sub-segments are dropped."""
    catalog = {"x": xp("x", "a\n---\n   \n---\nb")}
    with patch_catalog(catalog):
        out = expand_macro_swarms(["#!x"])
    assert out == ["a", "b"]


def test_expand_mixes_passthrough_and_expansion() -> None:
    """When a list contains a plain segment plus a macro swarm ref, both are handled."""
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    with patch_catalog(catalog):
        out = expand_macro_swarms(["plain", "#!three"])
    assert out == ["plain", "a", "b", "c"]


def test_fenced_macro_swarm_references_are_ignored() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    segment = "Example:\n```\n#three\n#!three\n```"
    with patch_catalog(catalog):
        out = expand_macro_swarms([segment])
    assert out == [segment]


def test_fenced_vcs_prefixed_macro_swarm_references_are_ignored() -> None:
    catalog = {"three": xp("three", "a\n---\nb\n---\nc")}
    segment = "Example:\n```\n#gh:sase #!three\n```"
    with patch_catalog(catalog), patch_vcs_patterns():
        out = expand_macro_swarms([segment])
    assert out == [segment]


def test_process_macro_references_uses_first_multi_prompt_part() -> None:
    catalog = {"three": xp("three", "first\n---\nsecond\n---\nthird")}
    with patch("sase.macro.processor.get_all_macros", return_value=catalog):
        out = process_macro_references("before #three after")
    assert out == "before first after"
