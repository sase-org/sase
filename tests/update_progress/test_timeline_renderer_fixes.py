"""Phase timeline-renderer-fixes: model, renderer, and session lifecycle."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from sase.update_progress import (
    FanOutProgress,
    LiveTimelineRenderer,
    PlainTimelineRenderer,
    StepSpec,
    TimelineModel,
    UpdateLogSink,
    UpdateProgressSession,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _console(**kwargs: object) -> Console:
    return Console(record=True, width=80, **kwargs)  # type: ignore[arg-type]


def test_trailing_rows_sort_after_late_declarations() -> None:
    model = TimelineModel(clock=FakeClock())
    model.declare(
        [
            StepSpec(id="restart", title="Restart scheduler", trailing=True),
            StepSpec(
                id="completions", title="Refresh shell completions", trailing=True
            ),
        ]
    )
    model.declare([StepSpec(id="check", title="Check for updates")])
    model.start("late-auto", title="Late auto row")
    assert [row.id for row in model.snapshot()] == [
        "check",
        "late-auto",
        "restart",
        "completions",
    ]


def test_trailing_leaves_children_alone() -> None:
    model = TimelineModel(clock=FakeClock())
    model.declare(
        [
            StepSpec(id="p", title="P"),
            StepSpec(id="p:c", title="C", parent_id="p"),
        ]
    )
    assert model.snapshot()[0].children[0].id == "p:c"


def test_lines_total_counts_past_tail_capacity() -> None:
    model = TimelineModel(clock=FakeClock())
    model.start("build", title="Rebuild")
    for i in range(250):
        model.output("build", "stdout", f"line {i}")
    row = model.snapshot()[0]
    assert row.lines_total == 250
    assert len(row.tail) == 200
    assert row.tail[0] == "line 50"


def test_finalize_marks_running_and_pending_separately() -> None:
    model = TimelineModel(clock=FakeClock())
    model.declare([StepSpec(id="a", title="A"), StepSpec(id="b", title="B")])
    model.start("a")
    model.finalize("skipped", status_for_running="interrupted")
    assert {row.id: row.status for row in model.snapshot()} == {
        "a": "interrupted",
        "b": "skipped",
    }


def test_finalize_defaults_running_to_pending_status() -> None:
    model = TimelineModel(clock=FakeClock())
    model.declare([StepSpec(id="a", title="A"), StepSpec(id="b", title="B")])
    model.start("a")
    model.finalize()
    assert {row.id: row.status for row in model.snapshot()} == {
        "a": "skipped",
        "b": "skipped",
    }


def test_plain_verbose_emits_omitted_marker_once() -> None:
    clock = FakeClock()
    console = _console(force_terminal=False)
    model = TimelineModel(clock=clock)
    model.start("build", title="Rebuild")
    for i in range(250):
        model.output("build", "stdout", f"line {i}")
    renderer = PlainTimelineRenderer(console, model, verbose=True, clock=clock)
    with renderer:
        renderer.poll()
        text = console.export_text(clear=False)
        assert "… 50 lines omitted (see full log)" in text
        assert "line 249" in text
        assert "line 0" not in text
        renderer.poll()
        assert console.export_text(clear=False) == text


def test_plain_prints_nothing_after_print_final() -> None:
    clock = FakeClock()
    console = _console(force_terminal=False)
    model = TimelineModel(clock=clock)
    model.declare([StepSpec(id="a", title="A")])
    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("a")
        model.finish("a", "done", detail="ok")
        renderer.print_final()
        frozen = console.export_text(clear=False)
        model.start("b", title="B")
        model.finish("b", "done")
        renderer.poll()
        assert console.export_text(clear=False) == frozen


def test_session_print_final_is_idempotent_and_skips_pending(
    tmp_path: Path,
) -> None:
    console = _console(force_terminal=False)
    with UpdateProgressSession(console, log_dir=tmp_path) as session:
        session.progress.declare(
            [StepSpec(id="a", title="A"), StepSpec(id="b", title="B")]
        )
        session.progress.start("a")
        session.progress.finish("a", "done")
        session.print_final()
        first = console.export_text(clear=False)
        session.print_final()
        assert console.export_text(clear=False) == first
        assert {row.id: row.status for row in session.model.snapshot()} == {
            "a": "done",
            "b": "skipped",
        }
        assert "– B" in first


def test_session_interrupt_marks_only_running(tmp_path: Path) -> None:
    console = _console(force_terminal=False)
    with UpdateProgressSession(console, log_dir=tmp_path) as session:
        session.progress.declare(
            [StepSpec(id="a", title="A"), StepSpec(id="b", title="B")]
        )
        session.progress.start("a")
        session.interrupt()
        assert {row.id: row.status for row in session.model.snapshot()} == {
            "a": "interrupted",
            "b": "skipped",
        }


def test_live_print_final_leaves_later_stdout_intact(tmp_path: Path) -> None:
    import io as _io

    stream = _io.StringIO()
    err_console = Console(file=stream, width=80, force_terminal=True)
    out_console = Console(file=stream, width=80, force_terminal=True)
    with UpdateProgressSession(err_console, log_dir=tmp_path) as session:
        assert session.kind == "live"
        session.progress.declare([StepSpec(id="a", title="First step")])
        session.progress.start("a")
        session.progress.finish("a", "done", detail="ok")
        session.print_final()
        out_console.print("RESULT PANEL intact")
    captured = stream.getvalue()
    assert "RESULT PANEL intact" in captured
    assert "\x1b[" not in captured.split("RESULT PANEL intact")[-1]


def test_live_running_clock_and_finished_duration() -> None:
    clock = FakeClock()
    console = _console(force_terminal=True)
    model = TimelineModel(clock=clock)
    model.declare(
        [
            StepSpec(id="rebuild", title="Rebuild Rust core into uv-tool venv"),
        ]
    )
    model.start("rebuild")
    clock.advance(31.0)
    console.print(LiveTimelineRenderer(console, model, clock=clock).frame())
    text = console.export_text()
    assert "Rebuild Rust core into uv-tool venv" in text
    assert "0:31" in text
    model.finish("rebuild", "done")
    finished = _console(force_terminal=True)
    finished.print(LiveTimelineRenderer(finished, model, clock=clock).frame())
    assert "31.0s" in finished.export_text()


def test_draw_time_failure_degrades_to_plain_without_verbose() -> None:
    clock = FakeClock()
    console = _console(force_terminal=True)
    model = TimelineModel(clock=clock)
    model.start("a", title="First step")
    model.finish("a", "done", detail="ok")
    renderer = LiveTimelineRenderer(console, model, clock=clock)

    def _raise() -> object:
        raise RuntimeError("draw boom")

    renderer.frame = _raise  # type: ignore[method-assign]
    list(
        LiveTimelineRenderer._Frame(renderer).__rich_console__(console, console.options)
    )
    assert renderer.degraded
    with renderer:
        renderer.poll_verbose()
        assert renderer._plain is not None
        renderer.print_final()
    assert "First step" in console.export_text()


def test_log_sink_omits_empty_mode_and_records_set_mode(tmp_path: Path) -> None:
    sink = UpdateLogSink(log_dir=tmp_path, sase_version="0.0-test")
    assert sink.path is not None
    assert "mode:" not in sink.path.read_text(encoding="utf-8")
    sink.set_mode("dev install")
    assert "mode: dev install" in sink.path.read_text(encoding="utf-8")


def test_log_sink_keeps_constructor_mode(tmp_path: Path) -> None:
    sink = UpdateLogSink(
        mode="managed install", log_dir=tmp_path, sase_version="0.0-test"
    )
    assert sink.path is not None
    assert "mode: managed install" in sink.path.read_text(encoding="utf-8")


def test_session_set_header_reaches_log(tmp_path: Path) -> None:
    console = _console(force_terminal=False)
    with UpdateProgressSession(console, log_dir=tmp_path) as session:
        session.set_header("dev install")
        assert session.log_path is not None
        assert "mode: dev install" in session.log_path.read_text(encoding="utf-8")


def test_dead_members_stay_removed() -> None:
    assert not hasattr(FanOutProgress, "sinks")
    assert not hasattr(UpdateProgressSession, "degraded")


def test_long_detail_yields_to_full_title_at_80_columns() -> None:
    """Details ellipsize first; the 35-char title still renders in full."""
    clock = FakeClock()
    console = _console(force_terminal=True)
    model = TimelineModel(clock=clock)
    model.declare(
        [
            StepSpec(id="inspect", title="Inspect install"),
            StepSpec(id="rebuild", title="Rebuild Rust core into uv-tool venv"),
        ]
    )
    model.start("inspect")
    model.finish("inspect", "done", detail="uv tool · 5 editable · 1 managed")
    console.print(LiveTimelineRenderer(console, model, clock=clock).frame())
    text = console.export_text()
    assert "Rebuild Rust core into uv-tool venv" in text
    assert "uv tool · 5 editable · 1 managed" not in text
    assert "…" in text
