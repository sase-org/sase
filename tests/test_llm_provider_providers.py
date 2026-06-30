"""Tests for Claude provider, backward compatibility, base provider, and registry."""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess import stream_process_output
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.claude import ClaudeCodeProvider
from sase.llm_provider.config import (
    _get_configured_worker_models,
    _get_model_aliases,
    coder_model_alias_for_provider,
    default_model_alias_name,
    format_model_directive_value,
    get_configured_worker_model_entry_for_primary,
    model_alias_names,
    resolve_model_alias,
    role_model_directive_value,
)
from sase.llm_provider.registry import (
    resolve_default_alias_provider_model,
    resolve_model_provider,
)
from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model,
)
from sase.llm_provider.types import InvokeResult, ModelTier


# --- subprocess tests ---


def test_stream_process_output_stderr() -> None:
    """Test streaming of process stderr."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('error message\\n')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = stream_process_output(process, suppress_output=True)

    assert stdout == ""
    assert "error message" in stderr
    assert return_code == 0


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_aliases_ignore_invalid_entries(mock_config: MagicMock) -> None:
    """Model aliases are stripped and invalid keys/values are ignored."""
    mock_config.return_value = {
        "model_aliases": {
            " other ": " claude/opus ",
            123: "opus",
            "empty": "   ",
            "bad": ["opus"],
        }
    }

    assert _get_model_aliases() == {"other": "claude/opus"}


@patch("sase.llm_provider.config._registered_provider_names")
@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_alias_names_include_configured_special_and_legacy(
    mock_config: MagicMock,
    mock_providers: MagicMock,
) -> None:
    """``model_alias_names`` unions configured, special, and legacy aliases."""
    mock_config.return_value = {"model_aliases": {"fast": "codex/o4-mini"}}
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
        # legacy reserved (deprecated stubs, retired in epic sase-5d phases 3-4)
        "worker",
        "other",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_format_model_directive_value_adds_alias_prefix(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "fast": "codex/o4-mini",
            "other": "claude/opus",
        }
    }

    assert format_model_directive_value("worker") == "@worker"
    assert format_model_directive_value("other") == "@other"
    assert format_model_directive_value("fast") == "@fast"
    assert format_model_directive_value("@worker") == "@worker"
    assert format_model_directive_value("opus") == "opus"
    assert format_model_directive_value("claude/opus") == "claude/opus"


@patch("sase.llm_provider.config.get_llm_provider_config")
@pytest.mark.parametrize(
    "cfg",
    [
        {},
        {"worker_model": "codex/gpt-5.5"},
        {"worker_models": ""},
        {"worker_models": "   "},
        {"worker_models": 123},
        {"worker_models": ["codex/gpt-5.5"]},
        {
            "worker_models": {
                "": "codex/gpt-5.5",
                "claude": "",
                "codex": "   ",
                123: "opus",
                "bad": ["codex/gpt-5.5"],
            }
        },
    ],
)
def test_get_configured_worker_models_tolerates_missing_blank_and_malformed(
    mock_config: MagicMock,
    cfg: dict[str, object],
) -> None:
    mock_config.return_value = cfg

    assert _get_configured_worker_models() == {}


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_get_configured_worker_models_strips_keys_and_values(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "worker_models": {
            " claude ": " codex/gpt-5.5 ",
            " opus ": " claude/sonnet ",
        }
    }

    assert _get_configured_worker_models() == {
        "claude": "codex/gpt-5.5",
        "opus": "claude/sonnet",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_get_configured_worker_model_entry_uses_specificity_order(
    mock_config: MagicMock,
) -> None:
    """The entry helper returns the most specific matched key and its target."""
    mock_config.return_value = {
        "worker_models": {
            "claude": "qwen/qwen3.6-plus",
            "opus": "agy/flash35h",
            "claude/opus": "codex/gpt-5.5",
        }
    }

    assert get_configured_worker_model_entry_for_primary("claude", "opus") == (
        "claude/opus",
        "codex/gpt-5.5",
    )
    assert get_configured_worker_model_entry_for_primary("opencode", "opus") == (
        "opus",
        "agy/flash35h",
    )
    assert get_configured_worker_model_entry_for_primary("claude", "sonnet") == (
        "claude",
        "qwen/qwen3.6-plus",
    )
    assert get_configured_worker_model_entry_for_primary("codex", "o3") is None


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_alias_handles_chains_and_cycles(
    mock_config: MagicMock,
) -> None:
    """Alias chains resolve, but cycles fall back to the raw input."""
    mock_config.return_value = {
        "model_aliases": {
            "other": "review",
            "review": "opus",
            "a": "b",
            "b": "a",
        }
    }

    assert resolve_model_alias("other") == "opus"
    assert resolve_model_alias("missing") == "missing"
    assert resolve_model_alias("a") == "a"


# --- Model alias policy: role helpers + special aliases (epic sase-5d) ---


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
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_model_alias("default") == "codex/gpt-5.5"
    assert resolve_model_provider("default") == ("codex", "gpt-5.5")


def test_default_alias_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent a configured ``default``, ``@default`` is the provider tier default."""
    _mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("default") == "claude/opus"
    assert resolve_model_provider("default") == ("claude", "opus")


def test_coder_alias_chains_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``coder`` defaults to ``@default`` when not explicitly configured."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_model_alias("coder") == "codex/gpt-5.5"
    assert resolve_model_provider("coder") == ("codex", "gpt-5.5")


def test_provider_coder_alias_chains_to_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<provider>_coder`` defaults to ``@coder`` -> ``@default`` when unset."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    # codex is a registered provider, so codex_coder is an implicit alias.
    assert resolve_model_alias("codex_coder") == "codex/gpt-5.5"
    assert resolve_model_provider("codex_coder") == ("codex", "gpt-5.5")


def test_epic_role_aliases_chain_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """epic_creator / epic_lander / phase_worker default to ``@default``."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    for role in ("epic_creator", "epic_lander", "phase_worker"):
        assert resolve_model_alias(role) == "codex/gpt-5.5"


def test_configured_role_alias_shadows_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-configured role alias wins over the implicit ``@default`` fallback."""
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "default": "codex/gpt-5.5",
                "phase_worker": "claude/sonnet",
            },
        },
    )

    assert resolve_model_alias("phase_worker") == "claude/sonnet"
    assert resolve_model_alias("coder") == "codex/gpt-5.5"  # still @default


def test_alias_value_may_reference_another_alias_with_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values can reference other aliases with the ``@`` marker."""
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "fast": "codex/o4-mini",
                "claude_coder": "@fast",
            },
        },
    )

    assert resolve_model_alias("claude_coder") == "codex/o4-mini"
    assert resolve_model_provider("claude_coder") == ("codex", "o4-mini")


def test_alias_at_reference_cycle_falls_back_to_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cyclic ``@`` reference chain fails closed to the original input."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"x": "@y", "y": "@x"}},
    )

    assert resolve_model_alias("x") == "x"


def test_self_referential_default_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``default: @default`` self-cycle is detected and never recurses."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "@default"}},
    )

    # Fails closed to the input rather than recursing on the special branch.
    assert resolve_model_alias("default") == "default"


def test_unknown_at_reference_resolves_to_bare_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling ``@`` reference to a non-alias resolves to the bare token."""
    _mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    # `@nope` references an alias that is neither configured nor special.
    assert resolve_model_alias("@nope") == "nope"


def test_worker_and_other_retained_as_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker``/``other`` remain valid legacy stubs until phases 3-4 retire them.

    Phase 1 keeps the worker lane functional because the plan/bead emit sites
    and worker-override UI that still produce ``@worker``/``@other`` are owned by
    epic sase-5d phases 3-4. They stay in the alias-name policy so directive
    validation does not reject prompts those phases still render.
    """
    from sase.llm_provider.config import special_model_alias_names

    _mock_provider_config(monkeypatch, {"provider": "claude"})

    names = special_model_alias_names()
    assert {"worker", "other"} <= names
    # The new role aliases are advertised alongside the legacy ones.
    assert {"default", "coder", "epic_creator", "epic_lander", "phase_worker"} <= names


# --- @default launch semantics: no-directive default resolution ---


def test_effective_default_uses_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-directive launch routes through a configured ``@default`` alias."""
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_default_alias_provider_model() == ("codex", "gpt-5.5")
    assert resolve_effective_default_provider_model() == ("codex", "gpt-5.5")


def test_effective_default_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no configured ``default``, the provider tier default is used."""
    _mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_default_alias_provider_model() == ("claude", "opus")
    assert resolve_default_alias_provider_model("small") == ("claude", "sonnet")
    assert resolve_effective_default_provider_model() == ("claude", "opus")


def test_active_override_wins_over_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active primary override still wins the new-launch-default slot."""
    from sase.llm_provider.temporary_override import set_temporary_override

    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    set_temporary_override("agy/Gemini 3.5 Pro", 3600.0, source="test")

    # The override wins for the effective launch default ...
    assert resolve_effective_default_provider_model() == ("agy", "Gemini 3.5 Pro")
    # ... but an explicit @default reference still resolves to the configured
    # target (the override only wins the no-directive slot).
    assert resolve_default_alias_provider_model() == ("codex", "gpt-5.5")
    assert resolve_model_alias("default") == "codex/gpt-5.5"


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_explicit_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at explicit provider/model syntax."""
    mock_config.return_value = {"model_aliases": {"other": "claude/opus"}}

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_bare_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at a known bare model name."""
    mock_config.return_value = {"model_aliases": {"other": "opus"}}

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_agy_display_name_alias(
    mock_config: MagicMock,
) -> None:
    """A model alias pointing at ``agy/<exact display name>`` routes to agy.

    This is the regression guard for the readable ``#agy_flash``/``#m_agy_flash``
    presets: the alias token expands to an explicit ``agy/<display name>`` target
    whose space-and-paren-laden model survives intact, so the launch routes to
    the Antigravity provider rather than falling back to the configured default.
    """
    mock_config.return_value = {
        "provider": "codex",
        "model_aliases": {"agy_flash": "agy/Gemini 3.5 Flash (High)"},
    }

    assert resolve_model_provider("agy_flash") == ("agy", "Gemini 3.5 Flash (High)")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_unknown_agy_token_falls_back(
    mock_config: MagicMock,
) -> None:
    """Without the alias, ``agy_flash`` keeps the documented default fallback.

    When the ``agy_flash`` alias is missing from ``model_aliases`` (the broken
    state this work fixes), the bare token is unknown to every provider, so
    resolution returns ``(None, ...)`` and the launch falls back to the
    configured default provider. The doctor guard (not a hard error) is what
    surfaces this degradation.
    """
    mock_config.return_value = {"provider": "codex", "model_aliases": {}}

    assert resolve_model_provider("agy_flash") == (None, "agy_flash")


def test_worker_alias_resolves_effective_worker_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "codex/gpt-5.5"}},
    )

    assert resolve_model_provider("worker") == ("codex", "gpt-5.5")


def test_worker_alias_shadows_configured_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {"claude": "codex/gpt-5.5"},
            "model_aliases": {"worker": "claude/sonnet"},
        },
    )

    assert resolve_model_provider("worker") == ("codex", "gpt-5.5")


def test_worker_alias_falls_through_to_primary_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_provider("worker") == ("claude", "opus")


# --- "other" alias override-aware tests ---


def _mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    """Patch the config lookup at every module that imported it directly."""
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )


def test_other_alias_uses_snapshot_when_override_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active override makes the internal ``other`` alias resolve to the displaced model."""
    from sase.llm_provider.temporary_override import set_temporary_override

    # Configured alias says claude/sonnet; configured default is claude → opus.
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    set_temporary_override("codex/o3", 3600.0, source="test")

    # Snapshot captured claude/opus (the default that was displaced).
    assert resolve_model_provider("other") == ("claude", "opus")


def test_other_alias_uses_snapshot_even_without_configured_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override-driven snapshot fires even with no model_aliases.other configured."""
    from sase.llm_provider.temporary_override import set_temporary_override

    _mock_provider_config(monkeypatch, {"provider": "claude"})

    set_temporary_override("codex/o3", 3600.0, source="test")

    assert resolve_model_provider("other") == ("claude", "opus")


def test_other_alias_falls_back_to_config_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an active override, the configured alias target wins."""
    _mock_provider_config(monkeypatch, {"model_aliases": {"other": "claude/sonnet"}})

    assert resolve_model_provider("other") == ("claude", "sonnet")


def test_other_alias_falls_back_when_override_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After clear, "other" reverts to the configured alias target."""
    from sase.llm_provider.temporary_override import (
        clear_temporary_override,
        set_temporary_override,
    )

    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    set_temporary_override("codex/o3", 3600.0, source="test")
    clear_temporary_override()

    assert resolve_model_provider("other") == ("claude", "sonnet")


def test_other_alias_legacy_state_falls_back_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy state file (no snapshot fields) falls back to the configured alias."""
    import json
    import time

    from sase.llm_provider.temporary_override import _state_path

    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "codex",
                "model": "o3",
                "raw_model": "codex/o3",
                "created_at": time.time(),
                "expires_at": time.time() + 3600,
                "source": "ace",
            }
        ),
        encoding="utf-8",
    )

    # Snapshot fields absent → short-circuit declines → configured alias wins.
    assert resolve_model_provider("other") == ("claude", "sonnet")


# --- Backward compatibility tests ---


def test_llm_provider_invoke_agent_importable() -> None:
    """Test that invoke_agent can be imported from llm_provider."""
    from sase.llm_provider import invoke_agent as llm_invoke_agent

    assert callable(llm_invoke_agent)


# --- claude.py tests ---


def test_claude_provider_is_llm_provider() -> None:
    """Test that ClaudeCodeProvider is a proper LLMProvider subclass."""
    provider = ClaudeCodeProvider()
    assert isinstance(provider, LLMProvider)


@patch.dict(os.environ, {"SASE_CLAUDE_SMALL_ARGS": "--max-tokens 1000"})
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CLAUDE_SMALL_ARGS env var is parsed into command."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = (
        "response",
        "",
        0,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )

    provider = ClaudeCodeProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--max-tokens" in cmd
    assert "1000" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--include-hook-events" not in cmd


def test_base_provider_resolve_model_name_returns_unknown() -> None:
    """Test that the base LLMProvider.resolve_model_name() returns 'unknown'."""

    class MinimalProvider(LLMProvider):
        def invoke(
            self,
            prompt: str,
            *,
            model_tier: ModelTier,
            suppress_output: bool = False,
            model_override: str | None = None,
        ) -> InvokeResult:
            return InvokeResult(content="")

    provider = MinimalProvider()
    assert provider.resolve_model_name() == "unknown"


def test_claude_provider_resolve_model_name() -> None:
    """Test that ClaudeCodeProvider.resolve_model_name() returns correct names."""
    provider = ClaudeCodeProvider()
    assert provider.resolve_model_name() == "opus"
    assert provider.resolve_model_name("large") == "opus"
    assert provider.resolve_model_name("small") == "sonnet"


# --- registry auto-detect tests ---


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_codex(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that codex is auto-detected when claude is absent."""
    mock_which.side_effect = lambda name: "/usr/bin/codex" if name == "codex" else None

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "codex"


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_priority(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that claude wins over codex when both are available."""
    mock_which.side_effect = lambda name: f"/usr/bin/{name}"

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "claude"


@patch(
    "sase.llm_provider.registry._llm_metadata_payload",
    return_value={
        "autodetect_candidates": [
            {"priority": 30, "provider": "agy", "cli_name": "agy"}
        ]
    },
)
@patch("sase.llm_provider.registry.shutil.which", return_value=None)
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_does_not_select_missing_agy_fallback(
    mock_config: MagicMock,
    mock_which: MagicMock,
    mock_payload: MagicMock,
) -> None:
    """Antigravity is not selected unless the `agy` CLI is discoverable."""
    from sase.llm_provider.registry import get_default_provider_name

    with pytest.raises(RuntimeError, match="No LLM provider is available"):
        get_default_provider_name()


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_provider_raises_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that ClaudeCodeProvider raises CalledProcessError on non-zero exit."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = (
        "",
        "some error",
        1,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )

    provider = ClaudeCodeProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "some error"
