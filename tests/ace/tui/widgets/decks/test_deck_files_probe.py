"""Files deck spread probe: worker completion gate and live spread pilot."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.worker import Worker, WorkerState

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from sase.ace.tui.widgets.decks.panel_files import DeckPanelFilesMixin
from sase.ace.tui.widgets.file_panel._spread_probe import (
    FilesSpreadPage,
    FilesSpreadProbe,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _two_page_agent(tmp_path: Path) -> Any:
    notes = tmp_path / "review_notes.md"
    notes.write_text("# Review Notes\n\n- First point.\n", encoding="utf-8")
    plan = tmp_path / "implementation_plan.md"
    plan.write_text("# Implementation Plan\n\n1. Do it.\n", encoding="utf-8")
    return make_agent(
        agent_name="pilot",
        status="DONE",
        extra_files=[str(notes), str(plan)],
    )


async def test_files_deck_spreads_live_without_a_hand_fed_probe(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(_two_page_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)

        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))

        # The worker's own StateChanged applied the probe; nothing fed it.
        assert panel._files_pending_probe is None
        assert len(panel._files_probe_pages) == 2
        assert panel._render_mode[DeckId.FILES] is RenderMode.SPREAD
        assert "spread" in panel._border_subtitle.plain


async def test_files_probe_error_clears_pending_and_stays_paged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        calls.append(1)
        raise RuntimeError("probe failed")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._spread_probe.probe_files_spread", _boom
    )
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(_two_page_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)

        # A failing probe must not crash the app and must settle the pending slot.
        await wait_for(
            pilot, lambda: bool(calls) and panel._files_pending_probe is None
        )
        assert panel._files_pending_probe is None
        assert panel._files_probe_pages == ()
        assert panel._render_mode[DeckId.FILES] is RenderMode.PAGED


def _probe() -> FilesSpreadProbe:
    page = FilesSpreadPage(slot="a.md", label="a.md", text="hi\n", lexer="markdown")
    return FilesSpreadProbe(
        pages=(page,),
        total_rows=3,
        exceeded=False,
        bound=10.0,
        has_solo=False,
    )


class _Host(DeckPanelFilesMixin):
    """Minimal host exposing only what the completion gate touches."""

    def __init__(self, pending: Any) -> None:
        self._files_pending_probe = pending
        self._on_files_probe_result = MagicMock()  # type: ignore[method-assign]


def _event(worker: Any, state: WorkerState) -> Worker.StateChanged:
    return cast(Worker.StateChanged, SimpleNamespace(worker=worker, state=state))


def _pending(worker: Any) -> tuple[Any, ...]:
    return (worker, "agent", ("a.md",), "subject")


def test_gate_applies_result_on_success_and_clears_pending() -> None:
    probe = _probe()
    worker = SimpleNamespace(result=probe)
    host = _Host(_pending(worker))

    host.on_worker_state_changed(_event(worker, WorkerState.SUCCESS))

    assert host._files_pending_probe is None
    host._on_files_probe_result.assert_called_once_with(
        probe, "agent", ("a.md",), "subject"
    )


@pytest.mark.parametrize("state", [WorkerState.ERROR, WorkerState.CANCELLED])
def test_gate_clears_pending_without_applying_on_error_or_cancel(
    state: WorkerState,
) -> None:
    worker = SimpleNamespace(result=None)
    host = _Host(_pending(worker))

    host.on_worker_state_changed(_event(worker, state))

    assert host._files_pending_probe is None
    host._on_files_probe_result.assert_not_called()


@pytest.mark.parametrize("state", [WorkerState.PENDING, WorkerState.RUNNING])
def test_gate_ignores_non_terminal_states(state: WorkerState) -> None:
    worker = SimpleNamespace(result=None)
    pending = _pending(worker)
    host = _Host(pending)

    host.on_worker_state_changed(_event(worker, state))

    assert host._files_pending_probe is pending
    host._on_files_probe_result.assert_not_called()


@pytest.mark.parametrize("state", list(WorkerState))
def test_gate_ignores_other_workers(state: WorkerState) -> None:
    worker = SimpleNamespace(result=_probe())
    pending = _pending(worker)
    host = _Host(pending)

    host.on_worker_state_changed(_event(SimpleNamespace(result=_probe()), state))

    assert host._files_pending_probe is pending
    host._on_files_probe_result.assert_not_called()


def test_gate_is_a_no_op_without_a_pending_probe() -> None:
    host = _Host(None)

    host.on_worker_state_changed(
        _event(SimpleNamespace(result=_probe()), WorkerState.SUCCESS)
    )

    assert host._files_pending_probe is None
    host._on_files_probe_result.assert_not_called()


def test_gate_drops_a_non_probe_result() -> None:
    worker = SimpleNamespace(result="not a probe")
    host = _Host(_pending(worker))

    host.on_worker_state_changed(_event(worker, WorkerState.SUCCESS))

    assert host._files_pending_probe is None
    host._on_files_probe_result.assert_not_called()
