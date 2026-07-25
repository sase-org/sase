"""Tests for agent list widget helpers."""

from sase.ace.tui.widgets._agent_list_helpers import short_model_name


def test_short_model_name_recognizes_claude_opus() -> None:
    """Claude Opus IDs should render with the compact opus label."""
    assert short_model_name("claude-opus-5") == "opus"


def test_short_model_name_recognizes_claude_fable() -> None:
    """Claude Fable IDs should render with the compact fable label."""
    assert short_model_name("claude-fable-5") == "fable"
