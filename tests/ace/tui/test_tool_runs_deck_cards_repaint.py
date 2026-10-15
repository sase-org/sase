"""Paint-path regressions for loaded Tool Runs detail (sase-1kx.5.3.3.3.1)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.tool_runs.deck import ToolRunsDetailLevel
from sase.ace.tui.tool_runs.detail import LoadedToolRunDetail
from sase.ace.tui.widgets.decks.tool_runs.document import build_tool_runs_document
from sase.ace.tui.widgets.decks.tool_runs.rows import tool_runs_render_digest
from sase.ace.tui.widgets.decks.tool_runs.view import ToolRunsDeckView
from sase.core.tool_run import (
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
)
from tests.ace.tui._tool_runs_deck_cards_shared import make_brief

__all__ = [
    "test_loaded_detail_repaints_placeholder_through_show_document",
    "test_render_digest_changes_with_detail_and_level",
    "test_stale_cache_complete_paints_unpainted_detail",
    "test_unchanged_complete_state_skips_repaint",
    "test_detail_level_change_repaints_without_summary_change",
]


def _stage(description: str) -> ToolRunDetailStage:
    return ToolRunDetailStage(
        description=description,
        started_ms=0,
        finished_ms=1000,
        elapsed_ms=1000,
        exit_code=1,
        counts=ToolRunDetailStageCounts(new=2),
    )


def _loaded(run_id: str) -> LoadedToolRunDetail:
    brief = make_brief(run_id, bucket="new_failures", new=3, known=1)
    detail = ToolRunDetail(
        store_exists=True,
        found=True,
        display_argv=("just", "check"),
        stages=(
            _stage("fmt (python)"),
            _stage("lint (symvision)"),
        ),
        brief=brief,
    )
    tail = SimpleNamespace(
        availability="available",
        source="run",
        lines=("check output line 1", "check output line 2"),
        total_bytes=40,
        truncated=False,
    )
    return LoadedToolRunDetail(run_id=run_id, detail=detail, tail=tail)


def _prepare_view(view: ToolRunsDeckView) -> list[str | None]:
    paints: list[str | None] = []
    view.prepare_section_document = lambda _identity: None  # type: ignore[method-assign]
    view._apply_section_content = (  # type: ignore[method-assign]
        lambda _content, digest, **_kwargs: paints.append(digest)
    )
    return paints


def test_render_digest_changes_with_detail_and_level() -> None:
    summary = "node:1::0"
    empty = tool_runs_render_digest(summary, details={})
    loaded = tool_runs_render_digest(summary, details={"a" * 32: _loaded("a" * 32)})
    leveled = tool_runs_render_digest(
        summary,
        details={"a" * 32: _loaded("a" * 32)},
        level=int(ToolRunsDetailLevel.FULL),
    )
    assert empty != loaded
    assert loaded != leveled
    again = tool_runs_render_digest(summary, details={"a" * 32: _loaded("a" * 32)})
    assert loaded == again


def test_loaded_detail_repaints_placeholder_through_show_document() -> None:
    """Cached summary without detail must yield to the loaded document.

    The production-path probe on be73b6021a painted once, left
    ``_document`` as the placeholder, kept the absence line, and never
    showed ``lint (symvision)``.
    """

    run_id = "6c3d5107" + "0" * 24
    brief = make_brief(run_id, bucket="new_failures", new=3, known=1)
    kw: dict[str, Any] = {
        "subject": ("agent", "tr-c-failed"),
        "now_s": 1785239400.0,
    }
    summary = "node:1::0"
    placeholder = build_tool_runs_document(
        (brief,),
        details={},
        digest=tool_runs_render_digest(summary, details={}),
        **kw,
    )
    loaded = _loaded(run_id)
    complete = build_tool_runs_document(
        (brief,),
        details={run_id: loaded},
        digest=tool_runs_render_digest(summary, details={run_id: loaded}),
        **kw,
    )
    view = ToolRunsDeckView()
    paints = _prepare_view(view)
    view.show_tool_runs_document(placeholder, "runs")
    view.show_tool_runs_document(complete, "runs")
    assert len(paints) == 2
    assert view._document is complete
    text = view.get_tool_runs_text() or ""
    assert "run detail unavailable" not in text
    assert "lint (symvision)" in text
    assert "check output line 1" in text


def _patch_fast_path(
    monkeypatch: Any,
    *,
    details_by_call: list[dict[str, Any]],
) -> None:
    from sase.ace.tui.widgets.decks.tool_runs import widget as _widget_module

    selector = SimpleNamespace(key="node-key")
    summary = SimpleNamespace()
    brief = make_brief("f" * 32)
    rows = (brief,)
    calls = {"n": 0}

    def _details(_rows: object, _token: object) -> dict[str, Any]:
        index = min(calls["n"], len(details_by_call) - 1)
        calls["n"] += 1
        return details_by_call[index]

    monkeypatch.setattr(_widget_module, "selector_for_agent", lambda _agent: selector)
    monkeypatch.setattr(
        _widget_module, "cached_node_summary_for_selector", lambda _selector: summary
    )
    monkeypatch.setattr(
        _widget_module,
        "tool_runs_rows_for_document",
        lambda _summary, _snapshot_runs: (rows, 1, False),
    )
    monkeypatch.setattr(
        _widget_module,
        "tool_runs_cache_signature",
        lambda _key, _total, _live, _trunc: "sig-1",
    )
    monkeypatch.setattr(_widget_module, "cached_block_details", _details)
    monkeypatch.setattr(_widget_module, "count_silent_rows", lambda _r, _n: 0)
    monkeypatch.setattr(_widget_module, "tool_runs_render_width", lambda _v: 100)
    monkeypatch.setattr(_widget_module, "tool_runs_hint_numbers", lambda _v: None)


def test_stale_cache_complete_paints_unpainted_detail() -> None:
    """A stale worker filling the LRU must not skip the loaded paint."""

    import pytest as _pytest

    run_id = "f" * 32
    loaded = _loaded(run_id)
    monkeypatch = _pytest.MonkeyPatch()
    view = ToolRunsDeckView()
    paints = _prepare_view(view)
    started: list[int] = []

    class _FakeWorker:
        is_running = True

        def cancel(self) -> None:
            self.is_running = False

    def _fake_run_worker(
        self: object, _fetch: object, *, thread: bool = True
    ) -> _FakeWorker:
        started.append(view._current_generation)
        worker = _FakeWorker()
        view._current_worker = worker  # type: ignore[assignment]
        return worker

    try:
        _patch_fast_path(monkeypatch, details_by_call=[{}, {run_id: loaded}])
        monkeypatch.setattr(ToolRunsDeckView, "run_worker", _fake_run_worker)
        monkeypatch.setattr(ToolRunsDeckView, "_show_loading", lambda self: None)
        agent = SimpleNamespace(identity=("agent", "a", ""))
        view.update_display(agent, generation=1)
        assert len(paints) == 1
        assert started == [1]
        placeholder_text = view.get_tool_runs_text() or ""
        assert "run detail unavailable" in placeholder_text
        view.update_display(agent, generation=1)
        assert len(paints) == 2
        text = view.get_tool_runs_text() or ""
        assert "run detail unavailable" not in text
        assert "lint (symvision)" in text
    finally:
        monkeypatch.undo()


def test_unchanged_complete_state_skips_repaint() -> None:
    import pytest as _pytest

    run_id = "f" * 32
    loaded = _loaded(run_id)
    monkeypatch = _pytest.MonkeyPatch()
    view = ToolRunsDeckView()
    paints = _prepare_view(view)
    started: list[int] = []

    def _fake_run_worker(
        self: object, _fetch: object, *, thread: bool = True
    ) -> object:
        started.append(1)
        return SimpleNamespace(is_running=True, cancel=lambda: None)

    try:
        _patch_fast_path(
            monkeypatch, details_by_call=[{run_id: loaded}, {run_id: loaded}]
        )
        monkeypatch.setattr(ToolRunsDeckView, "run_worker", _fake_run_worker)
        monkeypatch.setattr(ToolRunsDeckView, "_show_loading", lambda self: None)
        agent = SimpleNamespace(identity=("agent", "a", ""))
        view.update_display(agent, generation=1)
        assert len(paints) == 1
        assert started == []
        view.update_display(agent, generation=1)
        assert len(paints) == 1
        assert started == []
    finally:
        monkeypatch.undo()


def test_detail_level_change_repaints_without_summary_change() -> None:
    import pytest as _pytest

    run_id = "f" * 32
    loaded = _loaded(run_id)
    monkeypatch = _pytest.MonkeyPatch()
    view = ToolRunsDeckView()
    paints = _prepare_view(view)

    def _fake_run_worker(
        self: object, _fetch: object, *, thread: bool = True
    ) -> object:
        return SimpleNamespace(is_running=True, cancel=lambda: None)

    try:
        _patch_fast_path(
            monkeypatch, details_by_call=[{run_id: loaded}, {run_id: loaded}]
        )
        monkeypatch.setattr(ToolRunsDeckView, "run_worker", _fake_run_worker)
        monkeypatch.setattr(ToolRunsDeckView, "_show_loading", lambda self: None)
        agent = SimpleNamespace(identity=("agent", "a", ""))
        view.update_display(agent, generation=1)
        assert len(paints) == 1
        view._detail_level = ToolRunsDetailLevel.FULL
        view.update_display(agent, generation=1)
        assert len(paints) == 2
    finally:
        monkeypatch.undo()
