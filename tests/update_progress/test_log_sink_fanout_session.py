"""Log sink content, retention, fallback, fan-out isolation, and sessions."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from sase.update_progress import (
    FanOutProgress,
    NullProgress,
    StepSpec,
    TimelineModel,
    UpdateLogSink,
    UpdateProgressSession,
    select_renderer,
)


def test_log_sink_writes_header_steps_and_output(tmp_path: Path) -> None:
    sink = UpdateLogSink(
        argv=["sase", "update"],
        mode="dev install",
        log_dir=tmp_path,
        sase_version="0.0-test",
    )
    assert sink.path is not None
    sink.declare([StepSpec(id="check", title="Check for updates")])
    sink.start("check")
    sink.command("check", ["git", "fetch", "origin"], cwd="/repo")
    sink.output("check", "stdout", "From origin")
    sink.finish("check", "done", detail="2 behind")
    sink.finalize()

    text = sink.path.read_text(encoding="utf-8")
    assert "argv: sase update" in text
    assert "sase: 0.0-test" in text
    assert "mode: dev install" in text
    assert "START check" in text
    assert "COMMAND check" in text and "git fetch origin" in text
    assert "OUTPUT check stdout: From origin" in text
    assert "FINISH check done" in text


def test_log_sink_keeps_newest_twenty(tmp_path: Path) -> None:
    for i in range(22):
        (tmp_path / f"update-202601{i:02d}T000000Z-1.log").write_text("old\n")
    sink = UpdateLogSink(log_dir=tmp_path)
    assert sink.path is not None
    remaining = sorted(p.name for p in tmp_path.glob("update-*.log"))
    assert len(remaining) == 20
    assert sink.path.name in remaining
    assert "update-20260100T000000Z-1.log" not in remaining
    assert "update-20260101T000000Z-1.log" not in remaining


def test_log_sink_unwritable_dir_disables_silently(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir\n")
    sink = UpdateLogSink(log_dir=blocker / "update")
    assert sink.path is None
    sink.start("a")
    sink.output("a", "stdout", "x")
    sink.finish("a", "done")
    sink.finalize()


def test_fanout_forwards_and_isolates() -> None:
    class Exploding(NullProgress):
        def __init__(self) -> None:
            self.events: list[str] = []

        def start(
            self, id: str, *, title: str | None = None, detail: str | None = None
        ) -> None:
            self.events.append(id)
            raise RuntimeError("sink boom")

    model = TimelineModel()
    exploding = Exploding()
    fanout = FanOutProgress(model, exploding)
    fanout.declare([StepSpec(id="a", title="A")])
    fanout.start("a")
    fanout.output("a", "stdout", "hello")
    fanout.command("a", ["git", "fetch"])
    fanout.finish("a", "done")
    fanout.finalize()
    assert exploding.events == ["a"]
    row = model.snapshot()[0]
    assert row.status == "done"
    assert row.tail == ("hello",)
    fanout.output_sink("a")("stdout", "more")
    assert model.snapshot()[0].tail == ("hello", "more")


def test_select_renderer_modes() -> None:
    live_console = Console(force_terminal=True)
    assert (
        select_renderer(live_console, as_json=False, quiet=False, verbose=False)
        == "live"
    )
    assert (
        select_renderer(live_console, as_json=True, quiet=False, verbose=False)
        == "none"
    )
    assert (
        select_renderer(live_console, as_json=False, quiet=True, verbose=False)
        == "none"
    )
    pipe_console = Console(force_terminal=False)
    assert (
        select_renderer(pipe_console, as_json=False, quiet=False, verbose=False)
        == "plain"
    )


def test_session_plain_end_to_end(tmp_path: Path) -> None:
    console = Console(record=True, width=80, force_terminal=False)
    with UpdateProgressSession(
        console, mode="dev install", argv=["sase", "update"], log_dir=tmp_path
    ) as session:
        assert session.shown
        assert not session.degraded
        session.set_header("dev install")
        session.progress.declare([StepSpec(id="inspect", title="Inspect install")])
        session.progress.start("inspect")
        session.progress.output("inspect", "stdout", "hi")
        session.progress.finish("inspect", "done", detail="ok")
        session.print_final()
    text = console.export_text()
    assert "sase update · dev install" in text
    assert "Inspect install" in text
    assert session.log_path is not None
    assert "START inspect" in session.log_path.read_text(encoding="utf-8")


def test_session_none_for_json_leaves_log_only(tmp_path: Path) -> None:
    console = Console(record=True, width=80, force_terminal=True)
    with UpdateProgressSession(console, as_json=True, log_dir=tmp_path) as session:
        assert not session.shown
        session.progress.start("inspect", title="Inspect install")
        session.progress.finish("inspect", "done")
        session.print_final()
    assert console.export_text() == ""
    assert session.log_path is not None


def test_session_finalizes_leftovers_on_exit(tmp_path: Path) -> None:
    console = Console(record=True, width=80, force_terminal=False)
    with UpdateProgressSession(console, log_dir=tmp_path) as session:
        session.progress.start("hanging", title="Hanging step")
    assert session.model.snapshot()[0].status == "skipped"
