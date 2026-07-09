"""Integration-facing agent status formatting helpers."""

from __future__ import annotations

from sase.integrations.agent_status_groups import (
    agent_status_bucket_glyph,
    status_bucket_header,
)


def test_agent_status_bucket_glyph_known_bucket() -> None:
    assert agent_status_bucket_glyph("Running") == "▶"


def test_agent_status_bucket_glyph_unknown_bucket() -> None:
    assert agent_status_bucket_glyph("Custom") == ""


def test_status_bucket_header_includes_glyph_and_count() -> None:
    assert status_bucket_header("Running", 3) == "▶ Running (3)"


def test_status_bucket_header_omits_empty_glyph_prefix() -> None:
    assert status_bucket_header("Custom", 2) == "Custom (2)"
