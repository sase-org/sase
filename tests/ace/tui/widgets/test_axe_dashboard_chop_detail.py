"""Phase 4: AXE dashboard renders lumberjack overview and chop detail."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.actions.axe_display._data import (
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.util import axe_log_renderer
from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus


def _entry(
    run_id: str,
    *,
    status: str = "success",
    duration_ms: int = 250,
    output_log: str = "run.log",
    finished_at: str | None = "2026-05-11T12:34:57",
    exit_code: int | None = None,
    pid: int | None = None,
    source: str = "scheduled",
) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-05-11T12:34:56",
        finished_at=finished_at,
        duration_ms=duration_ms,
        status=status,  # type: ignore[arg-type]
        exit_code=exit_code
        if exit_code is not None
        else (0 if status == "success" else 1),
        output_log=output_log,
        pid=pid,
        source=source,  # type: ignore[arg-type]
    )


def _snapshot_with_runs(*runs: ChopRunSnapshot) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="fast description",
        runs=list(runs),
    )


def _reset_ansi_cache() -> None:
    axe_log_renderer._render_cache.clear()


def test_chop_run_ansi_cache_keyed_by_run_id() -> None:
    """Two different runs of the same chop don't collide in the render cache."""
    _reset_ansi_cache()

    payload = "shared\n"

    call_count = 0
    real_from_ansi = Text.from_ansi

    def _counting(text: str) -> Text:
        nonlocal call_count
        call_count += 1
        return real_from_ansi(text)

    with patch.object(Text, "from_ansi", staticmethod(_counting)):
        axe_log_renderer.render_axe_output("chop:hooks:fast:r1", payload, "ansi")
        axe_log_renderer.render_axe_output("chop:hooks:fast:r2", payload, "ansi")
        axe_log_renderer.render_axe_output(
            "chop:hooks:fast:r1", payload, "ansi"
        )  # cached
        axe_log_renderer.render_axe_output(
            "chop:hooks:fast:r2", payload, "ansi"
        )  # cached

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
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
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
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
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


def test_chop_status_label_mapping() -> None:
    """Each chop run status maps to a non-empty label."""
    for status in (
        "success",
        "failure",
        "timeout",
        "missing_script",
        "agent_launched",
        "running",
    ):
        label, style = axe_dashboard._chop_status_label(status)
        assert label
        assert style


def test_format_duration_ms_buckets() -> None:
    """Sub-second, sub-minute, and minute durations format distinctly."""
    assert axe_dashboard._format_duration_ms(250).endswith("ms")
    assert axe_dashboard._format_duration_ms(2_500).endswith("s")
    assert "m" in axe_dashboard._format_duration_ms(75_000)


def test_chop_status_running_label_style() -> None:
    """The running status renders as a non-empty live label."""
    label, style = axe_dashboard._chop_status_label("running")
    assert "running" in label.lower()
    assert "green" in style


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


def test_update_chop_run_display_agent_launched_uses_controlled_source_type() -> None:
    """Agent-launched chop runs render through the controlled-chop highlighter
    so the synthetic launch line gets the agent-launched accent and PID color."""
    launch_run = ChopRunSnapshot(
        entry=_entry("run-agent", status="agent_launched"),
        output_tail="Launched agent chop 'fast' (PID 9201)\n",
    )
    snap = _snapshot_with_runs(launch_run)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            captured["source_type"] = source_type

        def update(self, *_: object, **__: object) -> None:
            pass

    class _StatusSection:
        def update_chop_display(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    assert captured["source_type"] == "chop_controlled"


def test_update_chop_run_display_script_run_stays_on_ansi() -> None:
    """Script chop runs keep the ANSI fallback — their output is arbitrary."""
    script_run = ChopRunSnapshot(
        entry=_entry("run-script", status="success"),
        output_tail="\x1b[32mall good\x1b[0m\n",
    )
    snap = _snapshot_with_runs(script_run)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(
            self,
            output: str,
            source_id: str = "axe-output",
            source_type: str = "ansi",
        ) -> None:
            captured["source_type"] = source_type

        def update(self, *_: object, **__: object) -> None:
            pass

    class _StatusSection:
        def update_chop_display(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return _StatusSection()
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    assert captured["source_type"] == "ansi"


def test_render_chop_display_running_run_shows_elapsed_and_pid() -> None:
    """Running runs show Elapsed/PID/source instead of Took/Exit."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
            pid=12345,
            source="manual",
        ),
        output_tail="",
    )
    snap = _snapshot_with_runs(running)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(self, *args: object, **kwargs: object) -> None:
            captured["display"] = (args, kwargs)

        def update(self, content: object) -> None:
            captured["update"] = content

    # Reuse the real status section so we can inspect its rendered Text.
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]

    rendered: dict[str, object] = {}

    def _capture_update(content: object) -> None:
        rendered["content"] = content

    section.update = _capture_update  # type: ignore[assignment]

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return section
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    text = rendered["content"]
    assert isinstance(text, Text)
    plain = text.plain
    assert "running" in plain.lower()
    assert "Elapsed:" in plain
    assert "Took:" not in plain
    assert "PID:" in plain
    assert "12345" in plain
    # Manual source surfaces a marker so the user can tell why it ran.
    assert "manual" in plain
    # Exit code is suppressed for active runs.
    assert "Exit:" not in plain


def test_render_chop_display_scheduled_run_hides_source_marker() -> None:
    """The default scheduled source stays compact (no Source: chip)."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
            pid=4242,
            source="scheduled",
        ),
        output_tail="",
    )
    snap = _snapshot_with_runs(running)

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    class _OutputSection:
        def update_display(self, *_a: object, **_kw: object) -> None:
            pass

        def update(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        section if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    plain = rendered["content"].plain  # type: ignore[union-attr]
    assert "Source:" not in plain


def test_render_chop_display_running_with_no_output_shows_waiting() -> None:
    """An active run with no output yet shows a 'Waiting…' placeholder."""
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
    snap = _snapshot_with_runs(running)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("display", (args, kwargs))

        def update(self, content: object) -> None:
            captured["update"] = content

    class _StatusSection:
        def update_chop_display(self, *args: object, **kwargs: object) -> None:
            captured.setdefault("status", (args, kwargs))

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        _StatusSection() if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    rendered = captured["update"]
    assert isinstance(rendered, Text)
    assert "waiting" in rendered.plain.lower()
    # Output section's update_display path (for non-empty output) is unused.
    assert "display" not in captured


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


def test_status_section_renders_no_wrap_text() -> None:
    """All status renderers construct ``Text`` with ``no_wrap`` so the 1-cell
    status bar truncates cleanly rather than wrapping into the output panel."""
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]

    captured: list[Text] = []
    section.update = lambda content: captured.append(content)  # type: ignore[assignment,arg-type]

    section.update_lumberjack_display(
        status=LumberjackStatus(
            name="hooks",
            pid=1,
            started_at="2026-05-11T00:00:00",
            status="running",
            interval=60,
            cycles_run=2,
            errors_encountered=0,
        ),
        name="hooks",
        idx=0,
        total=1,
    )
    section.update_chop_display(
        lumberjack_name="hooks",
        chop_name="fast",
        run=None,
        run_idx=0,
        run_total=0,
    )
    section.update_display(status=None, is_running=True, full_cycles=0)
    section.update_bgcmd_display(info=None, is_running=False)

    assert captured, "status section never emitted a Text"
    for text in captured:
        assert text.no_wrap is True
        assert text.overflow == "ellipsis"


def test_chop_status_header_colors_names_with_sidebar_taxonomy() -> None:
    """The chop status header colors the lumberjack and chop names with the
    sidebar gold/copper hues so the header echoes the sidebar tree."""
    run = ChopRunSnapshot(
        entry=_entry("a", status="success"),
        output_tail="",
    )
    snap = _snapshot_with_runs(run)

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    class _OutputSection:
        def update_display(self, *_a: object, **_kw: object) -> None:
            pass

        def update(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        section if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    text = rendered["content"]
    assert isinstance(text, Text)
    spans = {(s.style, text.plain[s.start : s.end]) for s in text.spans}
    # Lumberjack name colored in the sidebar's gold accent.
    assert any(
        "FFD700" in str(style) and "hooks" in fragment for style, fragment in spans
    )
    # Chop name colored in the sidebar's copper child hue.
    assert any(
        "D7AF87" in str(style) and "fast" in fragment for style, fragment in spans
    )


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
