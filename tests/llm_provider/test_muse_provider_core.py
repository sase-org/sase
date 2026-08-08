"""Core MuseProvider command/model behavior and JSONL stream-parser tests.

The stream tests run against sanitized captures from Muse Code release
``0.1.0-R708.1``. The fixtures are release-keyed on purpose: when Muse renames
a payload type, the right fix is a re-capture, not a loosened assertion.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.base import LLMProvider
from sase.llm_provider.muse import MuseProvider
from sase.llm_provider.registry import resolve_model_provider
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from sase.llm_provider._subprocess_muse import MUSE_USAGE_ERROR_NOTE

_FIXTURES = Path(__file__).parent / "fixtures"
_READ_TOOL_FIXTURE = _FIXTURES / "muse_exec_read_tool_R708.1.jsonl"
_WRITE_BASH_FIXTURE = _FIXTURES / "muse_exec_write_bash_tools_R708.1.jsonl"

_MUSE_MODELS = [
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
]


def _run_fixture_stream(
    payload: str,
    *,
    exit_code: int = 0,
    stderr: str = "",
    suppress_output: bool = True,
) -> tuple[str, str, int, dict[str, int]]:
    """Replay *payload* on a real subprocess's stdout and parse the stream."""
    script = (
        "import sys\n"
        "sys.stdout.write(sys.argv[1])\n"
        "sys.stderr.write(sys.argv[2])\n"
        "sys.exit(int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload, stderr, str(exit_code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return stream_and_parse_muse_json_output(process, suppress_output=suppress_output)


def _envelope(payload_type: str, payload: dict[str, object], **envelope: object) -> str:
    record = {
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": payload_type,
        "payload_schema_version": 1,
        "payload": payload,
    }
    record.update(envelope)
    return json.dumps(record) + "\n"


# ---------------------------------------------------------------------------
# Identity, registration, and model mapping
# ---------------------------------------------------------------------------


def test_muse_provider_is_llm_provider() -> None:
    assert isinstance(MuseProvider(), LLMProvider)


def test_muse_provider_is_registered_as_an_entry_point() -> None:
    provider, model = resolve_model_provider("muse/muse-spark-1.2")
    assert provider == "muse"
    assert model == "muse-spark-1.2"


def test_muse_known_models_resolve_implicitly() -> None:
    provider, model = resolve_model_provider("muse-spark-1.2-contributor")
    assert provider == "muse"
    assert model == "muse-spark-1.2-contributor"


def test_muse_provider_metadata_hooks() -> None:
    provider = MuseProvider()
    assert provider.llm_provider_name() == "muse"
    assert provider.llm_provider_short_name() == "mus"
    assert provider.llm_autodetect_cli_name() == "muse"
    assert provider.llm_skill_deploy_subpath() == ".config/muse"
    assert provider.llm_cli_status_color() == "#0064E0"
    assert provider.llm_known_model_names() == _MUSE_MODELS
    assert provider.llm_model_short_aliases() == {
        "muse-spark-1.2": "spark12",
        "muse-spark-1.2-contributor": "spark12c",
        "muse-spark-1.1": "spark11",
    }
    context = provider.llm_skill_template_context()
    assert context["provider_name"] == "Muse Code"
    assert context["provider_tool_name"] == "Muse Code"
    assert context["provider_native_ask_tool"] == "request_user_input"
    assert provider.llm_auth_evidence() == {
        "credential_paths": ["$MUSE_AUTH_PATH", "~/.config/muse/auth.json"],
        "api_key_env_vars": ["META_API_KEY"],
    }


def test_muse_provider_has_no_autodetect_priority() -> None:
    """`muse` is a generic binary name; PATH presence must not win the default."""
    assert not hasattr(MuseProvider, "llm_autodetect_priority")


def test_muse_provider_resolve_model_name_never_routes_a_tier_to_contributor() -> None:
    """Both tiers map to the paid model; `small` is what `@cheap` reaches for."""
    provider = MuseProvider()
    assert provider.resolve_model_name() == "muse-spark-1.2"
    assert provider.resolve_model_name("large") == "muse-spark-1.2"
    assert provider.resolve_model_name("small") == "muse-spark-1.2"


def test_muse_install_metadata_declares_channel_and_script_install() -> None:
    metadata = MuseProvider().llm_install_metadata()
    assert metadata["manager"] == "script"
    assert metadata["display_name"] == "Muse Code"
    assert metadata["version_argv"] == ["--version"]
    assert metadata["version_compare"] == "exact"
    assert (
        metadata["latest_version_url"]
        == "https://api.meta.ai/muse-code/channels/muse-stable"
    )
    assert metadata["latest_version_json_field"] == "version"
    assert metadata["self_update_argv"] == ["--version"]
    assert metadata["self_update_env"] == {"MUSE_SYNC_UPDATE": "1"}
    assert metadata["install_script_url"] == "https://dev.meta.ai/install.sh"
    assert metadata["install_env"] == {"MUSE_UPGRADE_MODE": "1"}


def test_muse_version_regex_extracts_the_release_id() -> None:
    """`muse --version` prints `Muse Code 0.1.0 (0.1.0-R708.1)`."""
    import re

    pattern = MuseProvider().llm_install_metadata()["version_regex"]
    assert isinstance(pattern, str)
    match = re.search(pattern, "Muse Code 0.1.0 (0.1.0-R708.1)")
    assert match is not None
    assert match.group("version") == "0.1.0-R708.1"


def test_muse_setup_fallback_is_published_for_doctor() -> None:
    from sase.doctor.checks_providers import _PROVIDER_SETUP_FALLBACKS

    fallback = _PROVIDER_SETUP_FALLBACKS["muse"]
    assert fallback["tool"] == "Muse Code"
    assert "META_API_KEY" in fallback["auth"]


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def _invoke_and_capture(
    provider: MuseProvider,
    **invoke_kwargs: object,
) -> tuple[list[str], dict[str, object]]:
    """Invoke *provider* against mocked subprocess plumbing and return the argv."""
    with (
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.muse.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.muse.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("response", "", 0, {})
        provider.invoke(
            "test prompt",
            model_tier="large",
            suppress_output=True,
            **invoke_kwargs,  # type: ignore[arg-type]
        )
        return list(mock_popen.call_args.args[0]), dict(mock_popen.call_args.kwargs)


def test_muse_command_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_MUSE_SANDBOX", raising=False)
    monkeypatch.delenv("SASE_LLM_LARGE_ARGS", raising=False)
    monkeypatch.delenv("SASE_MUSE_LARGE_ARGS", raising=False)
    monkeypatch.setenv("SASE_MUSE_PATH", "/opt/muse/bin/muse")

    cmd, kwargs = _invoke_and_capture(MuseProvider())

    assert cmd[:3] == ["/opt/muse/bin/muse", "exec", "--json"]
    assert cmd[cmd.index("--workspace") + 1] == os.getcwd()
    assert cmd[cmd.index("--model") + 1] == "muse-spark-1.2"
    assert "--trust-workspace" in cmd
    assert "--disable-approval" in cmd
    assert "--disable-sandbox" in cmd
    assert "--user-input-auto-resolve" in cmd
    assert "--no-foreign-personal-context" in cmd
    # No resolved effort means no flag at all; Muse then applies its own `high`.
    assert "--reasoning-effort" not in cmd
    # `-w/--worktree` already defaults to off and the isolation flag is a no-op.
    assert "--worktree" not in cmd
    assert "-w" not in cmd
    assert "--subagent-worktree-isolation" not in cmd
    # `exec` reserves stdin for `--api-key-stdin`.
    assert "stdin" not in kwargs
    assert kwargs["text"] is True
    assert kwargs["env"]["MUSE_NO_AUTO_UPDATE"] == "1"


def test_muse_command_passes_a_session_id_and_prompt_file() -> None:
    import uuid

    cmd, _ = _invoke_and_capture(MuseProvider())

    session_id = cmd[cmd.index("--session-id") + 1]
    # SASE generates the session id so the artifacts phase can find the log.
    assert uuid.UUID(session_id)

    prompt_file = cmd[cmd.index("--prompt-file") + 1]
    assert prompt_file.endswith(".md")


def test_muse_prompt_file_is_written_0o600_and_removed() -> None:
    seen: dict[str, object] = {}

    def _capture(
        process: object, suppress_output: bool = False
    ) -> tuple[str, str, int, dict[str, int]]:
        del process, suppress_output
        path = Path(seen["prompt_file"])  # type: ignore[arg-type]
        seen["existed"] = path.exists()
        seen["mode"] = path.stat().st_mode & 0o777
        seen["content"] = path.read_text(encoding="utf-8")
        return ("response", "", 0, {})

    with (
        patch("sase.llm_provider.muse.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.muse.provider_timer"),
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output",
            side_effect=_capture,
        ),
    ):
        mock_popen.return_value = MagicMock()

        def _record(*args: object, **kwargs: object) -> MagicMock:
            argv = list(args[0])  # type: ignore[arg-type]
            seen["prompt_file"] = argv[argv.index("--prompt-file") + 1]
            return MagicMock()

        mock_popen.side_effect = _record
        MuseProvider().invoke(
            "secret prompt body", model_tier="large", suppress_output=True
        )

    assert seen["existed"] is True
    assert seen["mode"] == 0o600
    assert seen["content"] == "secret prompt body"
    assert not Path(seen["prompt_file"]).exists()  # type: ignore[arg-type]


def test_muse_hardened_sandbox_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_MUSE_SANDBOX", "on")

    cmd, _ = _invoke_and_capture(MuseProvider())

    assert "--disable-sandbox" not in cmd
    assert cmd[cmd.index("--sandbox-network") + 1] == "enabled"


def test_muse_model_override_wins_over_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_MUSE_SANDBOX", raising=False)

    cmd, _ = _invoke_and_capture(
        MuseProvider(), model_override="muse-spark-1.2-contributor"
    )

    assert cmd[cmd.index("--model") + 1] == "muse-spark-1.2-contributor"


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("none", "none"),
        ("minimal", "minimal"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        # Muse rejects `max` by name; `ultra` is its top level.
        ("max", "ultra"),
    ],
)
def test_muse_covers_every_canonical_effort_level(level: str, expected: str) -> None:
    args = MuseProvider().invocation_option_args(
        LLMInvocationOptions(reasoning_effort=level, explicit=True)
    )
    assert args == ["--reasoning-effort", expected]


def test_muse_effort_flag_is_absent_without_a_resolved_effort() -> None:
    assert MuseProvider().invocation_option_args(None) == []
    assert MuseProvider().invocation_option_args(LLMInvocationOptions()) == []


def test_muse_rejects_an_explicit_unsupported_effort() -> None:
    with pytest.raises(LLMInvocationError, match="Muse Code does not support"):
        MuseProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort="ludicrous", explicit=True)
        )


@pytest.mark.parametrize(
    ("generic_env", "provider_env"),
    [
        ("SASE_LLM_LARGE_ARGS", "SASE_MUSE_LARGE_ARGS"),
    ],
)
def test_muse_generic_extra_args_take_precedence(
    generic_env: str,
    provider_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(provider_env, "--from-provider-env")
    monkeypatch.setenv(generic_env, "--max-model-steps 5")

    cmd, _ = _invoke_and_capture(MuseProvider())

    assert "--from-provider-env" not in cmd
    assert cmd[cmd.index("--max-model-steps") + 1] == "5"


def test_muse_provider_specific_extra_args_are_used_as_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_LLM_LARGE_ARGS", raising=False)
    monkeypatch.setenv("SASE_MUSE_LARGE_ARGS", "--disable-web-tools")

    cmd, _ = _invoke_and_capture(MuseProvider())

    assert "--disable-web-tools" in cmd


def test_muse_never_interpolates_the_prompt_into_a_shell() -> None:
    with (
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.muse.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.muse.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("response", "", 0, {})
        MuseProvider().invoke("; rm -rf / #", model_tier="large", suppress_output=True)

    assert isinstance(mock_popen.call_args.args[0], list)
    assert "shell" not in mock_popen.call_args.kwargs
    # The prompt never reaches argv at all — it goes through --prompt-file.
    assert "; rm -rf / #" not in mock_popen.call_args.args[0]


def test_muse_missing_executable_names_the_env_var_and_install_command() -> None:
    with (
        patch("sase.llm_provider.muse.subprocess.Popen", side_effect=FileNotFoundError),
        patch("sase.llm_provider.muse.provider_timer"),
        pytest.raises(FileNotFoundError) as excinfo,
    ):
        MuseProvider().invoke("prompt", model_tier="large", suppress_output=True)

    message = str(excinfo.value)
    assert "SASE_MUSE_PATH" in message
    assert "PATH" in message
    assert "sase agent-cli install muse" in message


def test_muse_nonzero_exit_raises_called_process_error() -> None:
    with (
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.muse.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.muse.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("partial", "boom", 1, {})
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            MuseProvider().invoke("prompt", model_tier="large", suppress_output=True)

    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == "boom"


def test_muse_interrupt_reconstructs_the_continuation_prompt() -> None:
    provider = MuseProvider()
    prompts: list[str] = []

    def _fake_run(
        args: list[str],
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output
        prompt_file = Path(args[args.index("--prompt-file") + 1])
        prompts.append(prompt_file.read_text(encoding="utf-8"))
        if len(prompts) == 1:
            provider._pending_interrupt_message = "also update the README"
            return ("first pass", "", 0, {})
        return ("second pass", "", 0, {})

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        result = provider.invoke(
            "original task", model_tier="large", suppress_output=True
        )

    assert prompts[0] == "original task"
    assert "--- Work So Far ---\nfirst pass" in prompts[1]
    assert "--- User Message ---\nalso update the README" in prompts[1]
    assert result.content == "first pass\n\nsecond pass"


# ---------------------------------------------------------------------------
# Stream parser
# ---------------------------------------------------------------------------


def test_muse_stream_returns_the_terminal_text_without_delta_duplication() -> None:
    """The regression that matters most.

    The read-tool capture exits 0 while carrying `task.lifecycle.rejected`
    (`skip_if_running`) and `task.lifecycle.cancelled` (`main run completed`),
    and repeats the reply in both `run.output.delta` and
    `run.terminal.completed`. A Codex-style "any failure event is an error"
    parser manufactures a failure here, and appending the delta doubles the
    reply.
    """
    payload = _READ_TOOL_FIXTURE.read_text(encoding="utf-8")
    assert "task.lifecycle.rejected" in payload
    assert "task.lifecycle.cancelled" in payload

    content, stderr_content, return_code, usage = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "bravo"
    assert stderr_content == ""
    assert usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_muse_stream_parses_the_write_and_bash_capture() -> None:
    content, stderr_content, return_code, _ = _run_fixture_stream(
        _WRITE_BASH_FIXTURE.read_text(encoding="utf-8")
    )

    assert return_code == 0
    assert content == "DONE"
    assert stderr_content == ""


def test_muse_stream_streams_deltas_into_the_live_reply_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        _READ_TOOL_FIXTURE.read_text(encoding="utf-8")
    )

    live_reply = (tmp_path / "live_reply.md").read_text(encoding="utf-8")
    assert live_reply == "bravo"
    assert content == "bravo"
    timestamps = (tmp_path / "live_reply_timestamps.jsonl").read_text(encoding="utf-8")
    assert json.loads(timestamps.splitlines()[0])["byte_offset"] == 0


def test_muse_stream_keeps_task_failures_out_of_a_successful_run() -> None:
    payload = _envelope(
        "task.lifecycle.rejected",
        {"event": {"kind": "rejected", "reason": "skip_if_running"}},
    ) + _envelope(
        "run.terminal.completed",
        {"terminal": "completed", "reason": None, "text": "all good"},
    )

    content, stderr_content, return_code, _ = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "all good"
    assert stderr_content == ""


def test_muse_stream_surfaces_task_diagnostics_when_the_process_failed() -> None:
    payload = _envelope(
        "task.lifecycle.rejected",
        {"event": {"kind": "rejected", "reason": "skip_if_running"}},
    )

    _, stderr_content, return_code, _ = _run_fixture_stream(payload, exit_code=1)

    assert return_code == 1
    assert "[muse] task rejected: skip_if_running" in stderr_content


def test_muse_stream_reports_a_non_completed_terminal_outcome() -> None:
    payload = _envelope(
        "run.terminal.failed",
        {"terminal": "failed", "reason": "model stream closed", "text": ""},
    )

    _, stderr_content, _, _ = _run_fixture_stream(payload, exit_code=1)

    assert "[muse] run terminal failed: model stream closed" in stderr_content


def test_muse_stream_labels_exit_code_two_as_a_usage_error() -> None:
    _, stderr_content, return_code, _ = _run_fixture_stream(
        _envelope("run.terminal.completed", {"terminal": "completed", "text": "hello"}),
        exit_code=2,
        stderr="error: unexpected argument '--nope'\n",
    )

    assert return_code == 2
    assert "--nope" in stderr_content
    assert MUSE_USAGE_ERROR_NOTE in stderr_content


def test_muse_stream_tolerates_unknown_payload_types_and_newer_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    payload = _envelope("run.telepathy.vibed", {"text": "ignored"}) + _envelope(
        "run.terminal.completed",
        {"terminal": "completed", "text": "still fine"},
        schema_version=99,
        payload_schema_version=42,
    )

    content, stderr_content, return_code, _ = _run_fixture_stream(payload)

    assert return_code == 0
    assert content == "still fine"
    assert stderr_content == ""

    diagnostics = [
        json.loads(line)
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    ahead = [
        d for d in diagnostics if d["reason"] == "muse_stdout_schema_version_ahead"
    ]
    assert ahead and ahead[0]["schema_version"] == 99
    assert ahead[0]["payload_schema_version"] == 42


def test_muse_stream_records_a_diagnostic_for_undecodable_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, _, _ = _run_fixture_stream(
        '{"schema_version": 1, "payload_type"\n'
        + _envelope("run.terminal.completed", {"terminal": "completed", "text": "ok"})
    )

    assert content == "ok"
    reasons = {
        json.loads(line)["reason"]
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert "muse_stdout_json_decode_error" in reasons
    assert "muse_stdout_envelope_unparsed" in reasons


def test_muse_stream_flags_a_missing_terminal_event_instead_of_returning_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    content, _, return_code, _ = _run_fixture_stream(
        _envelope("run.output.delta", {"text": "partial answer"}, record_type="status")
    )

    assert return_code == 0
    # The delta is the only text there is; losing it silently would be worse.
    assert content == "partial answer"
    reasons = {
        json.loads(line)["reason"]
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert "muse_missing_run_terminal_event" in reasons
