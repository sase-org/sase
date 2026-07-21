"""Tests for parsing and presenting LLM provider model alias configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.llm_provider.config import (
    _get_model_aliases,
    format_model_directive_value,
    get_builtin_model_aliases,
    get_custom_model_aliases,
    model_alias_bucket,
    model_alias_bucket_description,
    model_alias_bucket_names,
    model_alias_config_source,
    model_alias_description,
    model_alias_names,
)


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_aliases_ignore_invalid_entries(mock_config: MagicMock) -> None:
    """Model aliases are stripped and invalid keys/values are ignored."""
    mock_config.return_value = {
        "model_aliases": {
            "builtin": {
                " other ": " claude/opus ",
                123: "opus",
                "empty": "   ",
                "bad": ["opus"],
            }
        }
    }

    assert _get_model_aliases() == {"other": "claude/opus"}
    assert get_builtin_model_aliases() == {"other": "claude/opus"}


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_custom_model_aliases_parse_defensively(mock_config: MagicMock) -> None:
    """Custom aliases skip malformed entries but tolerate missing descriptions."""
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                " blogger ": {
                    "model": " claude/opus ",
                    "description": "Draft blog posts.",
                },
                "no_description": {"model": "codex/o3"},
                "blank_model": {"model": "  ", "description": "Nope."},
                "bad": "claude/opus",
                123: {"model": "claude/opus", "description": "Nope."},
            }
        }
    }

    assert get_custom_model_aliases() == {
        "blogger": "claude/opus",
        "no_description": "codex/o3",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_custom_model_alias_buckets_parse_defensively(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                " research_a ": {
                    "model": "codex/gpt-5.6-sol",
                    "description": "Lead.",
                    "bucket": " research ",
                },
                "research_b": {
                    "model": "claude/opus",
                    "description": "Second opinion.",
                    "bucket": " ",
                },
                "research_c": {
                    "model": "codex/gpt-5.6-sol",
                    "description": "Extra.",
                },
                "bad": {
                    "model": "codex/o3",
                    "description": "Bad tag.",
                    "bucket": 123,
                },
            },
            "buckets": {
                "research": {"description": " Research roles. "},
                "blank": {"description": " "},
            },
        }
    }

    assert model_alias_bucket("research_a") == "research"
    assert model_alias_bucket("research_b") is None
    assert model_alias_bucket("research_c") is None
    assert model_alias_bucket("bad") is None
    assert model_alias_bucket_names() == {"research"}
    assert model_alias_bucket_description("research") == "Research roles."
    assert model_alias_bucket_description("blank") is None
    assert model_alias_bucket_description("missing") is None


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_custom_model_aliases_merge_over_legacy(mock_config: MagicMock) -> None:
    """The described custom map is authoritative on name collisions."""
    mock_config.return_value = {
        "model_aliases": {
            "builtin": {"blogger": "claude/haiku", "coder": "@default"},
            "custom": {
                "blogger": {
                    "model": "claude/opus",
                    "description": "Draft blog posts.",
                }
            },
        },
    }

    assert _get_model_aliases()["blogger"] == "claude/opus"
    assert model_alias_config_source("blogger") == "custom"
    assert model_alias_config_source("coder") == "builtin"


@patch("sase.llm_provider.config._registered_provider_names")
@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_alias_description_builtin_and_custom(
    mock_config: MagicMock,
    mock_providers: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                "blogger": {
                    "model": "claude/opus",
                    "description": "Draft blog posts.",
                },
                "legacy_gap": {"model": "codex/o3"},
            }
        }
    }
    mock_providers.return_value = ["claude"]

    assert model_alias_description("default").startswith("Model used")
    assert model_alias_description("big_epic_lander") == (
        "Epic land agents selected for plans at or above the configured "
        "phase-count threshold."
    )
    assert model_alias_description("phase_worker") == (
        "Shared fallback for medium bead phase agents and explicit uses."
    )
    assert model_alias_description("medium_phase_worker") == (
        "Medium bead phase agents that plan before implementation."
    )
    assert model_alias_description("smartest") == (
        "Highest-capability model used automatically by large phase agents."
    )
    assert model_alias_description("cheapest") == (
        "Cheap load-balanced pool for high-volume agents."
    )
    assert model_alias_description("claude_coder") == (
        "Coder follow-up agents for plans authored by claude."
    )
    assert model_alias_description("blogger") == "Draft blog posts."
    assert model_alias_description("legacy_gap") is None


@patch("sase.llm_provider.config._registered_provider_names")
@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_alias_names_include_configured_and_special(
    mock_config: MagicMock,
    mock_providers: MagicMock,
) -> None:
    """``model_alias_names`` unions configured and special role aliases.

    The legacy ``worker``/``other`` reserved aliases were retired with the
    worker lane (epic sase-5d phase 4), so they are no longer implicit.
    """
    mock_config.return_value = {"model_aliases": {"builtin": {"fast": "codex/o4-mini"}}}
    mock_providers.return_value = ["claude", "codex"]

    assert model_alias_names() == {
        # user-configured
        "fast",
        # fixed implicit role aliases
        "default",
        "coder",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "smartest",
        "cheapest",
        # per-provider coder aliases
        "claude_coder",
        "codex_coder",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_format_model_directive_value_adds_alias_prefix(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "builtin": {
                "fast": "codex/o4-mini",
                "other": "claude/opus",
            }
        }
    }

    # ``other`` is only an alias here because it is user-configured; ``worker``
    # is no longer special and is left bare.
    assert format_model_directive_value("worker") == "worker"
    assert format_model_directive_value("other") == "@other"
    assert format_model_directive_value("fast") == "@fast"
    assert format_model_directive_value("@fast") == "@fast"
    assert format_model_directive_value("opus") == "opus"
    assert format_model_directive_value("claude/opus") == "claude/opus"
