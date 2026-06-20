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
    get_configured_worker_model_entry_for_primary,
    resolve_model_alias,
)
from sase.llm_provider.registry import resolve_model_provider
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
    """Active override makes %model:other resolve to the displaced model."""
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
