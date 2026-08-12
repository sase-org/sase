"""Phase 4: AXE dashboard lumberjack overview, summary, and log-tail behavior."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.actions.axe_display._data import (
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.util import axe_log_renderer
from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import LumberjackMetrics, LumberjackStatus

from ._axe_dashboard_helpers import _entry


def _overrun(
    level: str, *, worst_ratio: float | None, latest_ratio: float | None
) -> ChopOverrun:
    return ChopOverrun(
        level=level,  # type: ignore[arg-type]
        sampled_runs=8,
        over_runs=2 if level != "none" else 0,
        worst_ratio=worst_ratio,
        worst_blocking_ms=None,
        latest_ratio=latest_ratio,
    )


def _overview_snapshot(
    *,
    log_tail: str = "",
    chops: list[ChopSnapshot] | None = None,
    interval: int = 60,
) -> LumberjackSnapshot:
    return LumberjackSnapshot(
        name="hooks",
        status=LumberjackStatus(
            name="hooks",
            pid=1,
            started_at="2026-05-11T00:00:00",
            status="running",
            interval=interval,
            cycles_run=3,
            errors_encountered=0,
        ),
        metrics=LumberjackMetrics(chops_executed=2),
        log_tail=log_tail,
        chops=chops or [],
    )


def _capture_overview(snap: LumberjackSnapshot, *, width: int | None) -> Text:
    """Render via the real ``_AxeOutputSection`` and capture the Rich Text."""
    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeOutputSection.__new__(axe_dashboard._AxeOutputSection)
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]
    section.update_lumberjack_overview(snap, width=width)
    out = rendered["content"]
    assert isinstance(out, Text)
    return out


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
        def update_lumberjack_overview(
            self, snapshot: LumberjackSnapshot, width: int | None = None
        ) -> None:
            captured["snapshot"] = snapshot
            captured["width"] = width

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


def test_update_lumberjack_display_uses_semantic_source_type() -> None:
    """Lumberjack aggregate logs route through the ``lumberjack`` source type
    so the semantic highlighter colors timestamps, names, status words, and
    PIDs instead of relying on raw ANSI escapes from the underlying tool."""
    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            captured["output"] = output
            captured["source_id"] = source_id
            captured["source_type"] = source_type

    class _StatusSection:
        def update_lumberjack_display(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_lumberjack_display(
        name="hooks",
        idx=0,
        total=1,
        status=None,
        output="[2026-05-11 12:34:56] [hooks] success\n",
    )

    assert captured["source_type"] == "lumberjack"
    assert captured["source_id"] == "lumberjack:hooks"


def test_lumberjack_overview_renders_running_chop_with_elapsed() -> None:
    """Running chops in the lumberjack overview table show elapsed runtime."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
        ),
        output_tail="",
    )
    chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="",
        runs=[running],
    )

    rendered: dict[str, object] = {}

    section = axe_dashboard._AxeOutputSection.__new__(axe_dashboard._AxeOutputSection)
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    section.update_lumberjack_overview(
        LumberjackSnapshot(
            name="hooks",
            status=LumberjackStatus(
                name="hooks",
                pid=1,
                started_at="2026-05-11T00:00:00",
                status="running",
                interval=60,
            ),
            metrics=LumberjackMetrics(),
            log_tail="",
            chops=[chop],
        )
    )

    plain = rendered["content"].plain  # type: ignore[union-attr]
    assert "running" in plain.lower()
    # Running rows do not display the static "0ms" final duration; the
    # column shows the elapsed runtime label instead.
    assert "0ms" not in plain


# --- Phase 4: dashboard polish under narrow widths and log-tail integration ---


def test_lumberjack_overview_wide_layout_renders_table_header() -> None:
    """At default width the chop table renders with its column header row."""
    snap = _overview_snapshot(
        chops=[
            ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="fast",
                description="",
                runs=[
                    ChopRunSnapshot(
                        entry=_entry("a", status="success", duration_ms=420),
                        output_tail="",
                    )
                ],
            )
        ],
    )

    plain = _capture_overview(snap, width=120).plain
    # Header row tokens only appear in the wide table layout.
    assert "NAME" in plain
    assert "LAST RUN" in plain
    assert "DURATION" in plain
    # Status line uses four-space separators, not stacking newlines.
    assert "Status: ● running    Interval:" in plain


def test_lumberjack_overview_narrow_layout_stacks_fields_and_chops() -> None:
    """Below the narrow threshold the overview stacks header fields and chops."""
    snap = _overview_snapshot(
        chops=[
            ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="fast",
                description="",
                runs=[
                    ChopRunSnapshot(
                        entry=_entry("a", status="success", duration_ms=420),
                        output_tail="",
                    )
                ],
            ),
            ChopSnapshot(
                lumberjack_name="hooks",
                chop_name="never_run",
                description="",
                runs=[],
            ),
        ],
    )

    plain = _capture_overview(snap, width=40).plain
    # The wide table's column header must not appear in compact mode.
    assert "LAST RUN" not in plain
    assert "DURATION" not in plain
    # Each chop name appears on its own line, followed by an indented
    # metadata line ("· success ·" or "never run").
    assert "  fast\n" in plain
    assert "success" in plain
    assert "never run" in plain
    # Header fields are stacked, not joined with four-space gaps.
    assert "Status: ● running    Interval:" not in plain
    assert "Interval: 60s" in plain


def test_lumberjack_overview_log_tail_uses_semantic_highlighter() -> None:
    """A non-empty log_tail surfaces a RECENT LOG section rendered semantically."""
    axe_log_renderer._render_cache.clear()
    log_tail = "\n".join(
        [
            "[2026-05-11 12:34:50] [hooks] success",
            "[2026-05-11 12:34:55] [hooks] running 3 chops",
            "[2026-05-11 12:35:00] [hooks] failure exit code 1",
            "",
        ]
    )
    snap = _overview_snapshot(log_tail=log_tail, chops=[])

    text = _capture_overview(snap, width=120)
    plain = text.plain
    assert "RECENT LOG" in plain
    # The semantic highlighter classified the tail through the
    # ``lumberjack:<name>:overview-tail`` cache slot so it does not collide
    # with ``update_lumberjack_display``'s full-log render.
    cache = axe_log_renderer._render_cache
    assert ("lumberjack:hooks:overview-tail", "lumberjack") in cache
    # The full-log slot must not be populated as a side effect.
    assert ("lumberjack:hooks", "lumberjack") not in cache


def test_lumberjack_overview_empty_log_tail_omits_recent_section() -> None:
    """When the cache has no log tail the RECENT LOG block is hidden entirely."""
    snap = _overview_snapshot(log_tail="", chops=[])
    text = _capture_overview(snap, width=120)
    assert "RECENT LOG" not in text.plain


def test_lumberjack_overview_no_traceback_on_huge_output() -> None:
    """A pathological log tail must still render — the tail is line-capped."""
    big = "[2026-05-11 12:34:56] [hooks] success\n" * 10_000
    snap = _overview_snapshot(log_tail=big, chops=[])
    text = _capture_overview(snap, width=120)
    plain = text.plain
    # Only the configured tail-window is included so the overview never
    # crowds the chop table even with a 10k-line log.
    assert plain.count("[hooks] success") <= 10


def test_lumberjack_summary_narrow_layout_stacks_rows() -> None:
    """The activity summary degrades to a stacked layout on narrow widths."""
    summaries: list[axe_dashboard.LumberjackSummary] = [
        (
            "hooks",
            LumberjackStatus(
                name="hooks",
                pid=1,
                started_at="2026-05-11T00:00:00",
                status="running",
                interval=60,
                cycles_run=5,
                errors_encountered=0,
            ),
            2,
        ),
    ]

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeOutputSection.__new__(axe_dashboard._AxeOutputSection)
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]
    section.update_lumberjack_summary(summaries, width=40)

    plain = rendered["content"].plain  # type: ignore[union-attr]
    # The full-width column header should be suppressed below the
    # narrow threshold.
    assert "LAST CYCLE" not in plain
    # Each row stacks: name on its own line, metadata indented below.
    assert "  hooks\n" in plain
    assert "5c" in plain
    assert "running" in plain.lower()


def test_lumberjack_overview_renders_when_snapshot_has_no_metrics() -> None:
    """Edge case: a snapshot without metrics (cold-miss) still renders cleanly."""
    snap = LumberjackSnapshot(
        name="hooks",
        status=None,
        metrics=None,
        log_tail="",
        chops=[],
    )
    plain = _capture_overview(snap, width=120).plain
    # Header still names the status, even if it falls back to "unknown".
    assert "Status:" in plain
    # No chops means the placeholder message; no traceback.
    assert "No chops configured" in plain


# --- tab_indicator: PACE column, compact chip, advisory line ---


def _chop_with_overrun(
    name: str,
    *,
    status: str = "success",
    duration_ms: int = 240_000,
    interval_seconds: int | None = 60,
    interval_source: str = "runtime",
    overrun: ChopOverrun | None = None,
) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name=name,
        description="",
        runs=[
            ChopRunSnapshot(
                entry=_entry("a", status=status, duration_ms=duration_ms),
                output_tail="",
            )
        ],
        interval_seconds=interval_seconds,
        interval_source=interval_source,  # type: ignore[arg-type]
        overrun=overrun,
    )


def test_wide_chop_table_pace_column_header_and_over_ratio() -> None:
    """PACE header appears and an over chop's row shows the bold amber ratio."""
    chop = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    snap = _overview_snapshot(chops=[chop])
    text = _capture_overview(snap, width=120)
    plain = text.plain
    assert "PACE" in plain
    assert "⚠ 4.0×" in plain
    pace_spans = [
        str(span.style)
        for span in text.spans
        if "⚠ 4.0×" in plain[span.start : span.end]
    ]
    assert pace_spans and all("bold #FFAF5F" in style for style in pace_spans)


def test_wide_chop_table_pace_column_dim_ratio_when_not_over() -> None:
    """A sampled-but-not-over latest run shows a dim plain ratio, no ⚠."""
    chop = _chop_with_overrun(
        "steady",
        overrun=_overrun("intermittent", worst_ratio=1.2, latest_ratio=0.4),
    )
    snap = _overview_snapshot(chops=[chop])
    plain = _capture_overview(snap, width=120).plain
    assert "0.4×" in plain
    assert "⚠ 0.4×" not in plain


def test_wide_chop_table_pace_column_dash_when_unsampleable() -> None:
    """No overrun verdict renders the PACE dash, matching other empty cells."""
    chop = _chop_with_overrun("never_sampled", overrun=None)
    snap = _overview_snapshot(chops=[chop])
    plain = _capture_overview(snap, width=120).plain
    lines = [ln for ln in plain.splitlines() if "never_sampled" in ln]
    assert lines
    assert lines[0].rstrip().endswith("—")


def test_wide_chop_table_row_width_matches_68_cell_rule() -> None:
    """The re-spaced NAME/LAST RUN/WHEN/DURATION/PACE header stays at 68 cells."""
    chop = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    snap = _overview_snapshot(chops=[chop])
    plain = _capture_overview(snap, width=120).plain
    lines = plain.splitlines()
    header_line = next(ln for ln in lines if ln.strip().startswith("NAME"))
    data_line = next(ln for ln in lines if "mentor_sweep" in ln)
    assert len(header_line) == 68
    assert len(data_line) == 68


def test_compact_chop_list_appends_ratio_chip() -> None:
    """The narrow compact list appends ` · ⚠ 4.0×` for an over chop."""
    chop = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    snap = _overview_snapshot(chops=[chop])
    plain = _capture_overview(snap, width=40).plain
    assert " · ⚠ 4.0×" in plain


def test_advisory_line_single_over_chop() -> None:
    """One over chop names itself directly with its ratio and the interval."""
    chop = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    snap = _overview_snapshot(chops=[chop], interval=60)
    plain = _capture_overview(snap, width=120).plain
    assert (
        "⚠ mentor_sweep reached 4.0× this lumberjack's 60s interval on its last run."
        in plain
    )
    assert "Raise `interval` or move the chop into its own lumberjack." in plain


def test_advisory_line_multiple_over_chops_collapse_to_worst() -> None:
    """Several over chops collapse to a count naming the worst by ratio."""
    worse = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=6.0, latest_ratio=6.0),
    )
    milder = _chop_with_overrun(
        "bead_triage",
        overrun=_overrun("over", worst_ratio=2.0, latest_ratio=2.0),
    )
    snap = _overview_snapshot(chops=[worse, milder], interval=60)
    plain = _capture_overview(snap, width=120).plain
    assert "⚠ 2 chops reached this lumberjack's 60s interval" in plain
    assert "worst 6.0×: mentor_sweep" in plain


def test_advisory_line_intermittent_gets_second_dim_line() -> None:
    """An intermittent chop is named on its own dim line below the primary one."""
    over_chop = _chop_with_overrun(
        "mentor_sweep",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    intermittent_chop = _chop_with_overrun(
        "bead_triage",
        overrun=ChopOverrun(
            level="intermittent",
            sampled_runs=8,
            over_runs=2,
            worst_ratio=1.5,
            worst_blocking_ms=None,
            latest_ratio=0.5,
        ),
    )
    snap = _overview_snapshot(chops=[over_chop, intermittent_chop], interval=60)
    plain = _capture_overview(snap, width=120).plain
    assert "bead_triage exceeded the interval on 2 of its last 8 runs." in plain


def test_advisory_line_absent_when_no_chop_marked() -> None:
    """No advisory renders when every chop is at overrun level none."""
    healthy = _chop_with_overrun(
        "fix_hooks",
        overrun=_overrun("none", worst_ratio=None, latest_ratio=None),
    )
    snap = _overview_snapshot(chops=[healthy], interval=60)
    plain = _capture_overview(snap, width=120).plain
    assert "⚠" not in plain
    assert "Raise `interval`" not in plain


def test_advisory_line_appends_configured_interval_suffix() -> None:
    """A config-sourced interval (lumberjack not running) gets a dim suffix."""
    chop = _chop_with_overrun(
        "mentor_sweep",
        interval_source="config",
        overrun=_overrun("over", worst_ratio=4.0, latest_ratio=4.0),
    )
    snap = _overview_snapshot(chops=[chop], interval=60)
    plain = _capture_overview(snap, width=120).plain
    assert "(configured interval — lumberjack not running)" in plain
