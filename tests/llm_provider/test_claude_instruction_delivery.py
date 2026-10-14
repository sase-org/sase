"""Claude adapter delivery through the real render/manifest boundary."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider._claude_helper_channel import (
    helper_channel_settings_json,
    helper_template_path,
)
from sase.llm_provider._instruction_boundary import invoke_with_instructions
from sase.llm_provider.claude import ClaudeCodeProvider, _SINGLE_TURN_DIRECTIVE
from sase.llm_provider.instruction_delivery import (
    MARKER_RE,
    current_instruction_delivery,
    resolve_delivery_plan,
)
from sase.llm_provider.registry import create_provider
from tests.instructions.fixture_compiler import make_roots, write


class _Harness:
    def __init__(self, root: Path) -> None:
        self.provider = ClaudeCodeProvider()
        self.artifacts = root / "artifacts"
        self.calls: list[dict[str, Any]] = []
        self.action = "ok"

    def capture(
        self, argv: list[str], prompt: str, _suppress: bool, *, wait_state: Any
    ) -> tuple[str, str, int, dict[str, int]]:
        files: dict[str, tuple[Path, str]] = {}
        for slot, flag in (
            ("root", "--append-system-prompt-file"),
            ("subagent", "--append-subagent-system-prompt-file"),
        ):
            if flag in argv:
                path = Path(argv[argv.index(flag) + 1])
                files[slot] = (path, path.read_text())
                if path != helper_template_path():
                    assert stat.S_IMODE(path.stat().st_mode) == 0o600
        self.calls.append({"argv": argv, "prompt": prompt, "files": files})
        if len(self.calls) == 1:
            if self.action == "interrupt":
                self.provider._pending_interrupt_message = "change of plan"
            elif self.action == "resume":
                wait_state.schedule_wakeup_requested = True
            elif self.action == "fail":
                return "", "CLI failed", 1, {}
        return "pong", "", 0, {}

    def invoke(self, *, enabled: bool = True, artifacts: bool = True) -> None:
        with override_flags(claude_explicit_instructions=enabled):
            invoke_with_instructions(
                self.provider,
                "ping",
                purpose="ordinary",
                provider_name="claude",
                artifacts_dir=str(self.artifacts) if artifacts else None,
                model_tier="small",
                model_override="haiku",
                suppress_output=True,
            )

    def manifest(self) -> dict[str, Any]:
        return json.loads(
            (self.artifacts / "instructions" / "00-claude.json").read_text()
        )


@pytest.fixture()
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    project, home = make_roots(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(project))
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(tmp_path / "instructions"))
    for variable in ("SASE_LLM_SMALL_ARGS", "SASE_CLAUDE_SMALL_ARGS"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        "sase.llm_provider.claude.subagent_prompt_supported", lambda: True
    )
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.probe_provider_cli_version",
        lambda _provider: "test",
    )
    temp = tmp_path / "delivery"
    temp.mkdir()
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.get_sase_managed_tmpdir",
        lambda *_args: str(temp),
    )
    result = _Harness(tmp_path)
    monkeypatch.setattr(result.provider, "_run_subprocess", result.capture)
    return result


@pytest.mark.parametrize("supported", [True, False])
def test_claude_hook_slots(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, supported: bool
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.claude.subagent_prompt_supported", lambda: supported
    )
    with override_flags(claude_explicit_instructions=True):
        plan = resolve_delivery_plan(create_provider("claude"))
    assert plan.root.status == "explicit"
    assert plan.root.channel == "claude.append_system_prompt_file"
    assert plan.subagent.status == ("explicit" if supported else "none")
    assert plan.subagent.reason == (None if supported else "unsupported_cli")
    with override_flags(claude_explicit_instructions=False):
        legacy = resolve_delivery_plan(create_provider("claude"))
    assert legacy.root.status == legacy.subagent.status == "inherits_native"
    assert legacy.root.reason == legacy.subagent.reason == "flag_disabled"


def test_explicit_files_excludes_and_cleanup(harness: _Harness) -> None:
    project, home = Path.cwd(), Path.home()
    write(home / "AGENTS.md", "## SASE Final Declaration\nHome render\n")
    write(home / "CLAUDE.md", "My hand-written home guide\n")
    for name in ("AGENTS.md", "CLAUDE.md", "tools/AGENTS.md", "sase/repos/x/CLAUDE.md"):
        write(project / name, "Repo-owned guide\n")
    harness.invoke()
    call = harness.calls[0]
    argv = call["argv"]
    assert "--append-system-prompt" not in argv
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["hooks"] == json.loads(helper_channel_settings_json())["hooks"]
    assert settings["autoMemoryEnabled"] is False
    assert settings["claudeMdExcludes"] == [
        str(project / "AGENTS.md"),
        str(project / "CLAUDE.md"),
        str(home / "AGENTS.md"),
    ]
    assert "instructionFiles" not in settings
    manifest = harness.manifest()
    delivery = manifest["delivery"]
    assert delivery["status"] == delivery["subagent"]["status"] == "explicit"
    assert delivery["session_ids"] == [argv[argv.index("--session-id") + 1]]
    for slot, (path, text) in call["files"].items():
        assert not path.exists()
        matches = MARKER_RE.findall(text)
        sha = (
            manifest["bundle"]["sha256"]
            if slot == "root"
            else delivery["subagent"]["bundle_sha256"]
        )
        assert matches == [(sha[:12], delivery["invocation_id"])]
    assert "SASE Final Declaration" in call["files"]["root"][1]
    assert "# SASE Helper Instructions" not in call["files"]["root"][1]
    assert "# SASE Helper Instructions" in call["files"]["subagent"][1]
    assert "SASE Final Declaration" not in call["files"]["subagent"][1]
    assert current_instruction_delivery() is None


@pytest.mark.parametrize(("enabled", "artifacts"), [(False, True), (True, False)])
def test_legacy_argv_golden(harness: _Harness, enabled: bool, artifacts: bool) -> None:
    harness.invoke(enabled=enabled, artifacts=artifacts)
    argv = harness.calls[0]["argv"]
    session = argv[argv.index("--session-id") + 1]
    assert argv == [
        "claude",
        "-p",
        "--verbose",
        "--model",
        "haiku",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "--append-system-prompt",
        _SINGLE_TURN_DIRECTIVE,
        "--disallowedTools",
        "ScheduleWakeup",
        "--session-id",
        session,
        "--settings",
        helper_channel_settings_json(),
        "--append-subagent-system-prompt-file",
        str(helper_template_path()),
    ]
    if artifacts:
        assert harness.manifest()["delivery"]["fallback"]["reason"] == "flag_disabled"
    else:
        assert not harness.artifacts.exists()


def test_unsupported_helper_keeps_root_and_guard(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.claude.subagent_prompt_supported", lambda: False
    )
    harness.invoke()
    argv = harness.calls[0]["argv"]
    assert "--append-system-prompt-file" in argv
    assert "--append-subagent-system-prompt-file" not in argv
    assert "PreToolUse" in argv[argv.index("--settings") + 1]
    assert harness.manifest()["delivery"]["subagent"]["status"] == "none"


@pytest.mark.parametrize("slot", ["root", "subagent"])
def test_materialization_failure_is_slot_local(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, slot: str
) -> None:
    # O_EXCL rejects an existing slot file, exercising the real write failure.
    write(tmp_path / "delivery" / f"{slot}.md", "occupied")
    notify = Mock()
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback", notify
    )
    harness.invoke()
    argv = harness.calls[0]["argv"]
    settings = json.loads(argv[argv.index("--settings") + 1])
    delivery = harness.manifest()["delivery"]
    failed = delivery if slot == "root" else delivery["subagent"]
    assert failed["status"] == "inherits_native"
    assert failed["fallback"]["reason"] == "delivery_failed"
    notify.assert_called_once()
    if slot == "root":
        assert "--append-system-prompt-file" not in argv
        assert argv[argv.index("--append-system-prompt") + 1] == _SINGLE_TURN_DIRECTIVE
        assert settings == json.loads(helper_channel_settings_json())
        assert delivery["subagent"]["status"] == "explicit"
    else:
        assert delivery["status"] == "explicit"
        assert settings["autoMemoryEnabled"] is False
        assert argv[argv.index("--append-subagent-system-prompt-file") + 1] == str(
            helper_template_path()
        )


@pytest.mark.parametrize("action", ["interrupt", "resume"])
def test_continuations_reuse_files_and_record_sessions(
    harness: _Harness, action: str
) -> None:
    harness.action = action
    harness.invoke()
    first, second = harness.calls
    assert first["files"] == second["files"]
    for path, _ in first["files"].values():
        assert not path.exists()
    initial = first["argv"][first["argv"].index("--session-id") + 1]
    sessions = harness.manifest()["delivery"]["session_ids"]
    if action == "resume":
        assert second["argv"][second["argv"].index("--resume") + 1] == initial
        assert sessions == [initial]
    else:
        restarted = second["argv"][second["argv"].index("--session-id") + 1]
        assert initial != restarted
        assert sessions == [initial, restarted]
        assert second["prompt"] == "change of plan"


def test_cli_failure_still_cleans_up(harness: _Harness) -> None:
    harness.action = "fail"
    with pytest.raises(subprocess.CalledProcessError):
        harness.invoke()
    for path, _ in harness.calls[0]["files"].values():
        assert not path.exists()
    assert current_instruction_delivery() is None
