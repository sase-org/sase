"""Tests for the Claude native-helper channel.

Covers the packaged helper template, the inline ``--settings`` guard JSON,
argv on first and ``--resume`` cycles, the sunset flag in both states, the
no-API capability probe outcomes, and the doctor deep check.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider._claude_helper_channel import (
    HELPER_TEMPLATE_FIRST_LINE,
    _helper_guard_path,
    claude_helper_channel_enabled,
    helper_channel_settings_json,
    helper_template_path,
    probe_subagent_prompt_uncached,
    subagent_prompt_supported,
)

_USAGE = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


def _stream_ok(*_args: object, **_kwargs: object) -> tuple:
    return ("response", "", 0, dict(_USAGE))


def _popen_argvs(mock_popen: MagicMock) -> list[list[str]]:
    return [call.args[0] for call in mock_popen.call_args_list]


def _invoke(cli_args: dict | None = None) -> MagicMock:
    from sase.llm_provider.claude import ClaudeCodeProvider

    with (
        patch(
            "sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()
        ) as mock_popen,
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=_stream_ok,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
        patch(
            "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
            return_value=None,
        ),
    ):
        with override_flags(claude_helper_channel=True):
            with patch(
                "sase.llm_provider.claude.subagent_prompt_supported",
                return_value=True,
            ):
                ClaudeCodeProvider().invoke(
                    "hi", model_tier="small", suppress_output=True
                )
    return mock_popen


def test_helper_template_marker_and_size() -> None:
    """The packaged template starts with its marker and stays small."""
    path = helper_template_path()
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == HELPER_TEMPLATE_FIRST_LINE
    assert len(text.encode("utf-8")) <= 2048


def test_helper_settings_json_names_guard_path() -> None:
    """The inline settings value parses and points at the guard script."""
    raw = helper_channel_settings_json()
    settings = json.loads(raw)
    entries = settings["hooks"]["PreToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Bash|Skill"
    hooks = entries[0]["hooks"]
    assert len(hooks) == 1
    assert hooks[0]["type"] == "command"
    assert hooks[0]["timeout"] == 10
    assert os.fspath(_helper_guard_path()) in hooks[0]["command"]
    assert _helper_guard_path().is_file()


def test_helper_channel_argv_first_cycle() -> None:
    """The first cycle carries both the guard settings and the template flag."""
    mock_popen = _invoke()
    assert mock_popen.call_count == 1
    argv = _popen_argvs(mock_popen)[0]
    assert "--settings" in argv
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "Bash|Skill"
    assert "--append-subagent-system-prompt-file" in argv
    template = argv[argv.index("--append-subagent-system-prompt-file") + 1]
    assert template == os.fspath(helper_template_path())


def test_helper_channel_argv_resume_cycle() -> None:
    """A wait-continuation ``--resume`` cycle keeps the helper channel."""
    from sase.llm_provider.claude import ClaudeCodeProvider

    calls = {"count": 0}

    def _stream_wait_then_ok(*args: object, **kwargs: object) -> tuple:
        calls["count"] += 1
        wait_state = kwargs.get("wait_state")
        if calls["count"] == 1 and wait_state is not None:
            wait_state.schedule_wakeup_requested = True
        return ("response", "", 0, dict(_USAGE))

    with (
        patch(
            "sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()
        ) as mock_popen,
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=_stream_wait_then_ok,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
        patch(
            "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
            return_value=None,
        ),
    ):
        with override_flags(claude_helper_channel=True):
            with patch(
                "sase.llm_provider.claude.subagent_prompt_supported",
                return_value=True,
            ):
                ClaudeCodeProvider().invoke(
                    "hi", model_tier="small", suppress_output=True
                )
    assert mock_popen.call_count == 2
    for argv in _popen_argvs(mock_popen):
        assert "--settings" in argv
        assert "--append-subagent-system-prompt-file" in argv
    assert "--resume" in _popen_argvs(mock_popen)[1]


def test_helper_channel_flag_off_restores_today_argv() -> None:
    """With the flag off there is no ``--settings`` and no subagent flag."""
    from sase.llm_provider.claude import ClaudeCodeProvider

    with (
        patch(
            "sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()
        ) as mock_popen,
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=_stream_ok,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
        patch(
            "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
            return_value=None,
        ),
    ):
        with override_flags(claude_helper_channel=False):
            ClaudeCodeProvider().invoke("hi", model_tier="small", suppress_output=True)
    argv = _popen_argvs(mock_popen)[0]
    assert "--settings" not in argv
    assert "--append-subagent-system-prompt-file" not in argv


def test_helper_channel_omits_template_when_unsupported() -> None:
    """An unsupported probe keeps the guard but drops the template flag."""
    from sase.llm_provider.claude import ClaudeCodeProvider

    with (
        patch(
            "sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()
        ) as mock_popen,
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=_stream_ok,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
        patch(
            "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
            return_value=None,
        ),
    ):
        with override_flags(claude_helper_channel=True):
            with patch(
                "sase.llm_provider.claude.subagent_prompt_supported",
                return_value=False,
            ):
                ClaudeCodeProvider().invoke(
                    "hi", model_tier="small", suppress_output=True
                )
    argv = _popen_argvs(mock_popen)[0]
    assert "--settings" in argv
    assert "--append-subagent-system-prompt-file" not in argv


@pytest.mark.parametrize(
    ("flag_value", "expected"),
    [(True, True), (False, False)],
)
def test_helper_channel_flag_reads_both_states(
    flag_value: bool, expected: bool
) -> None:
    with override_flags(claude_helper_channel=flag_value):
        assert claude_helper_channel_enabled() is expected


def test_helper_channel_flag_falls_back_to_on_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags.models import FeatureFlagError

    def _raise() -> object:
        raise FeatureFlagError("unknown feature flag: 'claude_helper_channel'")

    monkeypatch.setattr("sase.feature_flags.current_flags", _raise)
    assert claude_helper_channel_enabled() is True


def _write_fake_claude(tmp_path: Path, body: str) -> str:
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            'echo "Error: Append subagent system prompt file not found: $4" >&2; exit 1',
            "supported",
        ),
        (
            "echo \"error: unknown option '--append-subagent-system-prompt-file'\" >&2; exit 1",
            "unsupported",
        ),
        ('echo "something else entirely" >&2; exit 1', "unknown"),
    ],
)
def test_probe_outcomes_with_fake_executable(
    tmp_path: Path, body: str, expected: str
) -> None:
    executable = _write_fake_claude(tmp_path, body)
    outcome, _detail = probe_subagent_prompt_uncached(executable)
    assert outcome == expected


def test_probe_caches_by_executable_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    executable = _write_fake_claude(
        tmp_path,
        'echo "Error: Append subagent system prompt file not found: $4" >&2; exit 1',
    )
    with patch(
        "sase.llm_provider._claude_helper_channel.subprocess.run",
        wraps=__import__("subprocess").run,
    ) as spy:
        assert subagent_prompt_supported(executable) is True
        assert subagent_prompt_supported(executable) is True
    assert spy.call_count == 1


def _require_real_claude() -> str:
    """Return the real ``claude`` path, skipping on stubs or absence."""
    import subprocess

    candidate = shutil.which("claude")
    if candidate is None:
        pytest.skip("claude CLI is not installed")
    result = subprocess.run(
        [candidate, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    combined = f"{result.stdout} {result.stderr}"
    if "Claude Code" not in combined or "test stub" in combined:
        pytest.skip("PATH claude is a test stub, not Claude Code")
    return candidate


def test_live_probe_reports_supported_when_claude_present() -> None:
    """No-API probe against the real CLI; skips when ``claude`` is absent."""
    executable = _require_real_claude()
    outcome, detail = probe_subagent_prompt_uncached(executable)
    assert outcome == "supported", f"probe detail: {detail}"


def _doctor_context(tmp_path: Path):
    from sase.doctor.runner import DoctorContext

    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def test_doctor_helper_channel_ok(tmp_path: Path) -> None:
    from sase.doctor.checks_deep_providers import check_claude_helper_channel

    with override_flags(claude_helper_channel=True):
        with patch(
            "sase.llm_provider._claude_helper_channel.probe_subagent_prompt_uncached",
            return_value=("supported", "Error: ... not found: ..."),
        ):
            check = check_claude_helper_channel(_doctor_context(tmp_path))
    assert check.id == "providers.claude_helper_channel"
    assert check.status == "OK"


def test_doctor_helper_channel_error_when_unsupported(tmp_path: Path) -> None:
    from sase.doctor.checks_deep_providers import check_claude_helper_channel

    with override_flags(claude_helper_channel=True):
        with patch(
            "sase.llm_provider._claude_helper_channel.probe_subagent_prompt_uncached",
            return_value=("unsupported", "error: unknown option"),
        ):
            check = check_claude_helper_channel(_doctor_context(tmp_path))
    assert check.status == "ERROR"


def test_doctor_helper_channel_skips_when_flag_off(tmp_path: Path) -> None:
    from sase.doctor.checks_deep_providers import check_claude_helper_channel

    with override_flags(claude_helper_channel=False):
        check = check_claude_helper_channel(_doctor_context(tmp_path))
    assert check.status == "SKIP"
