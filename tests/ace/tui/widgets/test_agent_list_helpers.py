"""Tests for agent list widget helpers."""

from sase.ace.tui.widgets._agent_list_helpers import short_model_name


def test_short_model_name_recognizes_claude_opus() -> None:
    """Claude Opus IDs should render with the compact opus label."""
    assert short_model_name("claude-opus-5") == "opus"


def test_short_model_name_recognizes_claude_fable() -> None:
    """Claude Fable IDs should render with the compact fable label."""
    assert short_model_name("claude-fable-5") == "fable"


def test_short_model_name_recognizes_claude_haiku_5_5() -> None:
    """Claude Haiku 5.5 IDs should render with the compact haiku label."""
    assert short_model_name("claude-haiku-5-5") == "haiku"


def test_short_model_name_recognizes_gemini_argon() -> None:
    """Gemini 4 Argon IDs should render with the compact argon label."""
    assert short_model_name("gemini-4-argon-high") == "argon"


def test_short_model_name_recognizes_muse_wonder() -> None:
    """Muse Wonder model IDs should render with the compact wonder label."""
    assert short_model_name("muse-wonder-1.0") == "wonder"


def test_short_model_name_prefers_wonder_full() -> None:
    """Muse Wonder Full IDs should keep their more specific compact label."""
    assert short_model_name("muse-wonder-full-1.0-contributor") == "wonder-full"


def test_short_model_name_keeps_muse_spark_generic() -> None:
    """Muse Spark should not become a generic label for unrelated Spark models."""
    assert short_model_name("muse-spark-1.3") == "muse"
