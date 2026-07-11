"""Tests for LLM provider model alias configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.config import (
    _get_model_aliases,
    coder_model_alias_for_provider,
    default_model_alias_name,
    format_model_directive_value,
    get_builtin_model_aliases,
    get_custom_model_aliases,
    model_alias_bucket,
    model_alias_bucket_description,
    model_alias_bucket_names,
    model_alias_config_source,
    model_alias_description,
    model_alias_names,
    resolve_model_alias,
    role_model_directive_value,
)
from sase.llm_provider.registry import resolve_model_provider
from tests.llm_provider._provider_config_helpers import mock_provider_config


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
        "epic_creator",
        "epic_lander",
        "phase_worker",
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


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_alias_handles_chains_and_cycles(
    mock_config: MagicMock,
) -> None:
    """Alias chains resolve, but cycles fall back to the raw input."""
    mock_config.return_value = {
        "model_aliases": {
            "builtin": {
                "other": "review",
                "review": "opus",
                "a": "b",
                "b": "a",
            }
        }
    }

    assert resolve_model_alias("other") == "opus"
    assert resolve_model_alias("missing") == "missing"
    assert resolve_model_alias("a") == "a"


def test_role_alias_helpers() -> None:
    """The role-alias name/directive helpers return the documented strings."""
    assert default_model_alias_name() == "default"
    assert coder_model_alias_for_provider("codex") == "codex_coder"
    assert coder_model_alias_for_provider(" claude ") == "claude_coder"
    assert role_model_directive_value("phase_worker") == "@phase_worker"
    assert role_model_directive_value("default") == "@default"


def test_default_alias_resolves_to_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``default`` resolves through its explicit provider/model."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("default") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("default") == ("codex", "gpt-5.6-sol")


def test_default_alias_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent a configured ``default``, ``@default`` is the provider tier default."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("default") == "claude/opus"
    assert resolve_model_provider("default") == ("claude", "opus")


def test_coder_alias_chains_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``coder`` defaults to ``@default`` when not explicitly configured."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_model_alias("coder") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("coder") == ("codex", "gpt-5.6-sol")


def test_provider_coder_alias_chains_to_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<provider>_coder`` defaults to ``@coder`` -> ``@default`` when unset."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    # codex is a registered provider, so codex_coder is an implicit alias.
    assert resolve_model_alias("codex_coder") == "codex/gpt-5.6-sol"
    assert resolve_model_provider("codex_coder") == ("codex", "gpt-5.6-sol")


def test_provider_coder_alias_follows_configured_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured ``<provider>_coder`` inherits a configured ``coder``.

    Regression: the implicit provider-coder fallback must reference ``@coder``
    itself, not ``coder``'s resolved fallback. Otherwise configuring ``coder``
    once fails to flow through to the provider-specific coder lanes and they
    skip straight to ``@default``.
    """
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "coder": "claude/sonnet",
                }
            },
        },
    )

    # codex_coder is unconfigured, so it inherits @coder (claude/sonnet) rather
    # than skipping straight to @default (codex/gpt-5.6-sol).
    assert resolve_model_alias("codex_coder") == "claude/sonnet"
    assert resolve_model_provider("codex_coder") == ("claude", "sonnet")


def test_configured_provider_coder_shadows_generic_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``<provider>_coder`` still wins over the generic ``coder``."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "coder": "claude/sonnet",
                    "codex_coder": "codex/o3",
                }
            },
        },
    )

    assert resolve_model_alias("codex_coder") == "codex/o3"
    assert resolve_model_provider("codex_coder") == ("codex", "o3")


def test_epic_role_aliases_chain_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """epic_creator / epic_lander / phase_worker default to ``@default``."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    for role in ("epic_creator", "epic_lander", "phase_worker"):
        assert resolve_model_alias(role) == "codex/gpt-5.6-sol"


def test_configured_role_alias_shadows_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-configured role alias wins over the implicit ``@default`` fallback."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "phase_worker": "claude/sonnet",
                }
            },
        },
    )

    assert resolve_model_alias("phase_worker") == "claude/sonnet"
    assert resolve_model_alias("coder") == "codex/gpt-5.6-sol"  # still @default


def test_alias_value_may_reference_another_alias_with_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values can reference other aliases with the ``@`` marker."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "fast": "codex/o4-mini",
                    "claude_coder": "@fast",
                }
            },
        },
    )

    assert resolve_model_alias("claude_coder") == "codex/o4-mini"
    assert resolve_model_provider("claude_coder") == ("codex", "o4-mini")


def test_alias_at_reference_cycle_falls_back_to_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cyclic ``@`` reference chain fails closed to the original input."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"x": "@y", "y": "@x"}},
        },
    )

    assert resolve_model_alias("x") == "x"


def test_self_referential_default_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``default: @default`` self-cycle is detected and never recurses."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "@default"}},
        },
    )

    # Fails closed to the input rather than recursing on the special branch.
    assert resolve_model_alias("default") == "default"


def test_unknown_at_reference_resolves_to_bare_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling ``@`` reference to a non-alias resolves to the bare token."""
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    # `@nope` references an alias that is neither configured nor special.
    assert resolve_model_alias("@nope") == "nope"


def test_worker_and_other_no_longer_special_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker``/``other`` are no longer implicit aliases after phase 4.

    The worker lane was retired in epic sase-5d phase 4, so the legacy reserved
    ``worker``/``other`` aliases are gone from the implicit policy and only the
    role aliases remain. ``worker``/``other`` resolve now only when a user
    defines them as ordinary configured aliases.
    """
    from sase.llm_provider.config import _special_model_alias_names

    mock_provider_config(monkeypatch, {"provider": "claude"})

    names = _special_model_alias_names()
    assert "worker" not in names
    assert "other" not in names
    # The role aliases are the implicit policy now.
    assert {"default", "coder", "epic_creator", "epic_lander", "phase_worker"} <= names


def test_unconfigured_worker_and_other_resolve_to_bare_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without explicit config, ``worker``/``other`` are plain unknown tokens."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("worker") == "worker"
    assert resolve_model_alias("other") == "other"
