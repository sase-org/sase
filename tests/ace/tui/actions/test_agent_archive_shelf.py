"""Inbox Archive shelf and bridge correctness."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult

from sase.ace.testing.wait import wait_for
from sase.ace.tui._app_watchers import AppWatchersMixin
from sase.ace.tui.actions.agents import _archive_view
from sase.ace.tui.actions.agents._archive_controller import (
    init_agents_archive_controller,
)
from sase.ace.tui.actions.agents._archive_shelf import (
    _compute_shelf_snapshot,
    activate_archive_shelf,
    archive_bridge_detail,
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
            ArchiveShelfSnapshot(status="cold", query="status:FAILED"),
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


@pytest.mark.parametrize(
    ("committed", "carried_query"),
    [
        # Mid-recount the shelf still holds the unfiltered count; the profile
        # parse alone decides, with no corpus call.
        ("in:inbox outcome:failed", "in:archive outcome:failed"),
        # unread: is Inbox-only, so ⏎ opens the plain Archive instead.
        ("unread:yes", None),
    ],
)
def test_enter_during_a_recount_carries_only_an_answerable_filter(
    monkeypatch: pytest.MonkeyPatch, committed: str, carried_query: str | None
) -> None:
    from sase.core.agent_archive_facade import agents_archive_profile

    owner = SimpleNamespace(
        _agent_search_query=committed,
        query_one=lambda _selector: SimpleNamespace(remove_class=lambda _name: None),
    )
    state = init_agents_archive_controller(owner)
    corpus = ModelCorpus([])
    state.corpus = corpus
    state.profile = agents_archive_profile()
    state.shelf = ArchiveShelfSnapshot(status="ready", total=4, today=1, matching=4)
    opened: list[str | None] = []
    monkeypatch.setattr(
        _archive_view,
        "open_agents_archive_view_with_query",
        lambda _owner, *, query: opened.append(query),
    )
    monkeypatch.setattr(
        _archive_view, "open_agents_archive_view", lambda _owner: opened.append(None)
    )

    assert activate_archive_shelf(owner) is True
    assert opened == [carried_query]
    assert corpus.queries == []


def test_enter_opens_the_plain_archive_for_an_unanswerable_landed_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(
        _agent_search_query="status:FAILED",
        query_one=lambda _selector: SimpleNamespace(remove_class=lambda _name: None),
    )
    state = init_agents_archive_controller(owner)
    state.shelf = ArchiveShelfSnapshot(
        status="unanswerable", query="status:FAILED", total=4
    )
    opened: list[str | None] = []
    monkeypatch.setattr(
        _archive_view,
        "open_agents_archive_view_with_query",
        lambda _owner, *, query: opened.append(query),
    )
    monkeypatch.setattr(
        _archive_view, "open_agents_archive_view", lambda _owner: opened.append(None)
    )

    assert activate_archive_shelf(owner) is True
    assert opened == [None]


@pytest.mark.asyncio
async def test_shelf_keeps_its_last_line_until_the_recount_lands() -> None:
    app = _ShelfApp()
    async with app.run_test() as pilot:
        state = init_agents_archive_controller(app)
        corpus = ModelCorpus([light_row("failed", outcome="failed", status="FAILED")])
        state.corpus = corpus
        state.status = "warm"
        state.shelf = ArchiveShelfSnapshot(status="ready", total=12, today=3)
        app._agents = [object()]  # type: ignore[attr-defined]
        app._agent_search_query = "status:FAILED"  # type: ignore[attr-defined]
        shelf = app.query_one(AgentArchiveShelf)

        request_archive_shelf_refresh(app)

        # The recount is still in flight: the last line stays, unchanged.
        assert shelf.display is True
        assert shelf.render().plain == "◷ Archive · 12 runs · 3 today"
        await wait_for(
            pilot,
            lambda: (
                shelf.render().plain == "◷ Archive · 1 matches this filter · ⏎ search"
            ),
        )


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


class _CountingCorpus(ModelCorpus):
    """Model corpus that records every ``count`` query the shelf runs."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(rows)
        self.counted: list[str] = []

    def count(self, query: str, profile: Any = None) -> int:
        self.counted.append(query)
        return super().count(query, profile)


async def test_typing_in_the_filter_bar_never_counts_until_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.testing import AcePage
    from sase.ace.tui.models.agent import Agent, AgentType
    from tests.ace.tui.visual._ace_png_snapshot_startup import (
        patch_startup_loaders,
        wait_for_startup,
    )

    agents = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            agent_name=name.replace("-", "."),
            project_file="/tmp/project/project.sase",
            status=status,
            start_time=datetime(2026, 9, 10, 12, 0, 0),
        )
        for name, status in (("running-one", "RUNNING"), ("failed-one", "FAILED"))
    ]
    patch_startup_loaders(monkeypatch, agents=agents)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        state = init_agents_archive_controller(page.app)
        corpus = _CountingCorpus([light_row("old", outcome="failed", status="FAILED")])
        state.corpus = corpus
        state.status = "warm"
        state.shelf = ArchiveShelfSnapshot(status="ready", total=1, today=1)
        state.shelf_requested_key = ("", state.tokens, id(corpus))

        await page.press("f")
        await page.pause()
        for char in "status:FAILED":
            await page.press(char)
            await page.pause()
        assert page.app._agents_live_preview_query == "status:FAILED"
        assert corpus.counted == []

        await page.press("enter")
        await page.wait_for(
            lambda _state: "status:FAILED" in corpus.counted, timeout=10.0
        )
        # One recount on commit: the total, then the committed filter.
        assert corpus.counted == ["", "status:FAILED"]
