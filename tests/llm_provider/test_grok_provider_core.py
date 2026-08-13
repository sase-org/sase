"""Core GrokProvider command/model behavior and Messages stream fixtures."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.ace.tui.thinking.parser import read_codex_thinking
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.grok import GrokProvider
from sase.llm_provider.registry import (
    provider_cli_status_color_map,
    resolve_model_provider,
)
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions

GROK_STREAM_FIXTURES = Path(__file__).parents[1] / "fixtures" / "grok_stream"
_NO_TOOL_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_notool_1.0.3.jsonl"
_TOOLS_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_tools_1.0.3.jsonl"
_ERROR_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_error_1.0.3.jsonl"
_USAGE_ZERO = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}
_GROK_CONTROL_FLAGS = (
    "--no-plan",
    "--no-ask-user",
    "--no-auto-update",
    "--no-leader",
)


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SASE_GROK_PATH",
        "SASE_GROK_LARGE_ARGS",
        "SASE_GROK_SMALL_ARGS",
        "SASE_LLM_LARGE_ARGS",
        "SASE_LLM_SMALL_ARGS",
    ):
        monkeypatch.delenv(name, raising=False)


def _make_fake_grok(
    tmp_path: Path,
    fixture: Path,
    *,
    exit_code: int = 0,
    chunk_size: int = 0,
    expected_prompt: str = "fixture prompt",
) -> Path:
    path = tmp_path / "grok"
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            prompt = sys.stdin.read()
            if prompt != {expected_prompt!r}:
                sys.stderr.write(f"unexpected prompt: {{prompt!r}}\\n")
                sys.exit(64)

            payload = Path({str(fixture)!r}).read_text(encoding="utf-8")
            chunk_size = {chunk_size}
            if chunk_size:
                for index in range(0, len(payload), chunk_size):
                    sys.stdout.write(payload[index:index + chunk_size])
                    sys.stdout.flush()
            else:
                sys.stdout.write(payload)
                sys.stdout.flush()
            sys.exit({exit_code})
            """
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _invoke_and_capture(
    provider: GrokProvider,
    monkeypatch: pytest.MonkeyPatch,
    **invoke_kwargs: object,
) -> tuple[list[str], dict[str, object], MagicMock]:
    monkeypatch.setenv("SASE_GROK_PATH", "/opt/grok/bin/grok")
    with (
        patch(
            "sase.llm_provider.grok.stream_and_parse_messages_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.grok.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.grok.provider_timer"),
    ):
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_stream.return_value = ("response", "", 0, dict(_USAGE_ZERO))
        provider.invoke(
            "test prompt",
            model_tier="large",
            suppress_output=True,
            **invoke_kwargs,  # type: ignore[arg-type]
        )
        return (
            list(mock_popen.call_args.args[0]),
            dict(mock_popen.call_args.kwargs),
            mock_process,
        )


def test_grok_provider_is_llm_provider() -> None:
    assert isinstance(GrokProvider(), LLMProvider)


def test_grok_provider_is_registered_as_an_entry_point() -> None:
    provider, model = resolve_model_provider("grok/grok-4.6")
    assert provider == "grok"
    assert model == "grok-4.6"


def test_grok_known_model_resolves_implicitly() -> None:
    provider, model = resolve_model_provider("grok-4.6")
    assert provider == "grok"
    assert model == "grok-4.6"


def test_grok_provider_metadata_hooks() -> None:
    provider = GrokProvider()
    assert provider.llm_provider_name() == "grok"
    assert provider.llm_provider_short_name() == "grk"
    assert provider.llm_autodetect_cli_name() == "grok"
    assert provider.llm_cli_status_color() == "#00C8D7"
    assert provider.llm_known_model_names() == ["grok-4.6"]
    assert provider.llm_skill_template_context() == {
        "provider_name": "Grok",
        "provider_tool_name": "Grok Build",
        "provider_native_ask_tool": "ask_user_question",
    }
    assert provider.llm_auth_evidence() == {
        "credential_paths": ["~/.grok/auth.json"],
        "api_key_env_vars": ["XAI_API_KEY"],
    }


def test_grok_provider_surface_metadata_is_registered() -> None:
    assert provider_cli_status_color_map()["grok"] == "#00C8D7"
    assert provider_emoji_badge("grok") == "🛰️"
    assert provider_emoji_badge("xai") == "🛰️"


def test_grok_provider_has_no_autodetect_priority() -> None:
    """`grok` is a contested executable name; PATH presence is explicit-only."""
    assert not hasattr(GrokProvider, "llm_autodetect_priority")


def test_grok_install_metadata_declares_npm_package_and_self_update() -> None:
    metadata = GrokProvider().llm_install_metadata()
    assert metadata["manager"] == "npm"
    assert metadata["package"] == "@xai-official/grok"
    assert metadata["scope"] == "global"
    assert metadata["display_name"] == "Grok Build"
    assert metadata["docs_url"] == "https://docs.x.ai/build/overview"
    assert metadata["self_update_argv"] == ["update"]
    assert metadata["latest_version_package"] == "@xai-official/grok"


def test_grok_retry_config_uses_xai_specific_patterns() -> None:
    config = GrokProvider().llm_default_retry_config()
    assert config.max_retries == 3
    assert config.wait_times == [60, 300, 1800]
    assert config.preserve_workspace is True
    assert all("xai" in pattern.lower() for pattern in config.error_patterns)


def test_grok_provider_resolve_model_name_maps_both_tiers_to_grok_46() -> None:
    provider = GrokProvider()
    assert provider.resolve_model_name() == "grok-4.6"
    assert provider.resolve_model_name("large") == "grok-4.6"
    assert provider.resolve_model_name("small") == "grok-4.6"


def test_grok_command_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, kwargs, mock_process = _invoke_and_capture(GrokProvider(), monkeypatch)

    assert cmd[:2] == ["/opt/grok/bin/grok", "--prompt-file"]
    assert cmd[cmd.index("--prompt-file") + 1] == "/dev/stdin"
    assert cmd[cmd.index("--output-format") + 1] == "streaming-messages-json"
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert cmd[cmd.index("--model") + 1] == "grok-4.6"
    assert cmd[cmd.index("--cwd") + 1] == os.getcwd()
    uuid.UUID(cmd[cmd.index("--session-id") + 1])
    for flag in _GROK_CONTROL_FLAGS:
        assert flag in cmd
    assert "--effort" not in cmd
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is True
    mock_process.stdin.write.assert_called_once_with("test prompt")
    mock_process.stdin.close.assert_called_once()


def test_grok_model_override_wins_over_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, _, _ = _invoke_and_capture(
        GrokProvider(), monkeypatch, model_override="grok-next"
    )

    assert cmd[cmd.index("--model") + 1] == "grok-next"
    assert "grok-4.6" not in cmd


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh"])
def test_grok_accepts_the_verified_effort_table(level: str) -> None:
    args = GrokProvider().invocation_option_args(
        LLMInvocationOptions(reasoning_effort=level, explicit=True)
    )
    assert args == ["--effort", level]


@pytest.mark.parametrize("level", ["none", "minimal", "max"])
def test_grok_rejects_explicit_unsupported_effort(level: str) -> None:
    with pytest.raises(LLMInvocationError, match="Grok Build does not support"):
        GrokProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort=level, explicit=True)
        )


@pytest.mark.parametrize("level", ["none", "minimal", "max"])
def test_grok_skips_config_default_unsupported_effort(
    level: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.llm_provider._effort_args"):
        args = GrokProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort=level, explicit=False)
        )
    assert args == []
    assert "Grok Build does not support" in caplog.text


def test_grok_appends_effort_flag_to_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, _, _ = _invoke_and_capture(
        GrokProvider(),
        monkeypatch,
        options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=True),
    )

    assert cmd[cmd.index("--effort") + 1] == "xhigh"


def test_grok_generic_extra_args_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GROK_LARGE_ARGS", "--from-provider-env")
    monkeypatch.setenv("SASE_LLM_LARGE_ARGS", "--max-turns 5")

    cmd, _, _ = _invoke_and_capture(GrokProvider(), monkeypatch)

    assert "--from-provider-env" not in cmd
    assert cmd[cmd.index("--max-turns") + 1] == "5"


def test_grok_provider_specific_extra_args_are_used_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GROK_LARGE_ARGS", "--disable-web-search")

    cmd, _, _ = _invoke_and_capture(GrokProvider(), monkeypatch)

    assert "--disable-web-search" in cmd


def test_grok_missing_executable_names_env_var_and_install_command() -> None:
    with (
        patch("sase.llm_provider.grok.subprocess.Popen", side_effect=FileNotFoundError),
        patch("sase.llm_provider.grok.provider_timer"),
        pytest.raises(FileNotFoundError) as excinfo,
    ):
        GrokProvider().invoke("prompt", model_tier="large", suppress_output=True)

    message = str(excinfo.value)
    assert "SASE_GROK_PATH" in message
    assert "PATH" in message
    assert "sase agent-cli install grok" in message


def test_grok_nonzero_exit_raises_called_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch(
            "sase.llm_provider.grok.stream_and_parse_messages_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.grok.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.grok.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("partial", "boom", 1, {})
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            GrokProvider().invoke("prompt", model_tier="large", suppress_output=True)

    assert excinfo.value.returncode == 1
    assert excinfo.value.output == "partial"
    assert excinfo.value.stderr == "boom"


def test_grok_interrupt_preserves_partial_output_and_continues() -> None:
    provider = GrokProvider()
    prompts: list[str] = []

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        del args, suppress_output
        prompts.append(prompt)
        if len(prompts) == 1:
            provider._pending_interrupt_message = "also update the tests"
            return ("first pass", "", -15, {"input_tokens": 2})
        return ("second pass", "", 0, {"output_tokens": 3})

    with (
        patch("sase.llm_provider.grok.provider_timer"),
        patch.object(GrokProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        result = provider.invoke(
            "original task", model_tier="large", suppress_output=True
        )

    assert prompts[0] == "original task"
    assert "--- Work So Far ---\nfirst pass" in prompts[1]
    assert "--- User Message ---\nalso update the tests" in prompts[1]
    assert result.content == "first pass\n\nsecond pass"
    assert result.usage["input_tokens"] == 2
    assert result.usage["output_tokens"] == 3


def test_grok_provider_replays_no_tool_fixture_and_accumulates_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(
        tmp_path,
        _NO_TOOL_FIXTURE,
        chunk_size=7,
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = GrokProvider().invoke(
        "fixture prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "Grok says hello."
    assert result.usage == {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 4,
        "cache_read_input_tokens": 3,
    }
    assert (artifacts / "live_reply.md").read_text(encoding="utf-8") == (
        "Grok says hello."
    )
    assert (
        json.loads((artifacts / "usage.json").read_text(encoding="utf-8"))[
            "cache_creation_input_tokens"
        ]
        == 4
    )
    blocks = read_codex_thinking(str(artifacts))
    assert blocks is not None
    assert [block.text for block in blocks] == ["Need answer directly."]


def test_grok_provider_replays_tool_fixture_and_writes_grok_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(tmp_path, _TOOLS_FIXTURE)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = GrokProvider().invoke(
        "fixture prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "Created the file and counted it."
    records = [
        json.loads(line)
        for line in (artifacts / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [record["event"] for record in records] == [
        "ToolUse",
        "ToolResult",
        "ToolUse",
        "ToolResult",
    ]
    assert {record["runtime"] for record in records} == {"grok"}
    assert records[0]["tool_name"] == "Bash"
    assert records[0]["tool_input_summary"]["command"] == "wc -c hello.txt"
    assert records[1]["tool_response_summary"]["exit_code"] == 0
    assert records[2]["tool_name"] == "Edit"
    assert records[3]["tool_response_summary"]["file_path"] == (
        "/tmp/grok-fixture/hello.txt"
    )
    blocks = read_codex_thinking(str(artifacts))
    assert blocks is not None
    assert [block.text for block in blocks] == ["Summarize the completed tool work."]


def test_grok_provider_error_fixture_surfaces_errors_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(tmp_path, _ERROR_FIXTURE, exit_code=1)
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        GrokProvider().invoke(
            "fixture prompt", model_tier="large", suppress_output=True
        )

    assert excinfo.value.returncode == 1
    assert "[result] Couldn't set model 'definitely-not-a-model'" in (
        excinfo.value.stderr
    )


def _require_grok_build() -> str:
    candidate = os.environ.get("SASE_GROK_PATH") or shutil.which("grok")
    if candidate is None:
        pytest.skip("Grok Build binary not on PATH")

    result = subprocess.run(
        [candidate, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not result.stdout.startswith("grok "):
        pytest.skip("PATH grok is not Grok Build")
    return candidate


@pytest.mark.parametrize("flag", _GROK_CONTROL_FLAGS)
def test_grok_cli_parse_probe_accepts_control_flag(
    flag: str,
    tmp_path: Path,
) -> None:
    grok = _require_grok_build()
    result = subprocess.run(
        [
            grok,
            "--prompt-file",
            "/dev/stdin",
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            "definitely-not-a-model",
            "--cwd",
            str(tmp_path),
            flag,
        ],
        input="parse-probe",
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "unexpected argument" not in output


def test_grok_cli_parse_probe_rejects_unknown_flag(tmp_path: Path) -> None:
    grok = _require_grok_build()
    result = subprocess.run(
        [
            grok,
            "--prompt-file",
            "/dev/stdin",
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            "definitely-not-a-model",
            "--cwd",
            str(tmp_path),
            "--bogus-flag-xyz",
        ],
        input="parse-probe",
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "unexpected argument '--bogus-flag-xyz'" in output
