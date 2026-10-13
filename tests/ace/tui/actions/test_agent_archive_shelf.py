"""Inbox Archive shelf and bridge correctness."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui._app_watchers import AppWatchersMixin
from sase.ace.tui.actions.agents import _archive_view
from sase.ace.tui.actions.agents._archive_controller import (
    init_agents_archive_controller,
)
from sase.ace.tui.actions.agents._archive_shelf import (
    _compute_shelf_snapshot,
    activate_archive_shelf,
    archive_bridge_detail,
    route_archive_shelf_focus,
    request_archive_shelf_refresh,
)
from sase.ace.tui.models.agent_archive_controller import ArchiveShelfSnapshot
from sase.ace.tui.widgets.agent_archive_shelf import AgentArchiveShelf
from tests.ace.tui._agent_archive_column_helpers import ModelCorpus, light_row


class _ShelfApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentArchiveShelf(id="agent-archive-shelf")


def _owner_with_shelf(
    shelf: ArchiveShelfSnapshot,
    *,
    corpus: ModelCorpus | None = None,
) -> SimpleNamespace:
    owner = SimpleNamespace()
    state = init_agents_archive_controller(owner)
    state.shelf = shelf
    state.corpus = corpus
    return owner


def test_shelf_recount_strips_inbox_scope_before_archive_queries() -> None:
    corpus = ModelCorpus([light_row("failed", outcome="failed", status="FAILED")])

    snapshot = _compute_shelf_snapshot(
        corpus,
        None,
        "in:inbox outcome:failed",
    )

    assert snapshot.query == "outcome:failed"
    assert "in:inbox" not in corpus.queries
    assert "outcome:failed" in corpus.queries


def test_bridge_matches_scope_stripped_query_and_shows_time_outcome_and_name() -> None:
    row = light_row(
        "failed",
        hour=17,
        name="archive.failed-run",
        outcome="failed",
        status="FAILED",
    )
    corpus = ModelCorpus([row])
    owner = _owner_with_shelf(
        ArchiveShelfSnapshot(
            status="ready",
            query="outcome:failed",
            total=1,
            matching=1,
            rows=(row,),
        ),
        corpus=corpus,
    )

    detail = archive_bridge_detail(owner, "in:inbox outcome:failed")

    assert "1 matches this filter" in detail
    assert "17:00 · failed · archive.failed-run" in detail
    assert "⏎ search the Archive" in detail


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (
            ArchiveShelfSnapshot(status="loading", query="status:FAILED"),
            "Checking the Archive",
        ),
        (
            ArchiveShelfSnapshot(status="unanswerable", query="status:FAILED", total=3),
            "can't answer this filter",
        ),
        (
            ArchiveShelfSnapshot(
                status="ready", query="status:FAILED", total=3, matching=0
            ),
            "No Archive runs match this filter",
        ),
    ],
)
def test_bridge_states(snapshot: ArchiveShelfSnapshot, expected: str) -> None:
    owner = _owner_with_shelf(snapshot)

    assert expected in archive_bridge_detail(owner, "status:FAILED")


def test_enter_carries_scope_stripped_inbox_filter_into_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ShelfWidget:
        def remove_class(self, _name: str) -> None:
            return

    widget = _ShelfWidget()
    state = init_agents_archive_controller(SimpleNamespace())
    state.shelf = ArchiveShelfSnapshot(
        status="ready", query="outcome:failed", total=2, matching=1
    )
    owner = SimpleNamespace(
        _agents_archive_controller=state,
        _agent_search_query="in:inbox outcome:failed",
        query_one=lambda _selector: widget,
    )
    carried: list[str] = []
    monkeypatch.setattr(
        _archive_view,
        "open_agents_archive_view_with_query",
        lambda _owner, *, query: carried.append(query),
    )

    assert activate_archive_shelf(owner) is True
    assert carried == ["in:archive outcome:failed"]


def test_shelf_jk_focus_routes_to_and_from_the_bottom_panel() -> None:
    class _Widget:
        def __init__(self) -> None:
            self.styles = SimpleNamespace(display="block")
            self.classes: set[str] = set()
            self.focused = False

        def add_class(self, name: str) -> None:
            self.classes.add(name)

        def remove_class(self, name: str) -> None:
            self.classes.discard(name)

        def focus(self) -> None:
            self.focused = True

    shelf = _Widget()
    panel = _Widget()
    owner = SimpleNamespace(
        current_tab="agents",
        _panel_group=SimpleNamespace(panel_keys=("one", "two"), focused_idx=1),
        query_one=lambda selector: (
            shelf if selector == "#agent-archive-shelf" else panel
        ),
    )

    assert route_archive_shelf_focus(owner, forward=True) is True
    assert owner._agent_archive_shelf_focused is True
    assert shelf.focused is True

    assert route_archive_shelf_focus(owner, forward=False) is True
    assert owner._agent_archive_shelf_focused is False
    assert "-focused" not in shelf.classes
    assert panel.focused is True


def test_clicking_elsewhere_clears_shelf_focus() -> None:
    class _ShelfWidget:
        def __init__(self) -> None:
            self.classes = {"-focused"}

        def remove_class(self, name: str) -> None:
            self.classes.discard(name)

    widget = _ShelfWidget()
    owner = SimpleNamespace(
        _agent_archive_shelf_focused=True,
        query_one=lambda _selector: widget,
    )

    AppWatchersMixin.on_click(
        owner,
        SimpleNamespace(widget=SimpleNamespace(id="agent-list-panel")),
    )

    assert owner._agent_archive_shelf_focused is False
    assert "-focused" not in widget.classes


@pytest.mark.asyncio
async def test_same_shelf_key_still_updates_inbox_empty_lit_state() -> None:
    app = _ShelfApp()
    async with app.run_test():
        state = init_agents_archive_controller(app)
        corpus = ModelCorpus([])
        state.corpus = corpus
        state.status = "warm"
        state.shelf = ArchiveShelfSnapshot(status="ready", total=3)
        state.shelf_requested_key = ("status:FAILED", state.tokens, id(corpus))
        app._agent_search_query = "status:FAILED"  # type: ignore[attr-defined]
        app._agents = [object()]  # type: ignore[attr-defined]

        request_archive_shelf_refresh(app)
        shelf = app.query_one(AgentArchiveShelf)
        assert not shelf.has_class("-empty")

        app._agents = []  # type: ignore[attr-defined]
        request_archive_shelf_refresh(app)

        assert shelf.has_class("-empty")
        assert corpus.summary_calls == 0
