"""Exec-handoff refresh tests for the runner."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    refresh_runner_code_after_wait,
)


def test_changed_identity_reexecs_original_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    old = "a" * 40
    new = "b" * 40
    prompt_file = tmp_path / "submitted-prompt.md"
    submitted_prompt = "%i(fix)\nKeep this exact prompt\n"

    def assert_exec_handoff(*_args: object) -> None:
        assert prompt_file.read_text(encoding="utf-8") == submitted_prompt
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=new,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ) as execv,
        patch.object(sys, "executable", "/venv/bin/python"),
        patch.object(sys, "argv", ["runner.py", "--workspace-num", "7"]),
    ):
        refresh_runner_code_after_wait(
            old,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt=submitted_prompt,
        )

    execv.assert_called_once_with(
        "/venv/bin/python",
        ["/venv/bin/python", "runner.py", "--workspace-num", "7"],
    )
    assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"


def test_refresh_handoff_preserves_current_agent_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "submitted-prompt.md"

    def assert_exec_handoff(*_args: object) -> None:
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"
        assert os.environ["SASE_AGENT_PLANNED_NAME"] == "builder.w0"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value="builder.w0",
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="%wait:builder\nDo work",
            agent_name="builder.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert os.environ["SASE_AGENT_PLANNED_NAME"] == "builder.w0"


def test_refresh_handoff_drops_stale_planned_name_without_current_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "submitted-prompt.md"

    def assert_exec_handoff(*_args: object) -> None:
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"
        assert "SASE_AGENT_PLANNED_NAME" not in os.environ

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value=None,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="%wait:builder\nDo work",
            agent_name="foreign.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert "SASE_AGENT_PLANNED_NAME" not in os.environ


def test_exec_failure_restores_prior_planned_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.setenv("SASE_AGENT_PLANNED_NAME", "stale-parent")
    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh._validated_continuation_planned_name",
            return_value="builder.w0",
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="prompt",
            agent_name="builder.w0",
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert os.environ["SASE_AGENT_PLANNED_NAME"] == "stale-parent"
    assert not prompt_file.exists()
    assert "continuing: exec failed" in capsys.readouterr().err


def test_prompt_rewrite_failure_skips_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "missing" / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert "Skipping sase runner code refresh" in capsys.readouterr().err


def test_exec_failure_continues_without_refresh_guard_or_prompt_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="prompt",
        )

    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert not prompt_file.exists()
    assert "continuing: exec failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("startup_identity", "current_identity", "blocked", "killed"),
    [
        ("a" * 40, "a" * 40, True, False),
        ("a" * 40, "b" * 40, False, False),
        ("a" * 40, "b" * 40, True, True),
        (None, "b" * 40, True, False),
    ],
    ids=("unchanged", "no-blocking-wait", "killed", "unknown-startup"),
)
def test_refresh_is_inert_without_all_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    startup_identity: str | None,
    current_identity: str,
    blocked: bool,
    killed: bool,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=current_identity,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            startup_identity,
            blocking_wait_occurred=blocked,
            killed=killed,
            prompt_file="/tmp/prompt.md",
            submitted_prompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refreshed_guard_prevents_loop_and_is_not_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity"
        ) as current_identity,
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file="/tmp/prompt.md",
            submitted_prompt="prompt",
        )

    current_identity.assert_not_called()
    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refresh_path_imports_no_new_sase_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import firewall: the identity check to execv span imports no new code.

    A torn post-update tree cannot satisfy fresh imports, which is exactly
    how the 2026-10-09 ``auto_launch_prefix`` incident died. Any
    ``sase.*`` import after the identity check trips the firewall, so this
    reaches ``execv`` only when every refresh-path helper (including the
    lazily-imported leaves they touch) was already imported at boot.
    """
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    submitted_prompt = "%wait:builder\nDo work"
    macros = {"_x": Macro(name="_x", content="expanded body")}
    attempted: list[str] = []

    class _ImportFirewall:
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> object:
            if fullname == "sase" or fullname.startswith("sase."):
                attempted.append(fullname)
                raise ImportError(f"import-firewall: {fullname} imported late")
            return None

    firewall = _ImportFirewall()
    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)

    sys.meta_path.insert(0, firewall)
    try:
        with (
            patch(
                "sase.axe.run_agent_runner_refresh.runner_code_identity",
                return_value="b" * 40,
            ),
            patch(
                "sase.agent.names.planned_registered_name_belongs_to_artifact",
                return_value=True,
            ),
            patch(
                "sase.axe.run_agent_runner_refresh.os.execv",
                side_effect=capture_exec,
            ),
        ):
            refresh_runner_code_after_wait(
                "a" * 40,
                blocking_wait_occurred=True,
                killed=False,
                prompt_file=str(prompt_file),
                submitted_prompt=submitted_prompt,
                agent_name="builder.w0",
                artifacts_dir=str(artifacts_dir),
                local_macros=macros,
            )
    finally:
        sys.meta_path.remove(firewall)

    assert attempted == []
    assert prompt_file.read_text(encoding="utf-8") == submitted_prompt
    assert captured[RUNNER_CODE_REFRESHED_ENV] == "1"
    assert captured["SASE_AGENT_PLANNED_NAME"] == "builder.w0"
    assert LOCAL_MACROS_ENV in captured
