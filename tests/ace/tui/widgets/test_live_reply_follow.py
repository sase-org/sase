"""Targeted replacement and file snapshots for selected live Reply cards."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from rich.console import Group
from rich.console import Console
from rich.text import Text
import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import (
    card_document,
    context_card,
    reply_card,
    split_card_parts,
)
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
    get_prompt_content,
)
from sase.ace.tui.models._loaders._workflow_step_loaders import (
    load_workflow_agent_steps,
)
from sase.ace.tui.widgets.prompt_panel._live_reply_follow import (
    LiveReplyFollowMixin,
    _LiveReplySource as LiveReplySource,
    _collect_live_reply_snapshot as collect_live_reply_snapshot,
    _contains_live_reply_region as contains_live_reply_region,
    _selected_live_reply_agent as selected_live_reply_agent,
    is_live_reply_agent,
    live_reply_region,
    _replace_live_reply_region as replace_live_reply_region,
)
from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

_IDENTITY = ("running", "agent", "20261003123456")


class _NavGate:
    def is_navigating(self) -> bool:
        return False


class _Timer:
    def __init__(self, callback: object) -> None:
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _ReplyController(LiveReplyFollowMixin):
    def __init__(self, agent: Agent, content: object) -> None:
        self.id = "agent-prompt-panel"
        self.app = SimpleNamespace(
            current_tab="agents",
            _get_selected_agent=lambda: agent,
            _nav_gate=_NavGate(),
            _prompt_input_active=lambda: False,
        )
        self._agent_detail_render_context = SimpleNamespace(
            generation=5,
            attempt_view_mode="merged",
            attempt_pinned_number=None,
            is_current=lambda *_args: True,
        )
        self.attempt_view_mode = "merged"
        self.attempt_pinned_number = None
        self._agent_hint_mode_rendered = False
        self._live_reply_render_generation = 5
        self._last_prompt_panel_content = content
        self.timers: list[_Timer] = []
        self.published: list[object] = []

    def set_timer(self, _delay: float, callback: object) -> _Timer:
        timer = _Timer(callback)
        self.timers.append(timer)
        return timer

    def update(self, content: object) -> None:
        self._last_prompt_panel_content = content
        self.published.append(content)
        event = getattr(self, "published_event", None)
        if event is not None:
            event.set()


async def _fire_and_wait(controller: _ReplyController) -> None:
    controller._live_reply_pending = True
    controller._live_reply_timer_fired()
    for _ in range(100):
        if not controller._live_reply_running:
            return
        await asyncio.sleep(0.01)  # sase-test-wait: poll for async follow completion
    raise AssertionError("live reply collection did not finish")


def _touch_with_new_signature(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def _controller_for_empty_reply(source_dir: Path, agent: Agent) -> _ReplyController:
    identity = agent.identity
    content = card_document(
        context_card(Text("context stays")),
        reply_card(
            Text("AGENT REPLY"),
            live_reply_region(identity, [Text("Waiting for agent response...")]),
        ),
    )
    controller = _ReplyController(agent, content)
    controller._live_reply_source = LiveReplySource(
        selected_identity=identity,
        reply_identity=identity,
        generation=5,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        reply_path=str(source_dir / "live_reply.md"),
        timestamps_path=str(source_dir / "live_reply_timestamps.jsonl"),
    )
    return controller


def test_replace_live_reply_region_keeps_context_and_session_block_identity() -> None:
    block = CardBlock(
        "running|agent|20261003123456",
        "AGENT",
        Text("turn heading"),
        live_reply_region(_IDENTITY, [Text("old fragment")]),
        meta=BlockMeta("0", "agent", "", "#fff", "Running", "agent"),
    )
    context = context_card(Text("latest context"))
    reply = reply_card(Text("session title"), block)
    document = card_document(context, reply)

    updated, count = replace_live_reply_region(
        document, _IDENTITY, (Text("grown reply"),)
    )

    assert count == 1
    assert isinstance(updated, Group)
    parts = split_card_parts(updated)
    assert parts[0] is context
    assert parts[1].card_id == "reply"
    updated_block = parts[1].blocks[0]
    assert updated_block.block_id == block.block_id
    assert updated_block.meta == block.meta
    region = updated_block.renderables[1]
    assert contains_live_reply_region(parts[1], _IDENTITY)
    assert isinstance(region, type(live_reply_region(_IDENTITY, ())))
    assert tuple(region.renderables) == (Text("grown reply"),)


def testcollect_live_reply_snapshot_uses_joint_timestamped_chunks(
    tmp_path: Path,
) -> None:
    reply_path = tmp_path / "live_reply.md"
    timestamps_path = tmp_path / "live_reply_timestamps.jsonl"
    reply_path.write_text("café in flight", encoding="utf-8")
    timestamps_path.write_text(
        json.dumps({"byte_offset": 0, "timestamp": "2026-10-03T12:34:56+00:00"}) + "\n",
        encoding="utf-8",
    )
    source = LiveReplySource(
        selected_identity=_IDENTITY,
        reply_identity=_IDENTITY,
        generation=7,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        reply_path=str(reply_path),
        timestamps_path=str(timestamps_path),
    )

    snapshot = collect_live_reply_snapshot(source)

    assert snapshot.source == source
    assert snapshot.chunks == (("2026-10-03T12:34:56+00:00", "café in flight"),)
    assert snapshot.signatures[0] is not None
    assert snapshot.signatures[1] is not None


def test_reply_watcher_event_reaches_controller_without_dirtying_agents(
    tmp_path: Path,
) -> None:
    reply_path = tmp_path / "artifacts" / "ace-run" / "20261003123456" / "live_reply.md"

    class ReplyPanel:
        def __init__(self) -> None:
            self.paths: tuple[Path, ...] = ()

        def on_live_reply_artifact_change(self, paths: tuple[Path, ...]) -> None:
            self.paths = tuple(path for path in paths if path == reply_path)

    app = _FakeApp(watcher_active=True)
    panel = ReplyPanel()
    detail = SimpleNamespace(_deck_source_panel=lambda: panel)
    app.query_one = lambda _selector: detail  # type: ignore[attr-defined]

    app._on_artifact_change((reply_path,))

    assert panel.paths == (reply_path,)
    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_patches is False
    assert app._dirty_axe is False


@pytest.mark.asyncio
async def test_controller_publishes_a_fresh_snapshot_through_the_current_document(
    tmp_path: Path,
) -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003123456",
    )
    identity = agent.identity
    source_dir = tmp_path / "artifacts" / "ace-run" / "20261003123456"
    source_dir.mkdir(parents=True)
    (source_dir / "live_reply.md").write_text("first words", encoding="utf-8")
    (source_dir / "live_reply_timestamps.jsonl").write_text(
        json.dumps({"byte_offset": 0, "timestamp": "2026-10-03T12:34:56+00:00"}) + "\n",
        encoding="utf-8",
    )
    content = card_document(
        context_card(Text("context stays")),
        reply_card(Text("AGENT REPLY"), live_reply_region(identity, [Text("old")])),
    )
    controller = _ReplyController(agent, content)
    controller.published_event = asyncio.Event()
    controller._live_reply_source = LiveReplySource(
        selected_identity=agent.identity,
        reply_identity=identity,
        generation=5,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        reply_path=str(source_dir / "live_reply.md"),
        timestamps_path=str(source_dir / "live_reply_timestamps.jsonl"),
    )
    controller._live_reply_pending = True

    controller._live_reply_timer_fired()

    async def wait_for_live_reply_publication() -> None:
        await asyncio.wait_for(controller.published_event.wait(), timeout=1.0)

    await wait_for_live_reply_publication()

    console = Console(record=True, width=90)
    console.print(controller.published[-1])
    visible = console.export_text()
    assert "context stays" in visible
    assert "first words" in visible
    assert "old" not in visible

    reply_path = source_dir / "live_reply.md"
    timestamps_path = source_dir / "live_reply_timestamps.jsonl"
    reply_path.write_text("", encoding="utf-8")
    timestamps_path.write_text("", encoding="utf-8")
    await _fire_and_wait(controller)

    assert len(controller.published) == 2
    console = Console(record=True, width=90)
    console.print(controller.published[-1])
    assert "Waiting for agent response..." in console.export_text()

    _touch_with_new_signature(reply_path)
    _touch_with_new_signature(timestamps_path)
    await _fire_and_wait(controller)
    assert len(controller.published) == 2


@pytest.mark.asyncio
async def test_empty_snapshot_keeps_first_paint_placeholder_until_reply_exists(
    tmp_path: Path,
) -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003123456",
    )
    source_dir = tmp_path / "artifacts" / "ace-run" / "20261003123456"
    source_dir.mkdir(parents=True)
    reply_path = source_dir / "live_reply.md"
    timestamps_path = source_dir / "live_reply_timestamps.jsonl"
    reply_path.write_text("", encoding="utf-8")
    timestamps_path.write_text("", encoding="utf-8")
    controller = _controller_for_empty_reply(source_dir, agent)

    await _fire_and_wait(controller)

    assert controller.published == []
    console = Console(record=True, width=90)
    console.print(controller._last_prompt_panel_content)
    assert "Waiting for agent response..." in console.export_text()

    _touch_with_new_signature(reply_path)
    _touch_with_new_signature(timestamps_path)
    await _fire_and_wait(controller)
    assert controller.published == []


_START = datetime(2026, 10, 3, 12, 0, 0)


def _eligibility_agent(**kwargs: object) -> Agent:
    fields: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "agent",
        "project_file": "/tmp/test.sase",
        "status": "RUNNING",
        "start_time": _START,
        "raw_suffix": "20261003120000",
    }
    fields.update(kwargs)
    return Agent(**fields)  # type: ignore[arg-type]


def test_is_live_reply_agent_accepts_running_and_workflow_agent_rows() -> None:
    eligible = [
        _eligibility_agent(llm_provider="muse"),
        _eligibility_agent(llm_provider="codex"),
        _eligibility_agent(
            agent_type=AgentType.WORKFLOW,
            workflow="run",
            appears_as_agent=True,
            llm_provider="muse",
        ),
        _eligibility_agent(
            agent_type=AgentType.WORKFLOW,
            workflow="run",
            appears_as_agent=True,
            llm_provider="codex",
        ),
        _eligibility_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="main",
            workflow="run",
            parent_workflow="run",
            parent_timestamp="20261003120000",
            step_name="main",
            step_type="agent",
            llm_provider="muse",
        ),
    ]
    for agent in eligible:
        assert agent.is_agent_entry is True
        assert is_live_reply_agent(agent) is True


def test_is_live_reply_agent_rejects_non_agent_and_settled_rows() -> None:
    stopped = datetime(2026, 10, 3, 12, 1, 0)
    ineligible = [
        # Ordinary workflow aggregate with no agent presentation.
        _eligibility_agent(agent_type=AgentType.WORKFLOW, workflow="run"),
        # Non-agent workflow steps never carry assistant text.
        _eligibility_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cmd",
            workflow="run",
            parent_workflow="run",
            parent_timestamp="20261003120000",
            step_name="cmd",
            step_type="bash",
        ),
        _eligibility_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cmd",
            workflow="run",
            parent_workflow="run",
            parent_timestamp="20261003120000",
            step_name="cmd",
            step_type="python",
        ),
        _eligibility_agent(agent_type=AgentType.RUNNING, is_clan_container=True),
        _eligibility_agent(
            agent_session="sess",
            agent_session_role="monitor",
            role_suffix="--mon-1",
            monitor_id="m1",
            monitor_state="running",
            status="MONITORING",
        ),
        _eligibility_agent(
            agent_session="sess",
            agent_session_role="gate",
            role_suffix="--gate",
            gate_id="g1",
            gate_kind="test",
            gate_state="settling",
            gate_label="g1",
            status="GATE",
        ),
        _eligibility_agent(agent_type=AgentType.NAMED_PROC, status="RUNNING"),
        _eligibility_agent(status="DONE", stop_time=stopped),
        _eligibility_agent(status="RUNNING", stop_time=stopped),
    ]
    for agent in ineligible:
        assert is_live_reply_agent(agent) is False


def _session_container_with_turns(
    old_status: str = "DONE",
    *,
    current: Agent,
    old_raw_suffix: str = "20261003115900",
) -> Agent:
    root = _eligibility_agent(
        cl_name="sess",
        raw_suffix="20261003120000",
        agent_name="sess",
        agent_session="sess",
        agent_session_role="root",
        role_suffix="--root",
    )
    old = _eligibility_agent(
        cl_name="sess",
        raw_suffix=old_raw_suffix,
        agent_name="sess",
        agent_session="sess",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp=root.raw_suffix,
        status=old_status,
        stop_time=_START if old_status == "DONE" else None,
    )
    root.followup_agents = [old, current]
    return root


def test_selected_live_reply_agent_resolves_current_workflow_turn() -> None:
    current = _eligibility_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sess",
        raw_suffix="20261003120100",
        agent_name="sess",
        agent_session="sess",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp="20261003120000",
        workflow="run",
        appears_as_agent=True,
        llm_provider="muse",
    )
    session = _session_container_with_turns(current=current)

    assert selected_live_reply_agent(session) is current


def test_selected_live_reply_agent_ignores_monitor_and_gate_turns() -> None:
    monitor = _eligibility_agent(
        cl_name="sess",
        raw_suffix="20261003120100",
        agent_name="sess",
        agent_session="sess",
        agent_session_role="monitor",
        role_suffix="--mon-1",
        parent_timestamp="20261003120000",
        monitor_id="m1",
        monitor_state="running",
        status="MONITORING",
    )
    assert (
        selected_live_reply_agent(_session_container_with_turns(current=monitor))
        is None
    )

    gate = _eligibility_agent(
        cl_name="sess",
        raw_suffix="20261003120100",
        agent_name="sess",
        agent_session="sess",
        agent_session_role="gate",
        role_suffix="--gate",
        parent_timestamp="20261003120000",
        gate_id="g1",
        gate_kind="test",
        gate_state="settling",
        gate_label="g1",
        status="GATE",
    )
    assert (
        selected_live_reply_agent(_session_container_with_turns(current=gate)) is None
    )


def _write_workflow_live_reply_fixture(
    tmp_path: Path,
    *,
    is_anonymous: bool,
    workflow_name: str,
    llm_provider: str = "muse",
) -> tuple[Path, Path]:
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20261003120000"
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": workflow_name,
                "context": {"cl_name": "wf-agent"},
                "status": "running",
                "appears_as_agent": True,
                "is_anonymous": is_anonymous,
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
                "llm_provider": llm_provider,
                "model": "muse-spark",
            }
        ),
        encoding="utf-8",
    )
    meta: dict[str, object] = {
        "name": "wf-agent",
        "llm_provider": llm_provider,
        "model": "muse-spark",
    }
    if not is_anonymous:
        meta["vcs_provider"] = "gh"
    (timestamp_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    # Write the step-specific prompt first, then force the root prompt to a
    # newer mtime so it remains the root's selected prompt file.
    step_prompt_path = timestamp_dir / "01-main_prompt.md"
    root_prompt_path = timestamp_dir / "01_prompt.md"
    step_prompt_path.write_text(f"step prompt for {workflow_name}\n", encoding="utf-8")
    root_prompt_path.write_text(f"root prompt for {workflow_name}\n", encoding="utf-8")
    step_stat = step_prompt_path.stat()
    os.utime(
        root_prompt_path,
        ns=(step_stat.st_atime_ns, step_stat.st_mtime_ns + 2_000_000_000),
    )
    return project_dir, timestamp_dir


@pytest.mark.parametrize(
    ("is_anonymous", "workflow_name"),
    [(True, "run"), (False, "gh")],
)
def test_production_workflow_loaders_return_eligible_agent_rows(
    tmp_path: Path,
    *,
    is_anonymous: bool,
    workflow_name: str,
) -> None:
    project_dir, timestamp_dir = _write_workflow_live_reply_fixture(
        tmp_path, is_anonymous=is_anonymous, workflow_name=workflow_name
    )

    roots = load_workflow_agents(timestamp_dirs=[(project_dir, timestamp_dir)])
    steps, _meta = load_workflow_agent_steps(
        timestamp_dirs=[(project_dir, timestamp_dir)]
    )

    assert len(roots) == 1
    root = roots[0]
    assert root.agent_type == AgentType.WORKFLOW
    assert root.appears_as_agent is True
    assert root.is_anonymous is is_anonymous
    assert root.is_agent_entry is True
    assert is_live_reply_agent(root) is True
    assert root.get_artifacts_dir() == str(timestamp_dir)
    assert get_prompt_content(root) is not None
    assert "root prompt" in (get_prompt_content(root) or "")

    assert len(steps) == 1
    step = steps[0]
    assert step.agent_type == AgentType.WORKFLOW
    assert step.is_workflow_step_child is True
    assert step.step_type == "agent"
    assert step.is_agent_entry is True
    assert is_live_reply_agent(step) is True
    assert step.get_artifacts_dir() == str(timestamp_dir)
    assert "step prompt" in (get_prompt_content(step) or "")
