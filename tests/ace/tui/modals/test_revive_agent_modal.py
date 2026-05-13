"""Tests for the archive-backed revive modal."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.agent_query.archive_planner import (
    ArchiveQueryError,
    ArchiveQueryPage,
    ArchiveQueryResult,
)
from sase.ace.dismissed_bundle_index import rebuild_index
from sase.ace.tui.actions.agents._revive import _ScopedArchiveQueryProvider
from sase.ace.tui.modals.project_select_modal import SelectionItem
from sase.ace.tui.modals.revive_agent_modal import DismissedAgentSelectModal

from tests._agent_revive_helpers import make_agent


def _result(**overrides: object) -> ArchiveQueryResult:
    values: dict[str, object] = {
        "agent_id": "agent-id",
        "raw_suffix": "20260512120000",
        "bundle_path": "/tmp/bundle.json",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "revived_at": None,
        "project_name": "sase",
        "model": "gpt-5.5",
        "runtime": "codex",
        "llm_provider": "codex",
        "step_index": None,
        "step_name": None,
        "step_type": None,
        "retry_attempt": 0,
        "is_workflow_child": False,
    }
    values.update(overrides)
    return ArchiveQueryResult(**values)  # type: ignore[arg-type]


@dataclass
class _Provider:
    pages: dict[str, ArchiveQueryPage]
    hydrated: list[str]

    def search(
        self,
        query: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> ArchiveQueryPage:
        if query == "hidden:true":
            raise ArchiveQueryError("hidden: is only available for live agent queries")
        return self.pages[query]

    def hydrate(self, result: ArchiveQueryResult) -> list[object]:
        self.hydrated.append(result.agent_id)
        return [
            make_agent(
                cl_name=result.cl_name,
                raw_suffix=result.raw_suffix,
                agent_name=result.agent_name,
                status=result.status,
            )
        ]


def test_archive_query_error_preserves_previous_results() -> None:
    hit = _result(agent_id="hit", cl_name="failed_cl", status="FAILED")
    provider = _Provider(
        pages={"status:failed": ArchiveQueryPage(results=[hit], next_cursor=None)},
        hydrated=[],
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    assert modal.refresh_archive_query("status:failed") is True
    assert modal.refresh_archive_query("hidden:true") is False

    assert [entry.archive_result.cl_name for entry in modal._entries] == ["failed_cl"]
    assert "only available for live agent queries" in (modal._query_error or "")


def test_archive_entries_hydrate_only_on_demand() -> None:
    hit = _result(agent_id="hit", cl_name="lazy_cl")
    provider = _Provider(
        pages={"": ArchiveQueryPage(results=[hit], next_cursor=None)},
        hydrated=[],
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    modal.refresh_archive_query("")
    assert provider.hydrated == []

    agent = modal._hydrate_entry(modal._entries[0])

    assert agent is not None
    assert agent.cl_name == "lazy_cl"
    assert provider.hydrated == ["hit"]


def _write_bundle(root: Path, **overrides: object) -> None:
    raw_suffix = str(overrides.get("raw_suffix", "20260512120000"))
    bundle: dict[str, object] = {
        "raw_suffix": raw_suffix,
        "agent_type": "run",
        "cl_name": "default_cl",
        "agent_name": "default_agent",
        "status": "DONE",
        "start_time": "2026-05-12T12:00:00",
        "dismissed_at": "2026-05-12T12:30:00",
        "project_file": "/tmp/projects/sase/sase.sase",
        "model": "gpt-5.5",
        "llm_provider": "codex",
        "runtime": "codex",
    }
    bundle.update(overrides)
    shard = root / raw_suffix[:6]
    shard.mkdir(parents=True, exist_ok=True)
    (shard / f"{raw_suffix}.json").write_text(json.dumps(bundle), encoding="utf-8")


@dataclass
class _RecordingProvider:
    """Provider that records search calls and returns scripted pages."""

    pages: dict[str, ArchiveQueryPage] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    cursors: list[int | None] = field(default_factory=list)
    delay_s: float = 0.0
    started: threading.Event = field(default_factory=threading.Event)

    def search(
        self,
        query: str,
        *,
        limit: int,
        cursor: int | None = None,
    ) -> ArchiveQueryPage:
        self.calls.append(query)
        self.cursors.append(cursor)
        self.started.set()
        if self.delay_s:
            time.sleep(self.delay_s)
        return self.pages.get(query, ArchiveQueryPage(results=[], next_cursor=None))

    def hydrate(self, result: ArchiveQueryResult) -> list[object]:
        return []


class _ModalTestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def _wait_for(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def test_typing_burst_debounces_to_single_search() -> None:
    """Three keystrokes in quick succession should collapse to one search."""
    provider = _RecordingProvider(
        pages={
            "": ArchiveQueryPage(results=[], next_cursor=None),
            "f": ArchiveQueryPage(results=[], next_cursor=None),
            "fo": ArchiveQueryPage(results=[], next_cursor=None),
            "foo": ArchiveQueryPage(results=[], next_cursor=None),
        }
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _wait_for(lambda: "" in provider.calls)
        provider.calls.clear()

        await pilot.press("f")
        await pilot.press("o")
        await pilot.press("o")
        await pilot.pause(0.05)
        assert provider.calls == []

        await pilot.pause(0.2)
        await _wait_for(lambda: "foo" in provider.calls)

    assert provider.calls == ["foo"]


async def test_enter_flushes_pending_archive_query() -> None:
    """Pressing Enter must run the pending search synchronously and dismiss."""
    provider = _RecordingProvider(
        pages={
            "": ArchiveQueryPage(results=[], next_cursor=None),
            "x": ArchiveQueryPage(results=[], next_cursor=None),
        }
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _wait_for(lambda: "" in provider.calls)
        provider.calls.clear()

        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause()

    assert "x" in provider.calls


async def test_slow_provider_keeps_app_responsive() -> None:
    """While the worker thread runs a slow search, keypresses still process."""
    provider = _RecordingProvider(
        pages={
            "": ArchiveQueryPage(results=[], next_cursor=None),
            "s": ArchiveQueryPage(results=[], next_cursor=None),
        },
        delay_s=0.4,
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _wait_for(lambda: "" in provider.calls)
        provider.started.clear()
        provider.calls.clear()

        await pilot.press("s")
        await pilot.pause(0.2)
        await _wait_for(lambda: provider.started.is_set())

        loop = asyncio.get_running_loop()
        start = loop.time()
        await pilot.pause()
        elapsed = loop.time() - start

    assert elapsed < 0.3


async def test_ctrl_n_and_ctrl_p_navigate_when_archive_has_more_results() -> None:
    """Archive pagination cursor must not steal ctrl+n row navigation."""
    provider = _RecordingProvider(
        pages={"": ArchiveQueryPage(results=[], next_cursor=25)}
    )
    modal = DismissedAgentSelectModal(
        [
            make_agent(cl_name="alpha", raw_suffix="20260512120000"),
            make_agent(cl_name="beta", raw_suffix="20260512120100"),
        ],
        archive_query_provider=provider,
    )

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _wait_for(lambda: modal._archive_cursor == 25)
        provider.calls.clear()
        provider.cursors.clear()

        option_list = modal.query_one("#dismissed-agent-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("ctrl+n")
        await pilot.pause(0.2)

        assert option_list.highlighted == 1
        assert provider.calls == []

        await pilot.press("ctrl+p")
        await pilot.pause()

        assert option_list.highlighted == 0
        assert provider.calls == []


async def test_pagedown_loads_more_archive_results_with_current_cursor() -> None:
    provider = _RecordingProvider(
        pages={
            "": ArchiveQueryPage(
                results=[_result(agent_id="first", cl_name="first")],
                next_cursor=25,
            )
        }
    )
    modal = DismissedAgentSelectModal([], archive_query_provider=provider)

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _wait_for(lambda: modal._archive_cursor == 25)
        provider.calls.clear()
        provider.cursors.clear()

        await pilot.press("pagedown")
        await _wait_for(lambda: provider.calls == [""])

    assert provider.cursors == [25]


def test_scoped_archive_provider_filters_structured_query_and_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_bundle(
        tmp_path,
        raw_suffix="20260512120000",
        cl_name="hit",
        status="FAILED",
        project_file="/tmp/projects/sase/sase.sase",
    )
    _write_bundle(
        tmp_path,
        raw_suffix="20260512130000",
        cl_name="wrong_project",
        status="FAILED",
        project_file="/tmp/projects/other/other.sase",
    )
    rebuild_index(tmp_path)
    monkeypatch.setattr("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", tmp_path)
    selection = SelectionItem("[P] sase", "project", "sase", None)
    provider = _ScopedArchiveQueryProvider(selection)

    page = provider.search("status:failed", limit=10)

    assert [row.cl_name for row in page.results] == ["hit"]
