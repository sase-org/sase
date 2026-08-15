"""Phase 3 tests: invocation threading + per-provider effort translation.

Covers epic sase-55 Phase 3: resolving the effective reasoning effort
(``resolve_effective_effort``), the shared explicit-vs-default arg translator
(``effort_cli_args``), each provider's CLI argument construction, and threading
the resolved options through ``invoke_agent`` and the commit finalizer.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._effort_args import effort_cli_args
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.agy import AgyProvider
from sase.llm_provider.claude import ClaudeCodeProvider
from sase.llm_provider.codex import CodexProvider
from sase.llm_provider.config import resolve_effective_effort
from sase.llm_provider.opencode import OpenCodeProvider
from sase.llm_provider.qwen import QwenProvider
from sase.llm_provider.types import (
    InvokeResult,
    LLMInvocationError,
    LLMInvocationOptions,
)
from sase.xprompt.directives import PromptDirectives

_CLAUDE_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


# ---------------------------------------------------------------------------
# resolve_effective_effort() precedence
# ---------------------------------------------------------------------------


class TestResolveEffectiveEffort:
    def test_explicit_directive_beats_config_default(self) -> None:
        # An explicit %effort/@effort value wins and is marked explicit, even
        # when a config default exists.
        with patch("sase.llm_provider.config._get_default_effort", return_value="low"):
            effort, explicit = resolve_effective_effort(
                PromptDirectives(reasoning_effort="xhigh")
            )
        assert (effort, explicit) == ("xhigh", True)

    def test_config_default_used_when_no_directive(self) -> None:
        with patch("sase.llm_provider.config._get_default_effort", return_value="high"):
            effort, explicit = resolve_effective_effort(PromptDirectives())
        assert (effort, explicit) == ("high", False)

    def test_none_when_neither_present(self) -> None:
        with patch("sase.llm_provider.config._get_default_effort", return_value=None):
            assert resolve_effective_effort(PromptDirectives()) == (None, False)


# ---------------------------------------------------------------------------
# effort_cli_args() shared explicit-vs-default contract
# ---------------------------------------------------------------------------


_SUPPORTED = {"high": ["--effort", "high"]}


class TestEffortCliArgs:
    def test_no_options_returns_empty(self) -> None:
        assert effort_cli_args(None, provider_label="X", supported=_SUPPORTED) == []

    def test_no_effort_returns_empty(self) -> None:
        opts = LLMInvocationOptions(reasoning_effort=None, explicit=True)
        assert effort_cli_args(opts, provider_label="X", supported=_SUPPORTED) == []

    def test_supported_level_returns_args_copy(self) -> None:
        opts = LLMInvocationOptions(reasoning_effort="high", explicit=True)
        result = effort_cli_args(opts, provider_label="X", supported=_SUPPORTED)
        assert result == ["--effort", "high"]
        # A fresh list is returned so callers cannot mutate the shared map.
        assert result is not _SUPPORTED["high"]

    def test_explicit_unsupported_raises(self) -> None:
        opts = LLMInvocationOptions(reasoning_effort="max", explicit=True)
        with pytest.raises(LLMInvocationError, match="does not support"):
            effort_cli_args(opts, provider_label="X", supported=_SUPPORTED)

    def test_default_unsupported_skips_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        opts = LLMInvocationOptions(reasoning_effort="max", explicit=False)
        with caplog.at_level(logging.WARNING, logger="sase.llm_provider._effort_args"):
            result = effort_cli_args(opts, provider_label="X", supported=_SUPPORTED)
        assert result == []
        assert "does not support" in caplog.text


# ---------------------------------------------------------------------------
# Per-provider CLI command construction
# ---------------------------------------------------------------------------


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_appends_effort_flag(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0, dict(_CLAUDE_USAGE))

    ClaudeCodeProvider().invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=True),
    )

    cmd = mock_popen.call_args.args[0]
    assert "--effort" in cmd
    assert cmd[cmd.index("--effort") + 1] == "xhigh"


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_explicit_unsupported_level_raises(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    # Claude rejects ``none``/``minimal``; an explicit request must error
    # instead of silently launching at the default effort.
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0, dict(_CLAUDE_USAGE))

    with pytest.raises(LLMInvocationError, match="Claude does not support"):
        ClaudeCodeProvider().invoke(
            "test",
            model_tier="large",
            suppress_output=True,
            options=LLMInvocationOptions(reasoning_effort="none", explicit=True),
        )
    mock_popen.assert_not_called()


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_default_unsupported_level_is_skipped(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    # A config-default effort Claude cannot honor is silently skipped (no
    # ``--effort`` flag, no error) so a global default never breaks a run.
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0, dict(_CLAUDE_USAGE))

    result = ClaudeCodeProvider().invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="none", explicit=False),
    )

    cmd = mock_popen.call_args.args[0]
    assert "--effort" not in cmd
    assert result.content == "response"


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_appends_reasoning_effort_config(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    CodexProvider().invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=True),
    )

    cmd = mock_popen.call_args.args[0]
    assert "-c" in cmd
    # Mirrors the SASE_CODEX_LARGE_ARGS escape hatch exactly (quotes included).
    assert 'model_reasoning_effort="xhigh"' in cmd
    assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="xhigh"'


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_explicit_unsupported_level_raises(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    # Codex rejects ``none``/``max``.
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    with pytest.raises(LLMInvocationError, match="Codex does not support"):
        CodexProvider().invoke(
            "test",
            model_tier="large",
            suppress_output=True,
            options=LLMInvocationOptions(reasoning_effort="max", explicit=True),
        )
    mock_popen.assert_not_called()


@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.provider_timer")
def test_opencode_appends_variant_flag(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0, {})

    OpenCodeProvider().invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="high", explicit=True),
    )

    cmd = mock_popen.call_args.args[0]
    assert "--variant" in cmd
    assert cmd[cmd.index("--variant") + 1] == "high"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_explicit_effort_raises_before_launch(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    # Antigravity supports no effort; an explicit request raises before any
    # subprocess is launched.
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    with pytest.raises(LLMInvocationError, match="Antigravity"):
        AgyProvider().invoke(
            "test",
            model_tier="large",
            suppress_output=True,
            options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=True),
        )
    mock_popen.assert_not_called()


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_default_effort_is_skipped_and_runs(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    # A config-default effort agy cannot honor is skipped, and the run proceeds
    # normally with no effort args injected.
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    result = AgyProvider().invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=False),
    )

    cmd = mock_popen.call_args.args[0]
    assert "xhigh" not in cmd
    assert "response" in result.content


def test_qwen_explicit_effort_raises() -> None:
    with pytest.raises(LLMInvocationError, match="Qwen does not support"):
        QwenProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort="high", explicit=True)
        )


# ---------------------------------------------------------------------------
# invoke_agent() threads resolved options to the provider + finalizer
# ---------------------------------------------------------------------------


@patch("sase.llm_provider._invoke.run_commit_finalizer")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_threads_explicit_directive_effort(
    mock_postprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_finalizer: MagicMock,
) -> None:
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider
    mock_finalizer.side_effect = lambda **kw: kw["invoke_result"]

    invoke_agent(
        "prompt",
        agent_type="test",
        suppress_output=True,
        skip_preprocessing=True,
        directives=PromptDirectives(reasoning_effort="xhigh"),
    )

    expected = LLMInvocationOptions(reasoning_effort="xhigh", explicit=True)
    assert mock_provider.invoke.call_args.kwargs["options"] == expected
    # The same options flow into commit finalization so follow-ups keep effort.
    assert mock_finalizer.call_args.kwargs["options"] == expected


@patch("sase.llm_provider.config._get_default_effort", return_value="high")
@patch("sase.llm_provider._invoke.run_commit_finalizer")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_threads_config_default_effort(
    mock_postprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_finalizer: MagicMock,
    mock_default: MagicMock,
) -> None:
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider
    mock_finalizer.side_effect = lambda **kw: kw["invoke_result"]

    invoke_agent(
        "prompt",
        agent_type="test",
        provider_name="claude",
        suppress_output=True,
        skip_preprocessing=True,
        directives=PromptDirectives(),
    )

    # No directive effort → config default, marked non-explicit (best-effort).
    expected = LLMInvocationOptions(reasoning_effort="high", explicit=False)
    assert mock_provider.invoke.call_args.kwargs["options"] == expected


def test_default_effort_reaches_codex_cli() -> None:
    """A launch with no explicit effort passes the config default to Codex."""
    with (
        patch("sase.llm_provider.config._get_default_effort", return_value="xhigh"),
        patch("sase.llm_provider.registry._provider_names", return_value=["codex"]),
        patch(
            "sase.llm_provider._invoke.get_provider",
            return_value=CodexProvider(),
        ),
        patch("sase.llm_provider._invoke.run_commit_finalizer") as mock_finalizer,
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch("sase.llm_provider.codex.provider_timer"),
        patch("sase.llm_provider.codex.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.codex.stream_and_parse_codex_json_output") as stream,
    ):
        mock_popen.return_value = MagicMock()
        stream.return_value = ("response", "", 0)
        mock_finalizer.side_effect = lambda **kw: kw["invoke_result"]

        invoke_agent(
            "prompt",
            agent_type="test",
            suppress_output=True,
            skip_preprocessing=True,
            directives=PromptDirectives(model="codex/gpt-5"),
        )

    cmd = mock_popen.call_args.args[0]
    assert 'model_reasoning_effort="xhigh"' in cmd
