"""Pilot Files deck-view policy tests: fixed views and the complete probe."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from sase.ace.tui.widgets.decks.view_policy import ViewStatus
from sase.ace.tui.widgets.file_panel._spread_probe import FilesSpreadProbe
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_ROOT = Path(__file__).resolve().parents[5]

_MEDIA_TOAST = "Files stays paged: images and videos can't spread"


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _write(path: Path, lines: int) -> str:
    path.write_text("".join(f"line-{i:04d}\n" for i in range(lines)), encoding="utf-8")
    return str(path)


def _text_agent(tmp_path: Path, *, lines: int = 100) -> Any:
    first = _write(tmp_path / "alpha.py", lines)
    second = _write(tmp_path / "beta.py", lines)
    return make_agent(
        agent_name="pilot",
        status="DONE",
        extra_files=[first, second],
    )


def _media_agent(tmp_path: Path) -> Any:
    notes = _write(tmp_path / "notes.md", 10)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    return make_agent(
        agent_name="pilot",
        status="DONE",
        extra_files=[notes, str(shot)],
    )


async def _files_panel(app: _DetailApp) -> Any:
    detail = app.query_one("#agent-detail-panel", AgentDetail)
    return detail.deck_area.panel(0)


async def test_fixed_spread_spreads_after_complete_probe(tmp_path: Path) -> None:
    # Two 100-line files exceed the bounded auto budget, so only a
    # complete probe may spread this deck under a fixed policy.
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.deck_area.set_panel_view(0, DeckId.FILES, DeckView.SPREAD)
        detail.update_display(_text_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _files_panel(app)

        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))

        assert panel.view_policy(DeckId.FILES) is DeckView.SPREAD
        assert panel._files_probe_complete is True
        assert panel._files_probe_exceeded is False
        assert len(panel._files_probe_pages) == 2
        assert all(not page.truncated for page in panel._files_probe_pages)
        assert panel._files_spread_pending is False
        assert panel._files_spread_blocked is False


async def test_fixed_page_cards_never_probes(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.deck_area.set_panel_view(0, DeckId.FILES, DeckView.PAGE_CARDS)
        detail.update_display(_text_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _files_panel(app)
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert panel.view_policy(DeckId.FILES) is DeckView.PAGE_CARDS
        assert panel._files_pending_probe is None
        assert panel._files_probe_pages == ()
        assert panel._render_mode[DeckId.FILES] is RenderMode.PAGED
        assert panel.effective_layout(DeckId.FILES) is DeckView.PAGE_CARDS
        assert panel._files_spread_pending is False
        assert panel._files_spread_blocked is False


async def test_spreading_status_while_complete_probe_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.widgets.file_panel import _spread_probe as probe_module

    gate = threading.Event()
    real_probe = probe_module.probe_files_spread

    def _gated(*args: Any, **kwargs: Any) -> Any:
        gate.wait(timeout=30)
        return real_probe(*args, **kwargs)

    monkeypatch.setattr(probe_module, "probe_files_spread", _gated)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.deck_area.set_panel_view(0, DeckId.FILES, DeckView.SPREAD)
        detail.update_display(_text_agent(tmp_path, lines=20))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _files_panel(app)

        await wait_for(pilot, lambda: bool(panel._files_spread_pending))

        resolved = panel.resolved_view()
        assert resolved.status is ViewStatus.PENDING
        assert resolved.shown is DeckView.PAGE_CARDS
        assert panel.effective_layout(DeckId.FILES) is DeckView.PAGE_CARDS

        gate.set()
        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))
        assert panel.resolved_view().status is ViewStatus.OK


async def test_media_blocked_keeps_preference_and_toasts_once(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(_media_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _files_panel(app)
        await wait_for(pilot, lambda: panel._files_probe_slots != ())
        await pilot.pause()

        # Subject changes under AUTO never toast.
        panel.notify = MagicMock()  # type: ignore[method-assign]
        assert panel.notify.call_count == 0

        detail.set_focused_deck_view(DeckView.SPREAD)
        await wait_for(pilot, lambda: bool(panel._files_spread_blocked))

        assert panel.view_policy(DeckId.FILES) is DeckView.SPREAD
        assert panel._render_mode[DeckId.FILES] is RenderMode.PAGED
        resolved = panel.resolved_view()
        assert resolved.status is ViewStatus.BLOCKED
        assert resolved.shown is DeckView.PAGE_CARDS
        assert panel.notify.call_count == 1
        assert panel.notify.call_args[0][0] == _MEDIA_TOAST

        # The next compatible subject spreads with the kept preference.
        detail.update_display(_text_agent(tmp_path, lines=20))
        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))
        assert panel.view_policy(DeckId.FILES) is DeckView.SPREAD
        assert panel._files_spread_blocked is False
        assert panel.notify.call_count == 1


async def test_stale_results_dropped_and_reset_to_auto_redecides(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.deck_area.set_panel_view(0, DeckId.FILES, DeckView.SPREAD)
        detail.update_display(_text_agent(tmp_path))
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _files_panel(app)
        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))

        subject = panel._files_probe_subject
        stale = FilesSpreadProbe(
            pages=(),
            total_rows=None,
            has_solo=True,
            exceeded=False,
            bound=1.0,
        )
        panel._on_files_probe_result(stale, None, ("nope.md",), object())

        assert panel.is_spread(DeckId.FILES)
        assert panel._files_probe_subject == subject
        assert panel._files_spread_blocked is False

        # Reset to AUTO re-decides: this deck exceeds the auto budget.
        detail.set_focused_deck_view(DeckView.AUTO)
        await wait_for(
            pilot, lambda: panel._render_mode[DeckId.FILES] is RenderMode.PAGED
        )
        assert panel.view_policy(DeckId.FILES) is DeckView.AUTO
        assert panel._files_spread_pending is False
        assert panel._files_spread_blocked is False
