"""Integration smoke tests for _launch_repeat_agents on the TUI mixin."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow import _launch_repeat
from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
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

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: object, *args: object, **kwargs: object) -> None:
        if not callable(fn):
            return
        result = fn(*args, **kwargs)
        # The fan-out entry now schedules an ``asyncio.to_thread`` runner
        # via ``call_later``; drive that coroutine to completion so the
        # downstream launch path runs synchronously inside the test.
        if asyncio.iscoroutine(result):
            asyncio.run(result)

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
            }
        )


def _fake_context() -> PromptContext:
    return PromptContext(
        project_name="test",
        cl_name="test",
        project_file="/tmp/test.gp",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="",
        display_name="test",
        update_target="",
        is_home_mode=True,  # Skip real workspace allocation
    )


def _join_threads() -> None:
    """Wait for all non-main daemon threads to finish."""
    for t in list(threading.enumerate()):
        if t is threading.main_thread():
            continue
        t.join(timeout=5)


class TestLaunchRepeatAgents:
    def test_spawns_n_agents_with_repeat_envs(self, tmp_path: Path) -> None:
        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:3 %n:foo body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )
            _join_threads()

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

    def test_prompt_has_repeat_stripped_and_name_injected(self, tmp_path: Path) -> None:
        app = _FakeApp()
        with patch.object(Path, "home", return_value=tmp_path):
            app._launch_repeat_agents(
                prompt="%r:2 %n:bar do Y",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )
            _join_threads()

        assert len(app.launched) == 2
        for idx, call in enumerate(app.launched, start=1):
            prompt = call["prompt"]
            assert "%r:2" not in prompt  # type: ignore[operator]
            assert f"%n:bar.{idx}" in prompt  # type: ignore[operator]
            assert "do Y" in prompt  # type: ignore[operator]

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
                prompt="%r:3 %n:zz body",
                ctx=_fake_context(),
                vcs_ref=None,
                has_wait=False,
            )
            _join_threads()

        error_notifications = [
            msg for msg, severity in app.notifications if severity == "error"
        ]
        assert error_notifications
        assert any("zz" in msg for msg in error_notifications)
        assert app.launched == []
