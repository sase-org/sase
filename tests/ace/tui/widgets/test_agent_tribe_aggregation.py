"""Disk/statistics enrichment coverage for tribe detail documents."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.agents._display_detail import DetailMixin
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    build_clan_disk_snapshot,
    cache_clan_disk_snapshot,
    get_cached_clan_section_snapshot,
    prepare_clan_section_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeEnrichmentResult,
    TribeSectionSnapshot,
    build_tribe_enrichment,
    cache_tribe_enrichment,
    get_cached_tribe_section_snapshot,
    get_cached_tribe_sources,
    _load_tribe_runtime_statistics,
    _TribeDiskSnapshot,
    prepare_tribe_section_snapshot,
    tribe_sections_to_refresh,
)
from sase.ace.tui.widgets.prompt_panel._messages import (
    TribeSectionSnapshotLoaded,
)

_NOW = datetime(2026, 7, 18, 16, 0, 0)


def _agent(name: str, suffix: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": _NOW,
        "stop_time": _NOW,
        "raw_suffix": suffix,
        "agent_name": name,
        "tribe": "epic",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _reply_agent(
    tmp_path: Path,
    name: str,
    suffix: str,
    body: str,
    **overrides: object,
) -> Agent:
    artifacts = tmp_path / suffix
    artifacts.mkdir()
    response = artifacts / "response.md"
    response.write_text(body, encoding="utf-8")
    return _agent(
        name,
        suffix,
        artifacts_dir=str(artifacts),
        response_path=str(response),
        **overrides,
    )


def test_mixed_unit_replies_are_attributed_and_member_cache_is_reused(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    family = _reply_agent(
        tmp_path,
        "build--plan",
        "family",
        "Family root reply",
        agent_family="build",
        agent_family_role="root",
        plan_chain_root=True,
    )
    child = _reply_agent(
        tmp_path,
        "build--code",
        "child",
        "Child reply",
        agent_family="build",
        agent_family_role="code",
        parent_timestamp=family.raw_suffix,
    )
    family.followup_agents = [child]
    standalone = _reply_agent(
        tmp_path,
        "standalone",
        "standalone",
        "Standalone reply",
    )
    agents = [family, child, standalone]
    summary = build_agent_tribe_summary_snapshot(
        "epic",
        agents,
        panel_collapsed=True,
        now=_NOW,
    )
    widget = SimpleNamespace()
    prepare_tribe_section_snapshot(widget, summary, agents)
    sources = get_cached_tribe_sources(widget, summary.container_identity)

    first = build_tribe_enrichment(
        widget,
        summary.container_identity,
        sources,
        sections={"replies"},
    )
    assert [
        (item.unit_label, item.entry.member_label, item.entry.preview)
        for item in cast(_TribeDiskSnapshot, first.disk).replies
    ] == [
        ("build", "build", "Family root reply"),
        ("build", "--code", "Child reply"),
        ("standalone", "standalone", "Standalone reply"),
    ]
    cached = cache_tribe_enrichment(widget, first)
    assert cached is not None
    assert (
        tribe_sections_to_refresh(
            widget,
            summary.container_identity,
            {"replies"},
        )
        == frozenset()
    )

    def unexpected_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("stable member mtimes should reuse cached content")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "_load_clan_disk_member_snapshot",
        unexpected_load,
    )
    second = build_tribe_enrichment(
        widget,
        summary.container_identity,
        sources,
        sections={"replies"},
    )
    assert len(cast(_TribeDiskSnapshot, second.disk).replies) == 3


def test_clan_unit_reuses_fresh_clan_snapshot(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    member = _reply_agent(tmp_path, "research.one", "clan", "Clan reply")
    member.agent_clan = "research"
    member.agent_clan_generation = "20260718160000"
    container = project_clan_tree([member])[0]
    widget = SimpleNamespace()
    clan_snapshot = prepare_clan_section_snapshot(widget, container)
    clan_disk = build_clan_disk_snapshot(
        widget,
        container,
        clan_snapshot.in_memory,
        sections={"replies"},
    )
    assert cache_clan_disk_snapshot(widget, container, clan_disk) is not None

    agents = [container, member]
    summary = build_agent_tribe_summary_snapshot(
        "epic",
        agents,
        panel_collapsed=True,
        now=_NOW,
    )
    prepare_tribe_section_snapshot(widget, summary, agents)

    def unexpected_group_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("fresh clan disk snapshot should be reused as-is")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation."
        "build_agent_group_disk_snapshot",
        unexpected_group_load,
    )
    result = build_tribe_enrichment(
        widget,
        summary.container_identity,
        get_cached_tribe_sources(widget, summary.container_identity),
        sections={"replies"},
    )
    assert [
        item.entry.preview for item in cast(_TribeDiskSnapshot, result.disk).replies
    ] == ["Clan reply"]
    assert get_cached_clan_section_snapshot(widget, container) is not None


def test_runtime_statistics_query_filters_tribe_and_computes_share(
    monkeypatch: Any,
) -> None:
    calls: list[dict[str, object]] = []

    def query(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "runtime_groups": [
                {
                    "group": "other",
                    "runs": 1,
                    "total_seconds": 100.0,
                    "mean_seconds": 100.0,
                    "p50_seconds": 100.0,
                    "p95_seconds": 100.0,
                    "max_seconds": 100.0,
                },
                {
                    "group": "epic",
                    "runs": 3,
                    "total_seconds": 300.0,
                    "mean_seconds": 100.0,
                    "p50_seconds": 90.0,
                    "p95_seconds": 140.0,
                    "max_seconds": 150.0,
                },
            ]
        }

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation.query_run_stats",
        query,
    )
    stats = _load_tribe_runtime_statistics("epic", end_ts=1234)

    assert stats is not None
    assert (stats.runs, stats.total_seconds, stats.p50_seconds, stats.share) == (
        3,
        300.0,
        90.0,
        0.75,
    )
    assert calls == [
        {
            "start_ts": 0,
            "end_ts": 1234,
            "runtime_group_by": "tribe",
            "top_n": 10_000,
        }
    ]


def test_runtime_statistics_missing_archive_is_the_no_runs_state(
    monkeypatch: Any,
) -> None:
    def missing_archive(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("unable to open database file")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation.query_run_stats",
        missing_archive,
    )

    assert _load_tribe_runtime_statistics("epic", end_ts=1234) is None


class _FakeWorker:
    def __init__(self) -> None:
        self.is_running = True
        self.result: object | None = None
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class _TribePanel(AgentDisplayMixin):
    def __init__(self) -> None:
        self.messages: list[object] = []
        self.worker = _FakeWorker()
        self.worker_fn: Callable[[], object] | None = None
        self.worker_runs = 0

    def post_message(self, message: object) -> None:
        self.messages.append(message)

    def run_worker(self, fn: Callable[[], object], *, thread: bool) -> _FakeWorker:
        assert thread
        self.worker_runs += 1
        self.worker_fn = fn
        self.worker = _FakeWorker()
        return self.worker


def test_tribe_worker_coalesces_and_runs_latest_pending_panel(
    monkeypatch: Any,
) -> None:
    first_agent = _agent("first", "first")
    second_agent = _agent("second", "second", tribe="other")
    first_summary = build_agent_tribe_summary_snapshot(
        "epic", [first_agent], panel_collapsed=True, now=_NOW
    )
    second_summary = build_agent_tribe_summary_snapshot(
        "other", [second_agent], panel_collapsed=True, now=_NOW
    )
    panel = _TribePanel()
    prepare_tribe_section_snapshot(panel, first_summary, [first_agent])
    prepare_tribe_section_snapshot(panel, second_summary, [second_agent])

    def build(
        _widget: object,
        panel_identity: tuple[object, ...],
        sources: tuple[object, ...],
        **_kwargs: object,
    ) -> TribeEnrichmentResult:
        return TribeEnrichmentResult(
            panel_identity=cast(Any, panel_identity),
            source_signature=tuple(cast(Any, source).signature for source in sources),
            disk=_TribeDiskSnapshot(
                loaded_sections=frozenset({"replies"}),
                replies=(),
                slow_tool_calls=(),
            ),
            runtime_statistics_refreshed=False,
            runtime_statistics=None,
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async.build_tribe_enrichment",
        build,
    )
    panel.start_tribe_section_enrichment(
        first_summary.container_identity,
        sections={"replies"},
        slow_tool_threshold_ms=20_000,
    )
    first_worker = panel.worker
    first_fn = panel.worker_fn
    panel.start_tribe_section_enrichment(
        first_summary.container_identity,
        sections={"replies"},
        slow_tool_threshold_ms=20_000,
    )
    panel.start_tribe_section_enrichment(
        second_summary.container_identity,
        sections={"replies"},
        slow_tool_threshold_ms=20_000,
    )
    assert panel.worker_runs == 1
    assert first_fn is not None

    first_worker.result = first_fn()
    panel._apply_tribe_section_enrichment_result(
        cast(Worker[Any], first_worker),
        WorkerState.SUCCESS,
    )

    assert panel.worker_runs == 2
    assert isinstance(panel.messages[0], TribeSectionSnapshotLoaded)
    first_cached = get_cached_tribe_section_snapshot(
        panel, first_summary.container_identity
    )
    second_cached = get_cached_tribe_section_snapshot(
        panel, second_summary.container_identity
    )
    assert isinstance(first_cached, TribeSectionSnapshot)
    assert second_cached is not None
    assert "replies" in second_cached.loading_sections


def test_tribe_worker_latest_request_can_return_to_current_panel() -> None:
    first_agent = _agent("first", "first")
    second_agent = _agent("second", "second", tribe="other")
    first_summary = build_agent_tribe_summary_snapshot(
        "epic", [first_agent], panel_collapsed=True, now=_NOW
    )
    second_summary = build_agent_tribe_summary_snapshot(
        "other", [second_agent], panel_collapsed=True, now=_NOW
    )
    panel = _TribePanel()
    prepare_tribe_section_snapshot(panel, first_summary, [first_agent])
    prepare_tribe_section_snapshot(panel, second_summary, [second_agent])

    for summary in (first_summary, second_summary, first_summary):
        panel.start_tribe_section_enrichment(
            summary.container_identity,
            sections={"replies"},
            slow_tool_threshold_ms=20_000,
        )

    assert panel.worker_runs == 1
    assert panel._tribe_section_pending_request is None
    second_cached = get_cached_tribe_section_snapshot(
        panel, second_summary.container_identity
    )
    assert second_cached is not None
    assert second_cached.loading_sections == frozenset()

    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    panel._apply_tribe_section_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )
    assert panel.worker_runs == 1


class _Debouncer:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def schedule(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _DetailHarness(DetailMixin):
    def __init__(self, panel_identity: tuple[object, ...]) -> None:
        self.panel_identity = panel_identity
        self._agent_detail_debouncer = _Debouncer()  # type: ignore[assignment]

    def _resolve_focused_collapsed_panel(self) -> object:
        return SimpleNamespace(container_identity=self.panel_identity)

    def _fire_debounced_detail_update(self) -> None:
        pass


def test_tribe_completion_repaints_only_the_still_focused_panel() -> None:
    harness = _DetailHarness(("panel", "epic"))

    harness.on_tribe_section_snapshot_loaded(
        TribeSectionSnapshotLoaded(("panel", "other"))
    )
    harness.on_tribe_section_snapshot_loaded(
        TribeSectionSnapshotLoaded(("panel", "epic"))
    )

    debouncer = cast(_Debouncer, harness._agent_detail_debouncer)
    assert debouncer.callbacks == [harness._fire_debounced_detail_update]
