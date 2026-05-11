"""Phase 4: AXE dashboard renders lumberjack overview and chop detail."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.actions.axe_display._data import (
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus


def _entry(
    run_id: str,
    *,
    status: str = "success",
    duration_ms: int = 250,
    output_log: str = "run.log",
) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-05-11T12:34:56",
        finished_at="2026-05-11T12:34:57",
        duration_ms=duration_ms,
        status=status,  # type: ignore[arg-type]
        exit_code=0 if status == "success" else 1,
        output_log=output_log,
    )


def _snapshot_with_runs(*runs: ChopRunSnapshot) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="fast description",
        runs=list(runs),
    )


def _reset_ansi_cache() -> None:
    axe_dashboard._ansi_parse_cache.clear()


def test_chop_run_ansi_cache_keyed_by_run_id() -> None:
    """Two different runs of the same chop don't collide in the ANSI cache."""
    _reset_ansi_cache()

    payload = "shared\n"

    call_count = 0
    real_from_ansi = Text.from_ansi

    def _counting(text: str) -> Text:
        nonlocal call_count
        call_count += 1
        return real_from_ansi(text)

    with patch.object(Text, "from_ansi", staticmethod(_counting)):
        axe_dashboard._render_ansi_cached("chop:hooks:fast:r1", payload)
        axe_dashboard._render_ansi_cached("chop:hooks:fast:r2", payload)
        axe_dashboard._render_ansi_cached("chop:hooks:fast:r1", payload)  # cached
        axe_dashboard._render_ansi_cached("chop:hooks:fast:r2", payload)  # cached

    assert call_count == 2


def test_update_chop_run_display_empty_state() -> None:
    """A configured chop with no recorded runs paints an empty-state panel."""
    snap = _snapshot_with_runs()  # no runs

    captured: dict[str, object] = {}

    class _Section:
        def update(self, content: object) -> None:
            captured["content"] = content

        def update_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("display_called", True)

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            captured["status"] = (args, kwargs)

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _Section()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    rendered = captured["content"]
    assert isinstance(rendered, Text)
    plain = rendered.plain
    assert "No runs recorded" in plain
    assert "fast description" in plain  # description shown in empty state


def test_update_chop_run_display_renders_newest_run_by_default() -> None:
    """Default run_idx=0 shows the newest run's output via per-run source id."""
    _reset_ansi_cache()
    newest = ChopRunSnapshot(
        entry=_entry("20260511T123500_000000"),
        output_tail="newest output\n",
    )
    older = ChopRunSnapshot(
        entry=_entry("20260511T120000_000000"),
        output_tail="older output\n",
    )
    snap = _snapshot_with_runs(newest, older)

    output_calls: list[tuple[str, str]] = []
    status_calls: list[tuple[tuple, dict]] = []

    class _OutputSection:
        def update_display(self, output: str, source_id: str = "axe-output") -> None:
            output_calls.append((output, source_id))

        def update(self, *_: object, **__: object) -> None:
            output_calls.append(("__update__", "__update__"))

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            status_calls.append((args, kwargs))

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    assert output_calls == [
        ("newest output\n", f"chop:hooks:fast:{newest.entry.run_id}"),
    ]
    # Status section gets the newest run with Run 1/2.
    args, _kwargs = status_calls[0]
    # update_chop_display(lumberjack_name, chop_name, run, run_idx, run_total, countdown)
    assert args[0] == "hooks"
    assert args[1] == "fast"
    assert args[2] is newest
    assert args[3] == 0
    assert args[4] == 2


def test_update_chop_run_display_clamps_out_of_range_idx() -> None:
    """Out-of-range run_idx clamps into the available history range."""
    only = ChopRunSnapshot(
        entry=_entry("only_run"),
        output_tail="only run output\n",
    )
    snap = _snapshot_with_runs(only)

    selected: list[ChopRunSnapshot] = []
    output_payloads: list[str] = []

    class _OutputSection:
        def update_display(self, output: str, source_id: str = "axe-output") -> None:
            output_payloads.append(source_id)

        def update(self, *_: object, **__: object) -> None:
            pass

    class _StatusSection:
        def update_chop_display(
            self,
            lumberjack_name: str,
            chop_name: str,
            run: ChopRunSnapshot | None,
            run_idx: int,
            run_total: int,
            countdown: int,
        ) -> None:
            selected.append(run)  # type: ignore[arg-type]
            assert run_idx == 0  # clamped
            assert run_total == 1

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=99, countdown=0)

    assert selected == [only]
    assert output_payloads == [f"chop:hooks:fast:{only.entry.run_id}"]


def test_update_lumberjack_overview_renders_chop_table() -> None:
    """Lumberjack overview lists configured chops with their last-run status."""
    success = ChopRunSnapshot(
        entry=_entry("a", status="success", duration_ms=420),
        output_tail="",
    )
    failure = ChopRunSnapshot(
        entry=_entry("b", status="failure", duration_ms=1300),
        output_tail="",
    )
    chops = [
        ChopSnapshot(
            lumberjack_name="hooks",
            chop_name="fast",
            description="",
            runs=[success],
        ),
        ChopSnapshot(
            lumberjack_name="hooks",
            chop_name="slow",
            description="",
            runs=[failure],
        ),
        ChopSnapshot(
            lumberjack_name="hooks",
            chop_name="never_run",
            description="",
            runs=[],
        ),
    ]
    snap = LumberjackSnapshot(
        name="hooks",
        status=LumberjackStatus(
            name="hooks",
            pid=1,
            started_at="2026-05-11T00:00:00",
            status="running",
            interval=60,
            cycles_run=5,
            errors_encountered=0,
        ),
        metrics=LumberjackMetrics(chops_executed=2),
        log_tail="",
        chops=chops,
    )

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_lumberjack_overview(self, snapshot: LumberjackSnapshot) -> None:
            captured["snapshot"] = snapshot

        def update(self, content: object) -> None:
            captured["update"] = content

    class _StatusSection:
        def update_lumberjack_display(
            self,
            status: LumberjackStatus | None,
            name: str,
            idx: int,
            total: int,
            countdown: int,
        ) -> None:
            captured["status"] = (status, name, idx, total, countdown)

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_lumberjack_overview(snapshot=snap, idx=0, total=1, countdown=0)

    assert captured["snapshot"] is snap
    assert captured["status"] == (snap.status, "hooks", 0, 1, 0)


def test_chop_status_label_mapping() -> None:
    """Each chop run status maps to a non-empty label."""
    for status in (
        "success",
        "failure",
        "timeout",
        "missing_script",
        "agent_launched",
    ):
        label, style = axe_dashboard._chop_status_label(status)
        assert label
        assert style


def test_format_duration_ms_buckets() -> None:
    """Sub-second, sub-minute, and minute durations format distinctly."""
    assert axe_dashboard._format_duration_ms(250).endswith("ms")
    assert axe_dashboard._format_duration_ms(2_500).endswith("s")
    assert "m" in axe_dashboard._format_duration_ms(75_000)
