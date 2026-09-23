"""MuseProvider command-construction and invocation tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.muse import (
    MuseProvider,
    _muse_single_turn_directive,
    _muse_synchronous_shell_enabled,
)
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions

from ._muse_provider_helpers import _invoke_and_capture


def test_muse_command_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_MUSE_SANDBOX", raising=False)
    monkeypatch.delenv("SASE_LLM_LARGE_ARGS", raising=False)
    monkeypatch.delenv("SASE_MUSE_LARGE_ARGS", raising=False)
    monkeypatch.setenv("SASE_MUSE_PATH", "/opt/muse/bin/muse")

    cmd, kwargs = _invoke_and_capture(MuseProvider())

    assert cmd[:3] == ["/opt/muse/bin/muse", "exec", "--json"]
    assert cmd[cmd.index("--workspace") + 1] == os.getcwd()
    assert cmd[cmd.index("--model") + 1] == "muse-spark-1.3"
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
        process: object,
        suppress_output: bool = False,
        *,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del process, suppress_output, session_id
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
    assert seen["content"].startswith("SASE single-turn instructions for Muse Code")  # type: ignore[union-attr]
    assert seen["content"].endswith("\n\n--- User Prompt ---\nsecret prompt body")  # type: ignore[union-attr]
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
        ("max", "max"),
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
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, session_id
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

    assert prompts[0].endswith("\n\n--- User Prompt ---\noriginal task")
    assert "--- Work So Far ---\nfirst pass" in prompts[1]
    assert "--- User Message ---\nalso update the README" in prompts[1]
    # The reconstructed continuation keeps the single-turn directive.
    assert prompts[1].startswith("SASE single-turn instructions for Muse Code")
    assert "--- User Prompt ---\noriginal task\n\n--- Work So Far ---" in prompts[1]
    assert result.content == "first pass\n\nsecond pass"


@pytest.mark.parametrize(
    ("flag_value", "expected"),
    [(True, True), (False, False)],
)
def test_muse_sync_shell_flag_reads_both_states(
    flag_value: bool, expected: bool
) -> None:
    with override_flags(muse_synchronous_shell=flag_value):
        assert _muse_synchronous_shell_enabled() is expected


def test_muse_sync_shell_flag_falls_back_to_on_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags.models import FeatureFlagError

    def _raise() -> object:
        raise FeatureFlagError("unknown feature flag: 'muse_synchronous_shell'")

    monkeypatch.setattr("sase.feature_flags.current_flags", _raise)
    assert _muse_synchronous_shell_enabled() is True


def test_muse_sync_shell_flag_adds_enable_shell_tool() -> None:
    with override_flags(muse_synchronous_shell=True):
        cmd, _ = _invoke_and_capture(MuseProvider())

    assert "--enable-shell-tool" in cmd


def test_muse_managed_bash_flag_omits_enable_shell_tool() -> None:
    with override_flags(muse_synchronous_shell=False):
        cmd, _ = _invoke_and_capture(MuseProvider())

    assert "--enable-shell-tool" not in cmd


@pytest.mark.parametrize(
    "env",
    ["SASE_LLM_LARGE_ARGS", "SASE_MUSE_LARGE_ARGS"],
)
def test_muse_sync_shell_flag_is_never_duplicated(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(env, "--enable-shell-tool --max-model-steps 5")
    monkeypatch.delenv(
        "SASE_MUSE_LARGE_ARGS"
        if env == "SASE_LLM_LARGE_ARGS"
        else "SASE_LLM_LARGE_ARGS",
        raising=False,
    )

    with override_flags(muse_synchronous_shell=True):
        cmd, _ = _invoke_and_capture(MuseProvider())

    assert cmd.count("--enable-shell-tool") == 1


def _invoke_and_capture_prompts(provider: MuseProvider) -> list[str]:
    """Invoke *provider* and return every prompt file's contents."""
    prompts: list[str] = []

    def _fake_run(
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, session_id
        prompt_file = Path(args[args.index("--prompt-file") + 1])
        prompts.append(prompt_file.read_text(encoding="utf-8"))
        return ("response", "", 0, {})

    with (
        patch("sase.llm_provider.muse.provider_timer"),
        patch.object(MuseProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        provider.invoke("do the thing", model_tier="large", suppress_output=True)
    return prompts


def test_muse_sync_directive_prefixes_the_prompt() -> None:
    with override_flags(muse_synchronous_shell=True):
        (first,) = _invoke_and_capture_prompts(MuseProvider())

    assert first == (
        _muse_single_turn_directive(synchronous=True)
        + "\n\n--- User Prompt ---\ndo the thing"
    )
    assert "`shell` tool runs each command synchronously" in first
    assert "10 minutes" in first
    assert "timeout 540" in first
    assert "Never end your turn to wait." in first


def test_muse_managed_directive_prefixes_the_prompt() -> None:
    with override_flags(muse_synchronous_shell=False):
        (first,) = _invoke_and_capture_prompts(MuseProvider())

    assert first == (
        _muse_single_turn_directive(synchronous=False)
        + "\n\n--- User Prompt ---\ndo the thing"
    )
    assert "`bash` tool may move a long command to the background" in first
    assert "Never submit your final declaration" in first
    assert "`shell` tool runs each command synchronously" not in first


def test_muse_directives_share_routing_rules_but_differ_by_mode() -> None:
    sync = _muse_single_turn_directive(synchronous=True)
    managed = _muse_single_turn_directive(synchronous=False)

    assert "nothing can wake you after you end it" in sync
    assert "nothing can wake you after you end it" in managed
    assert "/sase_monitor" in sync
    assert "/sase_monitor" in managed
    assert "about two minutes after your final declaration" in managed
    assert "about two minutes after your final declaration" not in sync
