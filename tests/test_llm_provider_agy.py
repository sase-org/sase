"""Tests for AgyProvider (Antigravity CLI) invoke/command construction."""

import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.agy import AgyProvider, _AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.registry import resolve_model_provider
from sase.llm_provider.types import LLMInvocationError


def test_agy_provider_is_llm_provider() -> None:
    provider = AgyProvider()
    assert isinstance(provider, LLMProvider)


def test_agy_provider_resolve_model_name() -> None:
    provider = AgyProvider()
    assert provider.resolve_model_name() == "Gemini 3.5 Flash (High)"
    assert provider.resolve_model_name("large") == "Gemini 3.5 Flash (High)"
    assert provider.resolve_model_name("small") == "Gemini 3.5 Flash (Low)"


def test_agy_provider_metadata_hooks() -> None:
    provider = AgyProvider()
    assert provider.llm_provider_name() == "agy"
    assert provider.llm_provider_short_name() == "agy"
    assert provider.llm_autodetect_cli_name() == "agy"
    assert provider.llm_autodetect_priority() == 30
    assert provider.llm_skill_deploy_subpath() == ".gemini/antigravity-cli"
    assert provider.llm_cli_status_color() != "#4285F4"  # not Gemini blue
    context = provider.llm_skill_template_context()
    assert context["provider_name"] == "Antigravity"
    assert context["provider_tool_name"] == "Antigravity CLI"
    # Exact `agy models` display names with spaces/parens are preserved.
    assert "Gemini 3.5 Flash (High)" in provider.llm_known_model_names()
    assert "Claude Opus 4.6 (Thinking)" in provider.llm_known_model_names()
    aliases = provider.llm_model_short_aliases()
    assert aliases["Gemini 3.5 Flash (High)"] == "flash35h"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "agy"
    assert "--print-timeout" in cmd
    assert cmd[cmd.index("--print-timeout") + 1] == "24h"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "Gemini 3.5 Flash (High)"
    assert "--dangerously-skip-permissions" in cmd
    # The prompt is the value of --print and must be the final pair.
    assert cmd[-2] == "--print"
    assert cmd[-1] == "test prompt"
    assert mock_popen.call_args.kwargs["text"] is True
    assert "stdin" not in mock_popen.call_args.kwargs


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_model_override_preserves_spaces(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        model_override="Claude Opus 4.6 (Thinking)",
    )

    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "Claude Opus 4.6 (Thinking)"
    assert "Gemini 3.5 Flash (High)" not in cmd


@patch.dict(os.environ, {"SASE_AGY_PATH": "/opt/antigravity/bin/agy"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_uses_sase_agy_path(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_args.args[0][0] == "/opt/antigravity/bin/agy"


@patch.dict(os.environ, {"SASE_AGY_PRINT_TIMEOUT": "45m"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_print_timeout_env_override(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--print-timeout") + 1] == "45m"


@patch.dict(os.environ, {"SASE_AGY_SMALL_ARGS": "--sandbox"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--sandbox" in cmd
    assert cmd[cmd.index("--model") + 1] == "Gemini 3.5 Flash (Low)"


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic val1",
        "SASE_AGY_LARGE_ARGS": "--agy val2",
    },
)
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_generic_env_args_precedence(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--generic" in cmd
    assert "val1" in cmd
    assert "--agy" not in cmd


@patch("sase.llm_provider.agy.subprocess.Popen")
def test_agy_provider_missing_executable_error_mentions_resolution_paths(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)
    mock_popen.side_effect = FileNotFoundError("missing")

    provider = AgyProvider()
    with pytest.raises(FileNotFoundError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    message = str(exc_info.value)
    assert "SASE_AGY_PATH" in message
    assert "PATH" in message


@patch("sase.llm_provider.agy.subprocess.Popen")
def test_agy_provider_rejects_oversized_print_prompt_before_spawn(
    mock_popen: MagicMock,
) -> None:
    provider = AgyProvider()
    prompt = "x" * (_AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT + 1)

    with pytest.raises(LLMInvocationError) as exc_info:
        provider.invoke(prompt, model_tier="large", suppress_output=True)

    mock_popen.assert_not_called()
    message = str(exc_info.value)
    assert "argv transport" in message
    assert "stdin/prompt-file" in message
    assert "Antigravity CLI" in message


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_raises_called_process_error_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("", "agy failed", 2)

    provider = AgyProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "agy failed"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_interrupt_resume_prompt_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    provider = AgyProvider()
    calls = {"n": 0}

    def _stream_side_effect(
        process: object, suppress_output: bool = False, clean_ansi: bool = False
    ) -> tuple[str, str, int]:
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the interrupt monitor firing during the first cycle.
            provider._pending_interrupt_message = "please also add logging"
            return ("partial work", "", 0)
        return ("final answer", "", 0)

    mock_stream.side_effect = _stream_side_effect

    result = provider.invoke("original task", model_tier="large", suppress_output=True)

    assert calls["n"] == 2
    second_prompt = mock_popen.call_args_list[1].args[0][-1]
    assert "original task" in second_prompt
    assert "--- Work So Far ---" in second_prompt
    assert "partial work" in second_prompt
    assert "--- User Message ---" in second_prompt
    assert "please also add logging" in second_prompt
    assert result.content == "partial work\n\nfinal answer"
    assert result.usage is None


def test_agy_model_resolution_preserves_nested_provider_model() -> None:
    # Explicit provider/model syntax keeps the full model name (with spaces)
    # after the first slash.
    assert resolve_model_provider("agy/Gemini 3.5 Flash (High)") == (
        "agy",
        "Gemini 3.5 Flash (High)",
    )
    # Bare known model name resolves to the agy provider.
    assert resolve_model_provider("Gemini 3.5 Flash (High)") == (
        "agy",
        "Gemini 3.5 Flash (High)",
    )


def test_agy_provider_invokes_fake_cli_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import sys

            argv = sys.argv
            if "--print-timeout" not in argv or "--model" not in argv:
                sys.stderr.write("missing required flags\\n")
                sys.exit(64)
            if "--dangerously-skip-permissions" not in argv:
                sys.stderr.write("missing skip-permissions\\n")
                sys.exit(64)
            if argv[-2] != "--print":
                sys.stderr.write(f"prompt not behind --print: {argv!r}\\n")
                sys.exit(64)
            if argv[-1] != "fake agy prompt":
                sys.stderr.write(f"unexpected prompt argv: {argv[-1]!r}\\n")
                sys.exit(64)

            print("agy fake ok", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = AgyProvider().invoke(
        "fake agy prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "agy fake ok"
    # No stable token accounting in plain-stdout mode.
    assert result.usage is None
    assert (artifacts / "live_reply.md").read_text().strip() == "agy fake ok"


def test_agy_provider_writes_live_reply_but_no_structured_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 5 parity gate: plain stdout is the supported MVP artifact path.

    ``agy`` exposes no stable machine-readable contract, so the provider must
    write ``live_reply.md`` like every other provider while emitting NO
    structured artifacts. It must never fabricate ``tool_calls.jsonl``,
    ``usage.json``, or thinking rows from human display text — doing so would
    make the provider lie about tool calls and usage.
    """
    fake_agy = tmp_path / "agy"
    # A reply whose prose looks tool-shaped (glyphs, "Running"/"tool" words)
    # must NOT be scraped into a structured tool-call artifact.
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("● Running tool: Bash(echo hi)", flush=True)
            print("final agy answer", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = AgyProvider().invoke("do work", model_tier="large", suppress_output=True)

    # The plain-stdout reply is captured verbatim, including tool-shaped prose.
    assert "final agy answer" in result.content
    assert "Running tool" in result.content
    # No stable token accounting in plain-stdout mode: do not lie about usage.
    assert result.usage is None

    # live_reply.md is the supported MVP artifact and is written.
    live_reply = artifacts / "live_reply.md"
    assert live_reply.is_file()
    assert "final agy answer" in live_reply.read_text(encoding="utf-8")

    # No malformed / fabricated structured artifacts are created.
    assert not (artifacts / "tool_calls.jsonl").exists()
    assert not (artifacts / "usage.json").exists()
    assert not (artifacts / "codex_thinking.jsonl").exists()


def test_agy_provider_fake_cli_no_shell_interpolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A prompt full of shell-significant characters must reach the CLI as a
    # single, untouched argv element (proving subprocess uses an argv list,
    # not a shell string).
    tricky_prompt = "he said \"hi\"; rm -rf /\nline two\twith 'quotes' & $(echo no)"
    expected_file = tmp_path / "expected_prompt.txt"
    expected_file.write_text(tricky_prompt, encoding="utf-8")

    fake_agy = tmp_path / "agy"
    fake_agy.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import sys

            expected = open(os.environ["EXPECTED_PROMPT_FILE"], encoding="utf-8").read()
            if sys.argv[-1] != expected:
                sys.stderr.write(f"prompt was mangled: {sys.argv[-1]!r}\\n")
                sys.exit(65)
            print("no interpolation", flush=True)
            """
        )
    )
    fake_agy.chmod(0o755)
    monkeypatch.setenv("SASE_AGY_PATH", str(fake_agy))
    monkeypatch.setenv("EXPECTED_PROMPT_FILE", str(expected_file))

    result = AgyProvider().invoke(
        tricky_prompt, model_tier="large", suppress_output=True
    )

    assert result.content == "no interpolation"
