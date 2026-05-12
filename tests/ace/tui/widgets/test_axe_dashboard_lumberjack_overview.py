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
from sase.axe.state import LumberjackMetrics, LumberjackStatus

from ._axe_dashboard_helpers import _entry


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
