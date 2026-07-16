"""Async bead display resolution tests for the agent prompt panel."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bead import (
    _BEAD_DISPLAY_CACHE,
    _bead_display_cache_key,
    agent_has_confirmed_bead,
    should_resolve_bead_display,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    cache_detail_header_summary,
    get_cached_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._workflow_display import WorkflowDisplayMixin
from sase.bead.model import Issue
from tests.ace.tui.widgets._agent_display_helpers import make_agent, plain_of


@pytest.fixture(autouse=True)
def _clear_bead_display_cache() -> Iterator[None]:
    _BEAD_DISPLAY_CACHE.clear()
    yield
    _BEAD_DISPLAY_CACHE.clear()


class _FakeWorker:
    def __init__(self, result: object | None = None) -> None:
        self.is_running = True
        self.result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class _BeadPanel(AgentDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []
        self.worker = _FakeWorker()
        self.worker_fn: Callable[[], object] | None = None

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)

    def run_worker(self, fn: Callable[[], object], *, thread: bool) -> _FakeWorker:
        assert thread
        self.worker_fn = fn
        return self.worker


def _set_context(panel: AgentDisplayMixin, agent: Agent, *, current: bool) -> None:
    def is_current(
        agent_identity: tuple[Any, ...],
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        return (
            current
            and agent_identity == agent.identity
            and generation == 7
            and attempt_view_mode == "merged"
            and attempt_pinned_number is None
        )

    panel.set_agent_detail_render_context(
        generation=7,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=is_current,
    )


def test_cold_bead_display_schedules_worker_without_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)

    def fail_lookup(bead_id: str, **_: object) -> Issue | None:
        raise AssertionError("cold header render must not touch bead storage")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", fail_lookup)

    panel.update_display(agent)

    # Cold cache: the header omits the Bead row, and the worker is scheduled to
    # confirm the candidate off the event loop.
    assert panel.worker_fn is not None
    rendered = plain_of(panel.captured[-1])
    assert "Name: sase-x.3\n" in rendered
    assert "Bead:" not in rendered


def test_modern_phase_bypasses_generic_bead_worker_and_is_row_confirmed() -> None:
    agent = make_agent(
        agent_name="sase-x.3",
        epic_bead_id="sase-x",
        phase_bead_id="sase-x.3",
    )
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)

    panel.update_display(agent)

    assert agent_has_confirmed_bead(agent)
    assert not should_resolve_bead_display(agent)
    assert "Bead: sase-x.3\n" in plain_of(panel.captured[-1])
    assert getattr(panel, "_agent_bead_display_worker", None) is None
    assert getattr(panel, "_agent_detail_header_worker", None) is panel.worker


def test_successful_bead_worker_rerenders_cached_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)

    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: Issue(
            id=bead_id,
            title="Phase title",
            description="First line",
        ),
    )

    panel.update_display(agent)
    # Until the worker confirms existence, no Bead row is rendered.
    assert "Bead:" not in plain_of(panel.captured[-1])
    assert panel.worker_fn is not None
    assert panel.worker_fn() == "sase-x.3 - First line"

    panel._apply_agent_bead_display_worker_result(
        cast(Worker[Any], panel.worker), WorkerState.SUCCESS
    )

    assert "Bead: sase-x.3 - First line\n" in plain_of(panel.captured[-1])


def test_expired_bead_display_renders_stale_while_worker_revalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale description")
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: Issue(
            id=bead_id,
            title="Phase title",
            description="stale description",
        ),
    )

    panel.update_display(agent)

    rendered = plain_of(panel.captured[-1])
    assert "Bead: sase-x.3 - stale description\n" in rendered
    assert panel.worker_fn is not None
    assert panel.worker_fn() == "sase-x.3 - stale description"


def test_deleted_bead_worker_discards_cached_summary_before_rerender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale description")
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)
    cache_detail_header_summary(
        panel,
        agent,
        DetailHeaderSummary(bead_display="sase-x.3 - stale description"),
    )
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: None,
    )

    panel.update_display(agent)
    assert "Bead: sase-x.3 - stale description\n" in plain_of(panel.captured[-1])
    assert panel.worker_fn is not None
    assert panel.worker_fn() is None

    panel._apply_agent_bead_display_worker_result(
        cast(Worker[Any], panel.worker), WorkerState.SUCCESS
    )

    assert "Bead:" not in plain_of(panel.captured[-1])
    summary = get_cached_detail_header_summary(panel, agent)
    assert summary is not None
    assert summary.bead_display is None


def test_missing_bead_worker_stays_silent_and_does_not_reschedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    panel = _BeadPanel()
    _set_context(panel, agent, current=True)

    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: None,
    )

    panel.update_display(agent)
    assert "Bead:" not in plain_of(panel.captured[-1])
    assert panel.worker_fn is not None

    # Worker resolves the candidate as missing and caches None.
    assert panel.worker_fn() is None
    panel._apply_agent_bead_display_worker_result(
        cast(Worker[Any], panel.worker), WorkerState.SUCCESS
    )

    # The re-render stays silent: no Bead row for a missing candidate.
    assert "Bead:" not in plain_of(panel.captured[-1])

    # A subsequent selection of the same agent does not reschedule a lookup:
    # the cached None keeps ``should_resolve_bead_display`` false until TTL.
    panel.worker_fn = None
    panel.update_display(agent)
    assert panel.worker_fn is None


def test_stale_bead_worker_result_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3")
    panel = _BeadPanel()
    _set_context(panel, agent, current=False)

    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda bead_id, **_: Issue(
            id=bead_id,
            title="Phase title",
            description="First line",
        ),
    )

    panel.update_display(agent)
    assert panel.worker_fn is not None
    panel.worker_fn()
    captured_count = len(panel.captured)

    panel._apply_agent_bead_display_worker_result(
        cast(Worker[Any], panel.worker), WorkerState.SUCCESS
    )

    assert len(panel.captured) == captured_count


class _WorkerEvent:
    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = cast(Worker[Any], worker)
        self.state = state


class _CombinedPanel(AgentDisplayMixin, WorkflowDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []
        self.worker = _FakeWorker(result=Text("workflow rendered"))

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)

    def run_worker(self, _fn: Callable[[], object], *, thread: bool) -> _FakeWorker:
        assert thread
        return self.worker


def test_bead_worker_handler_chains_to_workflow_worker_handler() -> None:
    agent = make_agent(agent_type=AgentType.WORKFLOW, workflow="demo")
    panel = _CombinedPanel()
    panel.start_workflow_detail_render(
        agent,
        generation=1,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda *_args: True,
    )

    panel.on_worker_state_changed(
        cast(Worker.StateChanged, _WorkerEvent(panel.worker, WorkerState.SUCCESS))
    )

    assert plain_of(panel.captured[-1]) == "workflow rendered"
