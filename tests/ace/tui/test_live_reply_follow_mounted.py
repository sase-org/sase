"""Mounted ACE coverage for the Muse parser-to-Reply-card streaming path."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sase.ace.testing import AcePage
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.models._loaders._workflow_step_loaders import (
    load_workflow_agent_steps,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import current_agent_session_turn_row
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._live_reply_follow import (
    _contains_live_reply_region,
)
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)


def _envelope(payload_type: str, payload: dict[str, object]) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "event",
                "durability": "durable",
                "payload_type": payload_type,
                "payload_schema_version": 1,
                "payload": payload,
            }
        )
        + "\n"
    )


def _delta(text: str) -> str:
    return _envelope(
        "run.output.delta",
        {
            "command_id": "mounted-stream",
            "run_stream": {"id": "mounted-stream", "kind": "run"},
            "text": text,
        },
    )


def _gated_muse_script() -> str:
    """Emit two deltas, then wait at gates before the second delta and terminal."""
    return (
        """
import json
import os
import sys
import time
from pathlib import Path

def envelope(kind, payload):
    return (json.dumps({
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": kind,
        "payload_schema_version": 1,
        "payload": payload,
    }) + "\\n").encode()

def wait_for(path):
    deadline = time.monotonic() + 8
    while not Path(path).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not Path(path).exists():
        raise SystemExit(42)

command = {"command_id": "mounted-stream",
           "run_stream": {"id": "mounted-stream", "kind": "run"}}
os.write(1, (_delta1 + _delta2).encode())
Path(sys.argv[1]).write_text("first batch sent", encoding="utf-8")
wait_for(sys.argv[2])
os.write(1, _delta3.encode())
Path(sys.argv[3]).write_text("second batch sent", encoding="utf-8")
wait_for(sys.argv[4])
os.write(1, envelope("run.terminal.completed", {
    **command,
    "terminal": "completed",
    "reason": None,
    "text": _answer,
}))
Path(sys.argv[5]).write_text("terminal sent", encoding="utf-8")
""".replace(
            "_delta1",
            repr(_delta("A reply can stream in pieces: ")),
        )
        .replace(
            "_delta2",
            repr(_delta("the words stay together")),
        )
        .replace(
            "_delta3",
            repr(_delta(" and keep growing.")),
        )
        .replace(
            "_answer",
            repr(
                "A reply can stream in pieces: the words stay together and keep growing."
            ),
        )
    )


def _agent(artifacts_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="muse-stream-mounted",
        project_file="/tmp/muse-stream-mounted.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003120000-mounted",
        agent_name="muse-stream-mounted",
        llm_provider="muse",
        model="muse-spark-1.2",
        artifacts_dir=str(artifacts_dir),
    )


def _reply_card_text(page: AcePage) -> str:
    detail = page.app.query_one("#agent-detail-panel")
    card = detail._main_deck_document.card("reply")
    assert card is not None
    console = Console(file=StringIO(), record=True, width=120)
    console.print(card)
    return console.export_text()


def _context_card_text(page: AcePage) -> str:
    detail = page.app.query_one("#agent-detail-panel")
    card = detail._main_deck_document.card("context")
    assert card is not None
    console = Console(file=StringIO(), record=True, width=120)
    console.print(card)
    return console.export_text()


async def _wait_for_page(page: AcePage, predicate: Any, description: str) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"timed out waiting for {description}\n{page.screen}")
        await page.pause(0.025)


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_reply_before_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "muse-stream-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    (artifacts_dir / "01_prompt.md").write_text(
        "Wait for the gated provider reply.\n", encoding="utf-8"
    )
    reply_path = artifacts_dir / "live_reply.md"
    timestamps_path = artifacts_dir / "live_reply_timestamps.jsonl"
    reply_path.write_text("", encoding="utf-8")
    timestamps_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    agent = _agent(artifacts_dir)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"muse-stream-mounted"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await _wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        route_calls: list[tuple[Path, ...]] = []
        on_live_reply_artifact_change = panel.on_live_reply_artifact_change

        def track_live_reply_route(paths: tuple[Path, ...]) -> None:
            route_calls.append(paths)
            on_live_reply_artifact_change(paths)

        monkeypatch.setattr(
            panel, "on_live_reply_artifact_change", track_live_reply_route
        )
        await page.press("ctrl+j")
        await wait_for_visual_idle(page)

        refresh_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        schedule_refresh = page.app._schedule_agents_async_refresh

        def track_refresh(*args: Any, **kwargs: Any) -> Any:
            refresh_calls.append((args, kwargs))
            return schedule_refresh(*args, **kwargs)

        monkeypatch.setattr(page.app, "_schedule_agents_async_refresh", track_refresh)

        first_sent = tmp_path / "first-sent"
        release_second = tmp_path / "release-second"
        second_sent = tmp_path / "second-sent"
        release_terminal = tmp_path / "release-terminal"
        terminal_sent = tmp_path / "terminal-sent"
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                _gated_muse_script(),
                str(first_sent),
                str(release_second),
                str(second_sent),
                str(release_terminal),
                str(terminal_sent),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        parser_task = asyncio.create_task(
            asyncio.to_thread(
                stream_and_parse_muse_json_output,
                process,
                suppress_output=True,
            )
        )
        try:
            await _wait_for_page(page, first_sent.exists, "first Muse delta batch")
            await _wait_for_page(
                page,
                lambda: reply_path.read_text(encoding="utf-8").startswith(
                    "A reply can stream in pieces: the words stay together"
                ),
                "parser to append the first delta batch",
            )
            assert process.poll() is None
            assert not terminal_sent.exists()
            assert not (artifacts_dir / "done.json").exists()

            # Exercise the actual artifact watcher route while the fake provider is
            # blocked before its terminal record.
            await _wait_for_page(
                page,
                lambda: not page.app._nav_gate.is_navigating(),
                "navigation settles before the watcher route",
            )
            page.app._on_artifact_change((reply_path, timestamps_path))
            assert len(route_calls) == 1
            await _wait_for_page(
                page,
                lambda: "A reply can stream in pieces:" in _reply_card_text(page),
                "first partial reply in the mounted Reply card",
            )
            assert process.poll() is None
            assert timestamps_path.read_text(encoding="utf-8").count("\n") == 1
            assert (
                len(re.findall(r"─── \d{2}:\d{2}:\d{2}", _reply_card_text(page))) == 1
            )

            release_second.touch()
            await _wait_for_page(page, second_sent.exists, "second Muse delta")
            await _wait_for_page(
                page,
                lambda: reply_path.read_text(encoding="utf-8").endswith(
                    " and keep growing."
                ),
                "parser to append the final delta",
            )
            assert process.poll() is None
            assert not terminal_sent.exists()

            # Do not send a watcher event for the second append. Force the same
            # stat-only backstop the one-second countdown calls.
            panel._live_reply_last_probe = time.monotonic() - 2
            panel.maybe_probe_live_reply_drift()
            await _wait_for_page(
                page,
                lambda: "and keep growing." in _reply_card_text(page),
                "polling backstop to paint the latest bytes",
            )
            assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
            assert refresh_calls == []

            release_terminal.touch()
            result = await asyncio.wait_for(parser_task, timeout=5)
            assert process.wait(timeout=1) == 0
            assert result[0] == (
                "A reply can stream in pieces: the words stay together and keep growing."
            )
            assert terminal_sent.exists()

            # A normal terminal-state display render consumes the final artifact.
            # The provider's terminal text is authoritative and must not be appended
            # a second time on top of the streamed deltas.
            selected = page.app._get_selected_agent()
            assert selected is not None
            selected.status = "DONE"
            selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
            panel.update_display(selected)
            await wait_for_visual_idle(page)
            assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
            assert "the words stay together and keep growing." in _reply_card_text(page)
            assert panel._live_reply_source is None
        finally:
            for gate in (release_second, release_terminal):
                gate.touch(exist_ok=True)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if not parser_task.done():
                try:
                    await asyncio.wait_for(parser_task, timeout=3)
                except Exception:
                    pass


def _write_mounted_prompt_set(
    artifacts_dir: Path, *, step_name: str | None = None
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    if step_name is None:
        (artifacts_dir / "01_prompt.md").write_text(
            "Wait for the gated provider reply.\n", encoding="utf-8"
        )
    else:
        (artifacts_dir / f"01-{step_name}_prompt.md").write_text(
            "Wait for the gated provider step reply.\n", encoding="utf-8"
        )
    (artifacts_dir / "live_reply.md").write_text("", encoding="utf-8")
    (artifacts_dir / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")


def _build_mounted_workflow_fixture(
    tmp_path: Path, *, cl_name: str, workflow_name: str = "run"
) -> tuple[Path, Path]:
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20261003120000"
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": workflow_name,
                "context": {"cl_name": cl_name},
                "status": "running",
                "appears_as_agent": True,
                "start_time": "2026-10-03T12:00:00",
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    (timestamp_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "workflow_name": workflow_name,
                "step_name": "main",
                "step_type": "agent",
                "status": "in_progress",
                "artifacts_dir": str(timestamp_dir),
                "llm_provider": "muse",
                "model": "muse-spark",
            }
        ),
        encoding="utf-8",
    )
    (timestamp_dir / "agent_meta.json").write_text(
        json.dumps({"name": cl_name, "llm_provider": "muse", "model": "muse-spark"}),
        encoding="utf-8",
    )
    _write_mounted_prompt_set(timestamp_dir, step_name="main")
    # Keep the root prompt newest so the shared directory still resolves the
    # root view to its own prompt file while the step uses its step file.
    step_prompt = timestamp_dir / "01-main_prompt.md"
    root_prompt = timestamp_dir / "01_prompt.md"
    (timestamp_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    root_prompt.write_text("Wait for the gated provider reply.\n", encoding="utf-8")
    step_stat = step_prompt.stat()
    os_utime_ns = step_stat.st_mtime_ns + 2_000_000_000
    os.utime(root_prompt, ns=(step_stat.st_atime_ns, os_utime_ns))
    return project_dir, timestamp_dir


def _build_mounted_session_agents(tmp_path: Path) -> tuple[Agent, Agent, Agent]:
    base = tmp_path / "sess"
    container_dir = base / "container"
    old_dir = base / "old"
    current_dir = base / "current"
    for directory in (container_dir, old_dir, current_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (container_dir / "01_prompt.md").write_text(
        "session context stays\n", encoding="utf-8"
    )
    (old_dir / "01_prompt.md").write_text("old prompt\n", encoding="utf-8")
    (old_dir / "live_reply.md").write_text(
        "older completed turn text", encoding="utf-8"
    )
    (old_dir / "live_reply_timestamps.jsonl").write_text(
        json.dumps({"byte_offset": 0, "timestamp": "2026-10-03T12:09:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    (current_dir / "01_prompt.md").write_text(
        "Wait for the gated provider reply.\n", encoding="utf-8"
    )
    (current_dir / "live_reply.md").write_text("", encoding="utf-8")
    (current_dir / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")

    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003121000",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="root",
        role_suffix="--root",
        llm_provider="muse",
        artifacts_dir=str(container_dir),
    )
    old = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="DONE",
        start_time=datetime(2026, 10, 3, 11, 59, 0),
        stop_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003120900",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp=container.raw_suffix,
        llm_provider="muse",
        artifacts_dir=str(old_dir),
    )
    current = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 1, 0),
        raw_suffix="20261003121100",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp=container.raw_suffix,
        workflow="run",
        appears_as_agent=True,
        llm_provider="muse",
        artifacts_dir=str(current_dir),
    )
    container.followup_agents = [old, current]
    return container, old, current


async def _exercise_gated_stream(
    page: AcePage,
    panel: AgentPromptPanel,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stream_dir: Path,
    *,
    expected_identity: Any,
    expected_dir: Path,
    expected_dividers: int | None = 1,
    old_text: str | None = None,
) -> None:
    reply_path = stream_dir / "live_reply.md"
    timestamps_path = stream_dir / "live_reply_timestamps.jsonl"
    assert panel._live_reply_source is not None
    assert panel._live_reply_source.reply_identity == expected_identity
    assert panel._live_reply_source.reply_path.startswith(str(expected_dir))
    assert _contains_live_reply_region(
        panel._last_prompt_panel_content, expected_identity
    )
    if old_text is not None:
        assert old_text in _reply_card_text(page)

    route_calls: list[tuple[Path, ...]] = []
    on_live_reply_artifact_change = panel.on_live_reply_artifact_change

    def track_live_reply_route(paths: tuple[Path, ...]) -> None:
        route_calls.append(paths)
        on_live_reply_artifact_change(paths)

    monkeypatch.setattr(panel, "on_live_reply_artifact_change", track_live_reply_route)
    await page.press("ctrl+j")
    await wait_for_visual_idle(page)

    refresh_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    schedule_refresh = page.app._schedule_agents_async_refresh

    def track_refresh(*args: Any, **kwargs: Any) -> Any:
        refresh_calls.append((args, kwargs))
        return schedule_refresh(*args, **kwargs)

    monkeypatch.setattr(page.app, "_schedule_agents_async_refresh", track_refresh)

    first_sent = tmp_path / "first-sent"
    release_second = tmp_path / "release-second"
    second_sent = tmp_path / "second-sent"
    release_terminal = tmp_path / "release-terminal"
    terminal_sent = tmp_path / "terminal-sent"
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            _gated_muse_script(),
            str(first_sent),
            str(release_second),
            str(second_sent),
            str(release_terminal),
            str(terminal_sent),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    parser_task = asyncio.create_task(
        asyncio.to_thread(
            stream_and_parse_muse_json_output,
            process,
            suppress_output=True,
        )
    )
    try:
        await _wait_for_page(page, first_sent.exists, "first Muse delta batch")
        await _wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").startswith(
                "A reply can stream in pieces: the words stay together"
            ),
            "parser to append the first delta batch",
        )
        assert process.poll() is None
        assert not terminal_sent.exists()
        assert not (stream_dir / "done.json").exists()

        await _wait_for_page(
            page,
            lambda: not page.app._nav_gate.is_navigating(),
            "navigation settles before the watcher route",
        )
        page.app._on_artifact_change((reply_path, timestamps_path))
        assert len(route_calls) == 1
        await _wait_for_page(
            page,
            lambda: "A reply can stream in pieces:" in _reply_card_text(page),
            "first partial reply in the mounted Reply card",
        )
        assert process.poll() is None
        assert timestamps_path.read_text(encoding="utf-8").count("\n") == 1
        if expected_dividers is not None:
            assert (
                len(re.findall(r"─── \d{2}:\d{2}:\d{2}", _reply_card_text(page)))
                == expected_dividers
            )
        if old_text is not None:
            assert _reply_card_text(page).count(old_text) == 1

        release_second.touch()
        await _wait_for_page(page, second_sent.exists, "second Muse delta")
        await _wait_for_page(
            page,
            lambda: reply_path.read_text(encoding="utf-8").endswith(
                " and keep growing."
            ),
            "parser to append the final delta",
        )
        assert process.poll() is None
        assert not terminal_sent.exists()

        panel._live_reply_last_probe = time.monotonic() - 2
        panel.maybe_probe_live_reply_drift()
        await _wait_for_page(
            page,
            lambda: "and keep growing." in _reply_card_text(page),
            "polling backstop to paint the latest bytes",
        )
        assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert refresh_calls == []
        if old_text is not None:
            assert _reply_card_text(page).count(old_text) == 1

        release_terminal.touch()
        result = await asyncio.wait_for(parser_task, timeout=5)
        assert process.wait(timeout=1) == 0
        assert result[0] == (
            "A reply can stream in pieces: the words stay together and keep growing."
        )
        assert terminal_sent.exists()
    finally:
        for gate in (release_second, release_terminal):
            gate.touch(exist_ok=True)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if not parser_task.done():
            try:
                await asyncio.wait_for(parser_task, timeout=3)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_workflow_root_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir, timestamp_dir = _build_mounted_workflow_fixture(
        tmp_path, cl_name="muse-stream-workflow-root"
    )
    roots = load_workflow_agents(timestamp_dirs=[(project_dir, timestamp_dir)])
    assert len(roots) == 1
    agent = roots[0]
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(timestamp_dir))
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"muse-stream-workflow-root"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await _wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        await _exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            timestamp_dir,
            expected_identity=agent.identity,
            expected_dir=timestamp_dir,
        )

        selected = page.app._get_selected_agent()
        assert selected is not None
        selected.status = "DONE"
        selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in _reply_card_text(page)
        assert panel._live_reply_source is None


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_workflow_step_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.ace.tui.actions.navigation._agent_reveal import (
        prepare_agent_navigation_target,
        reveal_agent_navigation_target,
    )

    project_dir, timestamp_dir = _build_mounted_workflow_fixture(
        tmp_path, cl_name="muse-stream-workflow-step"
    )
    roots = load_workflow_agents(timestamp_dirs=[(project_dir, timestamp_dir)])
    steps, _meta = load_workflow_agent_steps(
        timestamp_dirs=[(project_dir, timestamp_dir)]
    )
    assert len(roots) == 1
    assert len(steps) == 1
    agent = steps[0]
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(timestamp_dir))
    patch_startup_loaders(monkeypatch, agents=[*roots, *steps])

    async with AcePage(
        query="",
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        # Workflow agent steps nest under their parent workflow row. Reveal
        # the loader-created step through the production jump-to-agent path,
        # then move the highlight with real keys like a user would.
        plan, failure = prepare_agent_navigation_target(
            page.app, agent.identity, require_current=False
        )
        assert failure is None, failure
        assert plan is not None
        outcome = reveal_agent_navigation_target(page.app, plan)
        assert outcome.succeeded, outcome.failure
        await wait_for_visual_idle(page)
        for _ in range(10):
            selected = page.app._get_selected_agent()
            if selected is not None and selected.identity == agent.identity:
                break
            await page.press("j")
            await wait_for_visual_idle(page)
        selected = page.app._get_selected_agent()
        assert selected is not None
        assert selected.identity == agent.identity
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await _wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        await _exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            timestamp_dir,
            expected_identity=agent.identity,
            expected_dir=timestamp_dir,
        )

        selected = page.app._get_selected_agent()
        assert selected is not None
        selected.status = "DONE"
        selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in _reply_card_text(page)
        assert panel._live_reply_source is None


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_session_current_turn_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container, _old, current = _build_mounted_session_agents(tmp_path)
    stream_dir = Path(current.artifacts_dir or "")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(stream_dir))
    patch_startup_loaders(monkeypatch, agents=[container])

    async with AcePage(
        query='"sess-stream"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await _wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        assert panel._live_reply_source is not None
        assert panel._live_reply_source.reply_identity == current.identity
        await _exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            stream_dir,
            expected_identity=current.identity,
            expected_dir=stream_dir,
            # Session Reply cards also render per-turn phase dividers that
            # match the timestamp-divider pattern, so exact divider counts
            # are asserted on the single-agent shapes above. Here the
            # older/newer text singleton counts prove clean concatenation.
            expected_dividers=None,
            old_text="older completed turn text",
        )
        # Older reply blocks keep their identity (two-turn roster intact)
        # while only the current turn grew, and Context is untouched.
        assert "· 2" in _reply_card_text(page)
        assert "session context stays" in _context_card_text(page)

        selected = page.app._get_selected_agent()
        assert selected is not None
        turn = current_agent_session_turn_row(selected)
        assert turn is not None
        assert turn.identity == current.identity
        turn.status = "DONE"
        turn.stop_time = datetime(2026, 10, 3, 12, 2, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert _reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in _reply_card_text(page)
        assert _reply_card_text(page).count("older completed turn text") == 1
        assert panel._live_reply_source is None
