"""Plain renderer lines, start delay, failure tails, and verbose output."""

from __future__ import annotations

import threading

from rich.console import Console

from sase.update_progress import (
    PlainTimelineRenderer,
    StepSpec,
    TimelineModel,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_console() -> Console:
    return Console(record=True, width=80, force_terminal=False)


def test_header_and_finish_lines() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.declare([StepSpec(id="inspect", title="Inspect install")])

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    renderer.set_header("dev install")
    with renderer:
        model.start("inspect")
        clock.advance(0.4)
        model.finish("inspect", "done", detail="uv tool · 5 editable · 1 managed")
        renderer.poll()
    text = console.export_text()
    assert "sase update · dev install" in text
    assert "[00:00] ✓ Inspect install — uv tool · 5 editable · 1 managed (0.4s)" in text


def test_start_line_prints_only_after_two_seconds() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("rebuild", title="Rebuild Rust core into uv-tool venv")
        clock.advance(1.0)
        renderer.poll()
        assert "→ Rebuild Rust core" not in console.export_text(clear=False)
        clock.advance(1.5)
        renderer.poll()
        assert "→ Rebuild Rust core into uv-tool venv" in console.export_text(
            clear=False
        )
        renderer.poll()
    assert console.export_text().count("→ Rebuild Rust core") == 1


def test_failure_tail_expands_last_twenty_lines() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("build", title="Rebuild")
        for i in range(25):
            model.output("build", "stdout", f"error line {i}")
        model.finish("build", "failed", detail="link error")
        renderer.poll()
    text = console.export_text()
    assert "✗ Rebuild — link error" in text
    assert "error line 24" in text
    assert "error line 5" in text
    assert "error line 4" not in text


def test_verbose_streams_every_output_line() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, verbose=True, clock=clock)
    with renderer:
        model.start("build", title="Rebuild")
        model.output("build", "stdout", "Compiling foo")
        model.output("build", "stderr", "warning: unused")
        renderer.poll()
        renderer.poll()
    text = console.export_text()
    assert "Compiling foo" in text
    assert "warning: unused" in text
    assert text.count("Compiling foo") == 1


def test_quiet_mode_prints_no_output_lines() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, verbose=False, clock=clock)
    with renderer:
        model.start("build", title="Rebuild")
        model.output("build", "stdout", "Compiling foo")
        renderer.poll()
    assert "Compiling foo" not in console.export_text()


def test_skipped_and_interrupted_glyphs() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.declare([StepSpec(id="a", title="Step A"), StepSpec(id="b", title="Step B")])

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("a")
        model.finish("a", "skipped", detail="prebuilt artifacts used")
        model.start("b")
        model.finish("b", "interrupted")
        renderer.poll()
    text = console.export_text()
    assert "– Step A — prebuilt artifacts used" in text
    assert "■ Step B" in text


def test_concurrent_poll_prints_each_line_once() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("build", title="Rebuild")
        clock.advance(3.0)
        threads = [threading.Thread(target=renderer.poll) for _ in range(8)]
        for thread in threads:
            thread.start()
        renderer.poll()
        for thread in threads:
            thread.join(timeout=10.0)
        model.finish("build", "done", detail="ok")
        renderer.poll()
    assert all(not thread.is_alive() for thread in threads)
    text = console.export_text()
    assert text.count("→ Rebuild") == 1
    assert text.count("✓ Rebuild — ok") == 1


def test_no_color_codes_when_not_a_terminal() -> None:
    clock = FakeClock()
    console = make_console()
    assert console.is_terminal is False
    model = TimelineModel(clock=clock)

    renderer = PlainTimelineRenderer(console, model, clock=clock)
    with renderer:
        model.start("a", title="Step A")
        model.finish("a", "done")
        renderer.poll()
    assert "\x1b[" not in console.export_text()
