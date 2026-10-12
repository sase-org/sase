"""Availability, reveal, and fast-path deck-cards tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.tool_runs import summaries as _summaries_module
from sase.ace.tui.tool_runs.deck import probe_tool_runs_card
from sase.ace.tui.tool_runs.snapshot import _set_snapshot
from sase.ace.tui.tool_runs import snapshot as _snapshot_module
from sase.ace.tui.widgets.decks.availability import probe_tools_deck
from sase.ace.tui.widgets.decks.tool_runs.view import ToolRunsDeckView
from sase.core.tool_run import ToolRunNodeSummary
from tests.ace.tui._tool_runs_deck_cards_shared import make_brief

__all__ = [
    "setup_function",
    "teardown_function",
    "test_fast_path_still_loads_when_details_missing_across_generation_bump",
    "test_pending_selection_applies_after_document_loads",
    "test_pending_selection_dropped_on_node_change",
    "test_probe_opens_for_monitor_owned_runs",
    "test_probe_pinned_attempt_has_no_runs",
    "test_probe_reads_cached_history_without_io",
    "test_probe_remote_and_clan_have_no_runs",
    "test_probe_unknown_history_is_none_before_first_load",
    "test_single_run_document_counts_as_success",
]


def _node(
    *,
    agent_name: str | None = "0t9--code",
    monitor_id: str | None = None,
    proc_id: str | None = None,
    remote: bool = False,
    clan: bool = False,
    agent_entry: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_name=agent_name,
        monitor_id=monitor_id,
        proc_id=proc_id,
        is_monitor=monitor_id is not None,
        is_named_proc=proc_id is not None,
        is_agent_session_container_row=False,
        is_agent_entry=agent_entry,
        is_clan_container=clan,
        fleet_origin_alias="fleet-machine" if remote else None,
        followup_agents=(),
        runtime_children=(),
        start_time=None,
    )


def setup_function(_: object) -> None:
    _set_snapshot(None)
    _snapshot_module._TOOL_RUNS_DISABLED_REASON = None
    _snapshot_module._TOOL_RUNS_DISABLED_LOGGED = False
    with _summaries_module._summary_lock:
        _summaries_module._summary_lru.clear()


def teardown_function(_: object) -> None:
    _set_snapshot(None)
    with _summaries_module._summary_lock:
        _summaries_module._summary_lru.clear()


def _store(selector: Any, summary: ToolRunNodeSummary) -> None:
    _summaries_module._store_node_summary(selector, "test-token", summary)


# Availability: per-card merge, monitor/proc opening, first-load None.


def test_probe_pinned_attempt_has_no_runs() -> None:
    assert probe_tool_runs_card(_node(), attempt_number=3) == (False, 0)


def test_probe_remote_and_clan_have_no_runs() -> None:
    assert probe_tool_runs_card(_node(remote=True)) == (False, 0)
    assert probe_tool_runs_card(_node(clan=True)) == (False, 0)


def test_probe_unknown_history_is_none_before_first_load() -> None:
    assert probe_tool_runs_card(_node()) == (None, 0)


def test_probe_reads_cached_history_without_io() -> None:
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    agent = _node()
    selector = selector_for_agent(agent)
    assert selector is not None
    _store(
        selector,
        ToolRunNodeSummary(
            key=selector.key,
            total_runs=2,
            runs=(
                make_brief("a" * 32, created_ts=1000),
                make_brief("b" * 32, created_ts=2000),
            ),
        ),
    )
    assert probe_tool_runs_card(agent) == (True, 2)


def test_probe_opens_for_monitor_owned_runs() -> None:
    agent = _node(agent_name=None, monitor_id="mon-1", agent_entry=False)
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    selector = selector_for_agent(agent)
    assert selector is not None
    assert selector.owners == (("monitor", "mon-1"),)
    _store(
        selector,
        ToolRunNodeSummary(
            key=selector.key,
            total_runs=1,
            runs=(
                make_brief(
                    "c" * 32,
                    agent="starter-turn",
                    owner_kind="monitor",
                    owner_id="mon-1",
                ),
            ),
        ),
    )
    assert probe_tool_runs_card(agent) == (True, 1)
    availability = probe_tools_deck(agent, attempt_number=None)
    assert availability.has_content is True
    assert availability.runs_count == 1
    assert availability.calls_count == 0


def _deck_panel() -> object:
    from types import SimpleNamespace

    panel = SimpleNamespace()
    panel.selected: list[str] = []
    panel.cards_shown: list[str] = []
    panel.select_block = lambda block_id: panel.selected.append(block_id) or True  # type: ignore[attr-defined]
    panel._show_tools_card = lambda card_id: (
        panel.cards_shown.append(card_id) or card_id
    )  # type: ignore[attr-defined]
    panel._tool_runs_document = SimpleNamespace(cards=[SimpleNamespace(blocks=[1, 2])])
    panel._availability = {}
    return panel


def _deck_app(selected_identity: object) -> object:
    from types import SimpleNamespace

    app = SimpleNamespace()
    app._pending_tool_run_block = None
    selected = SimpleNamespace(identity=selected_identity)
    app._get_selected_agent = lambda: selected  # type: ignore[attr-defined]
    app._panels: list[object] = []
    app._test_tool_run_panels = app._panels
    app.action_show_tool_runs_card = lambda: None  # type: ignore[attr-defined]
    return app


def test_pending_selection_applies_after_document_loads() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select

    app = _deck_app(("agent", "a", ""))
    panel = _deck_panel()
    app._panels.append(panel)  # type: ignore[attr-defined]
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=2) is True
    assert panel.selected == ["a" * 32]  # type: ignore[attr-defined]
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]


def test_pending_selection_dropped_on_node_change() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select

    app = _deck_app(("agent", "b", ""))
    panel = _deck_panel()
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=2) is False
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]
    assert panel.selected == []  # type: ignore[attr-defined]


def test_single_run_document_counts_as_success() -> None:
    from sase.ace.tui.tool_runs.reveal import apply_pending_tool_run_select
    from types import SimpleNamespace

    app = _deck_app(("agent", "a", ""))
    panel = SimpleNamespace()
    panel.selected: list[str] = []
    panel.select_block = lambda block_id: False  # type: ignore[attr-defined]
    panel._show_tools_card = lambda card_id: card_id  # type: ignore[attr-defined]
    panel._tool_runs_document = SimpleNamespace(cards=[SimpleNamespace(blocks=[])])
    panel._availability = {}
    app._pending_tool_run_block = {"run_id": "a" * 32, "identity": ("agent", "a", "")}  # type: ignore[attr-defined]
    assert apply_pending_tool_run_select(app, panel, n_runs=1) is True
    assert app._pending_tool_run_block is None  # type: ignore[attr-defined]


def test_fast_path_still_loads_when_details_missing_across_generation_bump() -> None:
    """Cached summary with missing details must still start a load.

    Regression for the deck-races fast-path strand: the summary LRU hit
    painted ``run detail unavailable`` and returned without a worker, while
    a generation bump dropped the only in-flight load as stale.
    """

    from types import SimpleNamespace
    from sase.ace.tui.widgets.decks.tool_runs import widget as _widget_module

    run_id = "f" * 32
    brief = make_brief(run_id)
    selector = SimpleNamespace(key="node-key")
    agent = SimpleNamespace(identity=("agent", "a", ""))
    summary = SimpleNamespace()
    rows = (brief,)

    paints: list[tuple[object, object | None]] = []
    started: list[int] = []

    class _FakeWorker:
        is_running = True

        def cancel(self) -> None:
            self.is_running = False

    view = ToolRunsDeckView()
    view._painted_signature = None
    view._current_worker = None

    def _fake_paint(
        self: object, result: object, preferred: object | None, **kwargs: object
    ) -> None:
        paints.append((result, preferred))
        view._painted_signature = getattr(result, "signature", None)
        view._has_displayed_content = True

    def _fake_run_worker(
        self: object, _fetch: object, *, thread: bool = True
    ) -> _FakeWorker:
        started.append(view._current_generation)
        worker = _FakeWorker()
        view._current_worker = worker  # type: ignore[assignment]
        return worker

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            _widget_module, "selector_for_agent", lambda _agent: selector
        )
        monkeypatch.setattr(
            _widget_module,
            "cached_node_summary_for_selector",
            lambda _selector: summary,
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
        # Detail cache misses every block: the fast path can only paint the
        # honest-absence placeholder.
        monkeypatch.setattr(
            _widget_module, "cached_block_details", lambda _rows, _token: {}
        )
        monkeypatch.setattr(
            _widget_module,
            "build_tool_runs_document",
            lambda *a, **k: SimpleNamespace(
                card_ids=("runs",), cards=(SimpleNamespace(),)
            ),
        )
        monkeypatch.setattr(_widget_module, "count_silent_rows", lambda _r, _n: 0)
        monkeypatch.setattr(_widget_module, "tool_runs_render_width", lambda _v: 100)
        monkeypatch.setattr(_widget_module, "tool_runs_hint_numbers", lambda _v: None)
        monkeypatch.setattr(ToolRunsDeckView, "_paint_tool_runs_result", _fake_paint)
        monkeypatch.setattr(ToolRunsDeckView, "run_worker", _fake_run_worker)
        monkeypatch.setattr(ToolRunsDeckView, "_show_loading", lambda self: None)

        view.update_display(agent, generation=1)
        assert len(paints) == 1
        assert started == [1]

        # A generation bump with the same cached summary must not strand the
        # subject's only load: the placeholder repaints and a new worker
        # starts for the new generation.
        view.update_display(agent, generation=2)
        assert len(paints) == 2
        assert started == [1, 2]
    finally:
        monkeypatch.undo()

    # A complete fast path paints once and starts no worker.
    view2 = ToolRunsDeckView()
    view2._painted_signature = None
    view2._current_worker = None
    paints2: list[tuple[object, object | None]] = []
    started2: list[int] = []

    def _fake_paint2(
        self: object, result: object, preferred: object | None, **kwargs: object
    ) -> None:
        paints2.append((result, preferred))
        view2._painted_signature = getattr(result, "signature", None)
        view2._has_displayed_content = True

    def _fake_run_worker2(
        self: object, _fetch: object, *, thread: bool = True
    ) -> _FakeWorker:
        started2.append(view2._current_generation)
        worker = _FakeWorker()
        view2._current_worker = worker  # type: ignore[assignment]
        return worker

    monkeypatch2 = _pytest.MonkeyPatch()
    try:
        monkeypatch2.setattr(
            _widget_module, "selector_for_agent", lambda _agent: selector
        )
        monkeypatch2.setattr(
            _widget_module,
            "cached_node_summary_for_selector",
            lambda _selector: summary,
        )
        monkeypatch2.setattr(
            _widget_module,
            "tool_runs_rows_for_document",
            lambda _summary, _snapshot_runs: (rows, 1, False),
        )
        monkeypatch2.setattr(
            _widget_module,
            "tool_runs_cache_signature",
            lambda _key, _total, _live, _trunc: "sig-1",
        )
        monkeypatch2.setattr(
            _widget_module,
            "cached_block_details",
            lambda _rows, _token: {run_id: SimpleNamespace()},
        )
        monkeypatch2.setattr(
            _widget_module,
            "build_tool_runs_document",
            lambda *a, **k: SimpleNamespace(
                card_ids=("runs",), cards=(SimpleNamespace(),)
            ),
        )
        monkeypatch2.setattr(_widget_module, "count_silent_rows", lambda _r, _n: 0)
        monkeypatch2.setattr(_widget_module, "tool_runs_render_width", lambda _v: 100)
        monkeypatch2.setattr(_widget_module, "tool_runs_hint_numbers", lambda _v: None)
        monkeypatch2.setattr(ToolRunsDeckView, "_paint_tool_runs_result", _fake_paint2)
        monkeypatch2.setattr(ToolRunsDeckView, "run_worker", _fake_run_worker2)
        monkeypatch2.setattr(ToolRunsDeckView, "_show_loading", lambda self: None)

        view2.update_display(agent, generation=1)
        assert len(paints2) == 1
        assert started2 == []
    finally:
        monkeypatch2.undo()
