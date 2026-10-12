"""End-to-end coverage for the auto-hiding Agents-tab FilterBar (sase-zf.4).

Exercises the full editing session through :class:`AcePage`: open via ``f``,
per-keystroke preview, ``Enter`` commit, ``Escape`` restore, an invalid
query's inline error, and saved-query slots. The legacy Off-flag modal path
is covered separately in ``test_agents_tab_query_filter.py``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.saved_queries import load_saved_queries
from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.models import agent_query_persistence as query_store
from sase.ace.tui.widgets.agents_filter_bar import AgentsFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui.visual._ace_png_snapshot_startup import (
    patch_startup_loaders,
    wait_for_startup,
)

_NOW = datetime(2026, 9, 10, 12, 0, 0)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "filter-fixture",
        "project_file": "/tmp/project/project.sase",
        "status": "RUNNING",
        "start_time": _NOW,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _fixture_agents() -> list[Agent]:
    return [
        _make_agent(cl_name="running-one", agent_name="running.one", status="RUNNING"),
        _make_agent(cl_name="running-two", agent_name="running.two", status="RUNNING"),
        _make_agent(cl_name="failed-one", agent_name="failed.one", status="FAILED"),
    ]


async def _type(page: AcePage, text: str) -> None:
    for char in text:
        await page.press(char)
        await page.pause()


async def _clear_and_type(page: AcePage, bar: AgentsFilterBar, text: str) -> None:
    """Clear whatever prefill ``open()`` loaded, then type *text*."""
    editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
    for _ in range(len(editor.text)):
        await page.press("backspace")
    await page.pause()
    await _type(page, text)


async def _wait_for_query_save(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: (
            page.app._agents_query_save_pending is None
            and page.app._agents_query_dirty_snapshot is None
            and (
                page.app._agents_query_save_task is None
                or page.app._agents_query_save_task.done()
            )
        )
    )


def _patch_recording_agent_loader(
    monkeypatch: pytest.MonkeyPatch,
    agents: list[Agent],
) -> list[str | None]:
    load_state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )
    provider_queries: list[str | None] = []

    def fake_load_agents(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        provider_queries.append(kwargs.get("search_query"))
        return SimpleNamespace(
            all_agents=list(agents),
            dismissed_from_loader=[],
            load_state=load_state,
        )

    monkeypatch.setattr(_loading, "load_agents_from_disk_with_state", fake_load_agents)
    return provider_queries


async def test_f_opens_the_bar_and_typing_previews_then_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is False

        await page.press("f")
        await page.pause()
        assert bar.display is True
        assert page.app._agents_filter_session_open is True

        await _type(page, "status:FAILED")
        await page.pause()
        # Live preview: the committed query and facade stay untouched while
        # editing, but the live-typed text is echoed into session state.
        assert page.app._agents_live_preview_query == "status:FAILED"
        assert page.app._agent_search_query == ""

        await page.press("enter")
        await page.pause()

        assert page.app._agents_filter_session_open is False
        assert bar.display is False
        assert page.app._agent_search_query == "status:FAILED"
        assert [a.cl_name for a in page.app._agents] == ["failed-one"]


async def test_filter_commit_persists_and_restores_in_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _fixture_agents()
    patch_startup_loaders(monkeypatch, agents=agents)
    provider_queries = _patch_recording_agent_loader(monkeypatch, agents)

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await page.press("f")
        await page.pause()
        await _type(page, "status:FAILED")
        await page.press("enter")
        await _wait_for_query_save(page)

    assert query_store.load_agent_query_snapshot(
        active_dialect=query_store.DIALECT_UNIFIED
    ).snapshot == query_store.make_agent_query_snapshot(
        "status:FAILED",
        dialect=query_store.DIALECT_UNIFIED,
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        assert page.app._agent_search_query == "status:FAILED"
        assert [a.cl_name for a in page.app._agents] == ["failed-one"]

    assert "status:FAILED" in provider_queries


async def test_slash_opens_the_bar_and_commits_like_f(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is False

        await page.press("slash")
        await page.pause()
        assert bar.display is True
        assert page.app._agents_filter_session_open is True

        await _type(page, "status:FAILED")
        await page.pause()
        assert page.app._agents_live_preview_query == "status:FAILED"
        assert page.app._agent_search_query == ""

        await page.press("enter")
        await page.pause()

        assert page.app._agents_filter_session_open is False
        assert bar.display is False
        assert page.app._agent_search_query == "status:FAILED"
        assert [a.cl_name for a in page.app._agents] == ["failed-one"]


async def test_explicit_empty_filter_commit_restores_unfiltered_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _fixture_agents()
    patch_startup_loaders(monkeypatch, agents=agents)
    query_store.save_agent_query_snapshot(
        query_store.make_agent_query_snapshot(
            "status:FAILED",
            dialect=query_store.DIALECT_UNIFIED,
        )
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        bar = page.app.query_one(AgentsFilterBar)
        await page.press("f")
        await page.pause()
        await _clear_and_type(page, bar, "   ")
        await page.press("enter")
        await _wait_for_query_save(page)

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        assert page.app._agent_search_query == ""
        assert [a.cl_name for a in page.app._agents] == [
            "running-one",
            "running-two",
            "failed-one",
        ]


async def test_escape_restores_the_prior_committed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        page.app._agent_search_query = "status:RUNNING"
        page.app._refilter_agents()
        await page.pause()
        assert len(page.app._agents) == 2

        await page.press("f")
        await page.pause()
        await _type(page, " AND cl:one")
        await page.pause()

        await page.press("escape")
        await page.pause()

        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is False
        assert page.app._agents_filter_session_open is False
        assert page.app._agent_search_query == "status:RUNNING"
        assert len(page.app._agents) == 2


async def test_invalid_query_shows_inline_error_and_keeps_last_good_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        await page.press("f")
        await page.pause()
        # "status:RUNNING" is a valid preview (2 matches); a single stray
        # ")" then fails to parse. The error must surface without
        # clobbering that last good (2-row) preview. (A multi-character
        # invalid suffix like the retired "age>2h" spelling would pass
        # through its own valid bare-word states while typing -- e.g.
        # "status:RUNNING AND kind" parses as a bare "kind" search term --
        # so this test picks a one-keystroke valid -> error transition to
        # isolate the "never clobbers" behavior precisely.)
        await _type(page, "status:RUNNING")
        await page.pause()
        assert page.app._agents_filter_query_error is None
        assert len(page.app._agents) == 2

        await _type(page, ")")
        await page.pause()

        assert page.app._agents_filter_query_error is not None
        # The invalid suffix never touched the last good preview.
        assert len(page.app._agents) == 2
        assert (
            query_store.load_agent_query_snapshot(
                active_dialect=query_store.DIALECT_UNIFIED
            ).snapshot
            is None
        )

        bar = page.app.query_one(AgentsFilterBar)
        status = bar.query_one(f"#{bar.STATUS_ID}")
        assert status.has_class("error")


async def test_hash_slot_saves_a_query_under_the_agents_live_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        await page.press("f")
        await page.pause()
        await _type(page, "#1 status:FAILED")
        await page.press("enter")
        await page.pause()

        saved = load_saved_queries("agents-live")
        assert "1" in saved
        assert saved["1"].canonical == "status:FAILED"
        # Saving does not commit the query.
        assert page.app._agent_search_query == ""
        assert (
            query_store.load_agent_query_snapshot(
                active_dialect=query_store.DIALECT_UNIFIED
            ).snapshot
            is None
        )


async def test_circumflex_history_replaces_the_live_edit_while_the_bar_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        # Commit one query, then another, to build history.
        bar = page.app.query_one(AgentsFilterBar)
        await page.press("f")
        await page.pause()
        await _type(page, "status:RUNNING")
        await page.press("enter")
        await page.pause()

        await page.press("f")
        await page.pause()
        await _clear_and_type(page, bar, "status:FAILED")
        await page.press("enter")
        await page.pause()
        assert page.app._agent_search_query == "status:FAILED"

        await page.press("f")
        await page.pause()
        await page.press("circumflex_accent")
        await page.pause()

        bar = page.app.query_one(AgentsFilterBar)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.text == "status:RUNNING"
        # History replaces the in-progress edit only; nothing commits yet.
        assert page.app._agent_search_query == "status:FAILED"


def test_validator_appends_legacy_token_hint_without_typing_races() -> None:
    """Unit-level coverage for the retired ``age>``/``type:`` hint text.

    Isolated from the TUI so it doesn't need a real keystroke-by-keystroke
    typing sequence, whose intermediate prefixes can themselves parse as
    valid bare-word searches (see the invalid-query test above).
    """
    from sase.ace.tui.actions.agents._filter_bar_session import (
        AgentsFilterBarSessionMixin,
    )

    mixin = AgentsFilterBarSessionMixin()
    assert mixin._validate_agents_live_query("") is None
    error = mixin._validate_agents_live_query("age>2h")
    assert error is not None
    assert "until:2h" in error
    assert mixin._validate_agents_live_query("in:archive") is None
    assert mixin._validate_agents_live_query("in:archive restorable:true") is None
    hint = mixin._validate_agents_live_query("restorable:true")
    assert hint is not None
    assert "Archive field" in hint
    mirror = mixin._validate_agents_live_query("in:archive unread:true")
    assert mirror is not None
    assert "Inbox field" in mirror


def test_agents_query_profile_follows_the_host_scope() -> None:
    from sase.ace.tui.models.agent_live_query_engine import (
        agents_query_profile_for_source,
    )

    assert agents_query_profile_for_source("status:FAILED").pane_id == "agents-live"
    assert (
        agents_query_profile_for_source("in:inbox status:FAILED").pane_id
        == "agents-live"
    )
    assert agents_query_profile_for_source("in:archive").pane_id == "agents-archive"
    assert (
        agents_query_profile_for_source("in:archive outcome:failed").pane_id
        == "agents-archive"
    )


def test_archive_filter_commit_parks_inbox_without_persisting_archive_query() -> None:
    from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
    from sase.ace.tui.actions.agents._filter_bar_session import (
        AgentsFilterBarSessionMixin,
    )
    from sase.feature_flags import override_flags

    class Harness(AgentsFilterBarSessionMixin):
        def __init__(self) -> None:
            self.current_tab = "agents"
            self._agent_search_query = "model:opus"
            self.current_idx = 0
            self._agents = []
            self.transitions: list[tuple[str, str, str, str | None, str]] = []
            self.explicit_commits: list[str] = []
            init_agents_archive_view_state(self)

        def _get_selected_agent(self) -> None:
            return None

        def _record_artifacts_query_transition(self, pane: str, **kwargs: Any) -> None:
            self.transitions.append(
                (
                    pane,
                    kwargs["old_source"],
                    kwargs["old_canonical"],
                    kwargs["old_profile_digest"],
                    kwargs["new_canonical"],
                )
            )

        def _schedule_agents_async_refresh(self, **_kwargs: Any) -> None:
            return

        def _record_explicit_agents_query_commit(self, source: str) -> None:
            self.explicit_commits.append(source)

        def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
            raise LookupError("no mounted widgets in this harness")

    app = Harness()
    with override_flags(agents_archive_view=True):
        app._commit_agents_filter_query("in:archive outcome:failed")

    assert app._agents_archive_view.active_view == "archive"
    assert (
        app._agents_archive_view.archive.committed_query == "in:archive outcome:failed"
    )
    assert app._agents_archive_view.parked_inbox is not None
    assert app._agents_archive_view.parked_inbox.committed_query == "model:opus"
    assert app.explicit_commits == []
    assert app.transitions[0][0] == "agents-live"
    assert app.transitions[0][3] is not None


def test_archive_history_and_saved_slot_keep_the_archive_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace import saved_queries
    from sase.ace.tui.actions.agents._filter_bar_session import (
        AgentsFilterBarSessionMixin,
    )
    from sase.ace.tui.models.agent_live_query_engine import (
        agents_query_profile_for_source,
    )

    class Harness(AgentsFilterBarSessionMixin):
        _agents_filter_session_open = True
        _agents_live_preview_query = "in:archive outcome:failed"
        _agent_search_query = ""

        def notify(self, *_args: Any, **_kwargs: Any) -> None:
            return

    app = Harness()
    record = app.query_history_record()
    assert (
        record.profile_digest == agents_query_profile_for_source(record.source).digest
    )

    saved: list[tuple[str, str, str, str, str | None]] = []
    monkeypatch.setattr(saved_queries, "find_slot_for_query", lambda *_: None)
    monkeypatch.setattr(saved_queries, "get_next_available_slot", lambda _slots: "1")
    monkeypatch.setattr(saved_queries, "load_saved_queries", lambda _pane: {})

    def save(
        pane_id: str,
        slot: str,
        source: str,
        canonical: str,
        *,
        profile_digest: str | None = None,
    ) -> bool:
        saved.append((pane_id, slot, source, canonical, profile_digest))
        return True

    monkeypatch.setattr(saved_queries, "save_query", save)
    app._save_agents_filter_query_slot("#in:archive outcome:failed")

    assert saved == [
        (
            "agents-live",
            "1",
            "in:archive outcome:failed",
            "in:archive outcome:failed",
            agents_query_profile_for_source(record.source).digest,
        )
    ]


def test_saved_slot_commit_does_not_copy_stale_preview_facade() -> None:
    from sase.ace.tui.actions.agents._filter_bar_session import (
        AgentsFilterBarSessionMixin,
    )

    class Harness(AgentsFilterBarSessionMixin):
        def __init__(self) -> None:
            self.current_tab = "agents"
            self._agent_search_query = "model:opus"
            self._agents_filter_session_open = False
            self._agents_live_preview_query = "stale preview"
            self._agents_live_preview_facade = "preview-facade"
            self._agents_live_query_facade = "committed-facade"
            self._agents_archive_view = None
            self.refresh_calls = 0

        def _agents_history_canonical(self, source: str) -> str:
            return source

        def _agents_profile_digest_for_source(self, source: str) -> str | None:
            return None

        def _record_explicit_agents_query_commit(self, source: str) -> None:
            self._agent_search_query = source

        def _refilter_agents(self, **_kwargs: Any) -> None:
            return

        def _schedule_agents_async_refresh(self, **_kwargs: Any) -> None:
            self.refresh_calls += 1

        def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
            raise LookupError("no mounted widgets in this harness")

    app = Harness()
    app._commit_agents_filter_query("status:FAILED")

    assert app._agents_live_query_facade == "committed-facade"
    assert app._agent_search_query == "status:FAILED"
    assert app.refresh_calls == 1


def test_open_session_commit_copies_matching_preview_facade() -> None:
    from sase.ace.tui.actions.agents._filter_bar_session import (
        AgentsFilterBarSessionMixin,
    )

    class Harness(AgentsFilterBarSessionMixin):
        def __init__(self) -> None:
            self.current_tab = "agents"
            self._agent_search_query = "model:opus"
            self._agents_filter_session_open = True
            self._agents_live_preview_query = "status:FAILED"
            self._agents_live_preview_facade = "preview-facade"
            self._agents_live_query_facade = "committed-facade"
            self._agents_archive_view = None

        def _agents_history_canonical(self, source: str) -> str:
            return source

        def _agents_profile_digest_for_source(self, source: str) -> str | None:
            return None

        def _record_explicit_agents_query_commit(self, source: str) -> None:
            self._agent_search_query = source

        def _refilter_agents(self, **_kwargs: Any) -> None:
            return

        def _schedule_agents_async_refresh(self, **_kwargs: Any) -> None:
            return

        def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
            raise LookupError("no mounted widgets in this harness")

    app = Harness()
    app._commit_agents_filter_query("status:FAILED")

    assert app._agents_live_query_facade == "preview-facade"


async def test_f_opens_the_filter_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_fixture_agents())

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await page.press("f")
        await page.pause()
        bar = page.app.query_one(AgentsFilterBar)
        assert bar.display is True
        assert page.app._agents_filter_session_open is True
