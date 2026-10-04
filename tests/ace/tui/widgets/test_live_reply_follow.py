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
from sase.ace.tui.widgets.prompt_panel._live_reply_follow import (
    LiveReplyFollowMixin,
    _LiveReplySource as LiveReplySource,
    _collect_live_reply_snapshot as collect_live_reply_snapshot,
    _contains_live_reply_region as contains_live_reply_region,
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
