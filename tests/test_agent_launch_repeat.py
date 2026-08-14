"""Integration smoke tests for _launch_repeat_agents on the TUI mixin."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow import _launch_repeat
from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcOutcome
from sase.ace.tui.actions.agent_workflow._types import PromptContext


@pytest.fixture(autouse=True)
def _no_repeat_spawn_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero out the 1s inter-spawn sleep so tests don't wait on real time."""
    monkeypatch.setattr(_launch_repeat, "_REPEAT_SPAWN_SLEEP", 0.0)


class _FakeApp(AgentLaunchMixin):
    """Minimal AgentLaunchMixin harness for repeat-launch tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.launched: list[dict[str, object]] = []
        self.outcomes: list[LaunchProcOutcome] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: object, *args: object, **kwargs: object) -> None:
        if not callable(fn):
            return
        result = fn(*args, **kwargs)
        # Compatibility for helpers that still schedule coroutines.
        if asyncio.iscoroutine(result):
            asyncio.run(result)

    def _submit_launch_proc(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        proc_callable: object,
        dedup_key: str | None = None,
        submitted_prompt: str | None = None,
    ) -> bool:
        del display_name, cl_name, project_file, dedup_key, submitted_prompt
        if not callable(proc_callable):
            return False
        outcome = proc_callable()
        if isinstance(outcome, LaunchProcOutcome):
            self.outcomes.append(outcome)
            if outcome.notify:
                self.notify(outcome.message, severity=outcome.severity)
        return True

    def request_agents_refresh(
        self,
        source: str,
        *,
        debounce_ms: int = 150,
        latest_only: bool = True,
    ) -> None:
        del source, debounce_ms, latest_only

    def _load_agents(self) -> None:
        pass

    def _launch_background_agent(
        self,
        cl_name: str,
        project_file: str,
        workspace_dir: str,
        workspace_num: int,
        workflow_name: str,
        prompt: str,
        timestamp: str,
        update_target: str = "",
        project_name: str = "",
        history_sort_key: str = "",
        is_home_mode: bool = False,
        vcs_ref: tuple[str, str] | None = None,
        deferred_workspace: bool = False,
        extra_env: dict[str, str] | None = None,
        retry_transfer_from_pid: int | None = None,
    ) -> None:
        del (
            project_file,
            workspace_dir,
            workspace_num,
            timestamp,
            update_target,
            project_name,
            history_sort_key,
            is_home_mode,
            vcs_ref,
            deferred_workspace,
        )
        self.launched.append(
            {
                "cl_name": cl_name,
                "prompt": prompt,
                "workflow_name": workflow_name,
                "extra_env": extra_env,
                "retry_transfer_from_pid": retry_transfer_from_pid,
            }
        )


def _fake_context() -> PromptContext:
    return PromptContext(
        project_name="test",
        cl_name="test",
        project_file="/tmp/test.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="",
        display_name="test",
        update_target="",
        is_home_mode=True,  # Skip real workspace allocation
    )


class TestLaunchRepeatAgents:
    def test_spawns_n_agents_with_repeat_envs(self, tmp_path: Path) -> None:
        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:3 %i:foo body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )

        assert len(app.launched) == 3
        names = [call["extra_env"]["SASE_REPEAT_NAME"] for call in app.launched]  # type: ignore[index]
        assert names == ["foo.1", "foo.2", "foo.3"]
        iterations = [
            call["extra_env"]["SASE_REPEAT_ITERATION"]  # type: ignore[index]
            for call in app.launched
        ]
        assert iterations == ["1", "2", "3"]
        totals = [
            call["extra_env"]["SASE_REPEAT_TOTAL"]  # type: ignore[index]
            for call in app.launched
        ]
        assert totals == ["3", "3", "3"]

    def test_injects_prev_name_only_for_later_slots(self, tmp_path: Path) -> None:
        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:3 %i:foo body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )

        assert len(app.launched) == 3
        prev_names = [
            call["extra_env"].get("SASE_REPEAT_PREV_NAME")  # type: ignore[union-attr]
            for call in app.launched
        ]
        assert prev_names == [None, "foo.1", "foo.2"]

    def test_prompt_has_repeat_stripped_and_name_injected(self, tmp_path: Path) -> None:
        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:2 %i:bar do Y",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )

        assert len(app.launched) == 2
        for idx, call in enumerate(app.launched, start=1):
            prompt = call["prompt"]
            assert "%r:2" not in prompt  # type: ignore[operator]
            assert f"%i:bar.{idx}" in prompt  # type: ignore[operator]
            assert "do Y" in prompt  # type: ignore[operator]

    def test_forwards_workspace_claim_transfer_pid(self, tmp_path: Path) -> None:
        app = _FakeApp()
        ctx = _fake_context()
        ctx.is_home_mode = False

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.running_field.claim_next_axe_workspace",
                side_effect=[21, 22],
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[("/tmp/ws21", None), ("/tmp/ws22", None)],
            ),
        ):
            app._launch_repeat_agents(
                prompt="%r:2 %i:foo body",
                ctx=ctx,
                vcs_ref=None,
                has_wait=False,
            )

        assert len(app.launched) == 2
        assert [call["retry_transfer_from_pid"] for call in app.launched] == [
            os.getpid(),
            os.getpid(),
        ]

    def test_single_iteration_falls_through(self, tmp_path: Path) -> None:
        """%r:1 should be a no-op — _launch_repeat_agents only runs when >1,
        so the guarding caller (`_finish_agent_launch`) never invokes it.
        Here we exercise the detection helper directly."""
        from sase.agent.repeat_launcher import extract_repeat_and_name

        count, _, _ = extract_repeat_and_name("%r:1 do X")
        assert count is None

    def test_name_collision_surfaces_as_error_notification(
        self, tmp_path: Path
    ) -> None:
        import json
        import os

        artifact_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "ts"
        )
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "zz.2", "pid": os.getpid()})
        )

        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:3 %i:zz body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )

        error_notifications = [
            msg for msg, severity in app.notifications if severity == "error"
        ]
        assert error_notifications
        assert any("zz" in msg for msg in error_notifications)
        assert app.launched == []

    def test_error_outcome_requests_agents_refresh(self, tmp_path: Path) -> None:
        """A mid-plan failure may have spawned slots already; the error
        outcome must request a refresh so they become visible."""
        import json
        import os

        artifact_dir = (
            tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "ts"
        )
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": "zz.2", "pid": os.getpid()})
        )

        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:3 %i:zz body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )

        assert app.outcomes
        outcome = app.outcomes[-1]
        assert outcome.severity == "error"
        assert outcome.request_agents_refresh is True
