"""Live renderer frames, row budget, failure expansion, and fallback."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.update_progress import (
    LiveTimelineRenderer,
    StepSpec,
    TimelineModel,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_console() -> Console:
    return Console(record=True, width=80, force_terminal=True)


def test_live_frame_layout_matches_target() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.declare(
        [
            StepSpec(id="inspect", title="Inspect install"),
            StepSpec(id="check", title="Check for updates"),
            StepSpec(id="rebuild", title="Rebuild Rust core into uv-tool venv"),
            StepSpec(id="verify", title="Verify sase-core-rs imports"),
        ]
    )
    model.start("inspect")
    model.finish("inspect", "done", detail="uv tool · 5 editable · 1 managed")
    clock.advance(0.4)
    model.start("check")
    model.output("check", "stdout", "From origin")
    clock.advance(0.1)

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    renderer.set_header("dev install")
    console.print(renderer.frame())
    text = console.export_text()
    assert "sase update · dev install" in text
    assert "✓" in text
    assert "Inspect install" in text
    assert "uv tool · 5 editable · 1 managed" in text
    assert "Check for updates" in text


def test_live_tail_shows_last_three_lines() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.start("rebuild", title="Rebuild Rust core into uv-tool venv")
    for i in range(5):
        model.output("rebuild", "stdout", f"Compiling crate-{i}")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    console.print(renderer.frame())
    text = console.export_text()
    assert "Compiling crate-2" in text
    assert "Compiling crate-3" in text
    assert "Compiling crate-4" in text
    assert "Compiling crate-0" not in text
    assert "Compiling crate-1" not in text


def test_markup_like_output_renders_literally() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.start("rebuild", title="Rebuild")
    model.output("rebuild", "stdout", "[red]x[/] ok")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    console.print(renderer.frame())
    assert "[red]x[/] ok" in console.export_text()


def test_narrow_width_ellipsizes() -> None:
    clock = FakeClock()
    console = Console(record=True, width=40, force_terminal=True)
    model = TimelineModel(clock=clock)
    model.start("inspect", title="Inspect install with a very long title here")
    model.finish("inspect", "done", detail="uv tool · 5 editable · 1 managed detail")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    console.print(renderer.frame())
    for line in console.export_text().splitlines():
        assert len(line) <= 40


def test_row_budget_collapses_finished_children() -> None:
    clock = FakeClock()
    console = Console(record=True, width=80, height=8, force_terminal=True)
    model = TimelineModel(clock=clock)
    specs = [StepSpec(id="check", title="Check for updates")]
    specs += [
        StepSpec(id=f"check:{i}", title=f"repo-{i}", parent_id="check")
        for i in range(6)
    ]
    specs += [StepSpec(id="other", title="Other step")]
    model.declare(specs)
    model.start("check")
    for i in range(6):
        model.start(f"check:{i}")
        model.finish(f"check:{i}", "done", detail="current")
    model.finish("check", "done", detail="6 current")
    model.start("other")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    console.print(renderer.frame())
    text = console.export_text()
    assert "+6 more" in text
    assert "repo-0" not in text


def test_running_step_and_failures_never_hidden() -> None:
    clock = FakeClock()
    console = Console(record=True, width=80, height=8, force_terminal=True)
    model = TimelineModel(clock=clock)
    specs = [StepSpec(id=f"s{i}", title=f"Step number {i}") for i in range(10)]
    model.declare(specs)
    for i in range(8):
        model.start(f"s{i}")
        model.finish(f"s{i}", "done")
    model.start("s8", title="Step number 8")
    model.output("s8", "stdout", "tail line here")
    model.start("s9")
    model.finish("s9", "failed", detail="boom")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    console.print(renderer.frame())
    text = console.export_text()
    assert "Step number 8" in text
    assert "Step number 9" in text


def test_print_final_expands_failures_and_footer() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.declare(
        [StepSpec(id="a", title="First step"), StepSpec(id="b", title="Second step")]
    )
    model.start("a")
    clock.advance(1.0)
    model.finish("a", "done")
    model.start("b", title="Second step")
    for i in range(25):
        model.output("b", "stdout", f"error line {i}")
    clock.advance(2.0)
    model.finish("b", "failed", detail="link error")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    renderer.set_header("dev install")
    renderer.print_final()
    text = console.export_text()
    assert "✗" in text
    assert "error line 24" in text
    assert "error line 5" in text
    assert "error line 4" not in text
    assert "slowest:" in text


def test_print_final_drops_tails_without_expansion() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.start("b", title="Second step")
    model.output("b", "stdout", "some output")
    model.finish("b", "failed", detail="boom")

    renderer = LiveTimelineRenderer(console, model, clock=clock)
    renderer.print_final(expand_failures=False)
    assert "some output" not in console.export_text()


def test_render_failure_falls_back_to_plain() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.start("a", title="First step")
    model.finish("a", "done", detail="ok")

    renderer = LiveTimelineRenderer(console, model, clock=clock)

    def _raise() -> Panel:
        raise RuntimeError("render boom")

    renderer.frame = _raise  # type: ignore[method-assign]
    fallback = LiveTimelineRenderer._Frame(renderer).__rich__()
    assert isinstance(fallback, Text)
    assert "progress unavailable" in fallback.plain
    assert renderer.degraded
    with renderer:
        renderer.print_final()
    assert "First step" in console.export_text()


def test_verbose_lines_print_above_live_region() -> None:
    clock = FakeClock()
    console = make_console()
    model = TimelineModel(clock=clock)
    model.start("build", title="Rebuild")
    model.output("build", "stdout", "Compiling foo")

    renderer = LiveTimelineRenderer(console, model, verbose=True, clock=clock)
    with renderer:
        renderer.poll_verbose()
        renderer.poll_verbose()
    text = console.export_text()
    verbose_lines = [
        line for line in text.splitlines() if line == "    │ Compiling foo"
    ]
    assert len(verbose_lines) == 1
