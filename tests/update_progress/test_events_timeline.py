"""Model transitions, auto-behaviors, context manager, and thread safety."""

from __future__ import annotations

import threading

import pytest

from sase.update_progress import (
    NULL_PROGRESS,
    StepSpec,
    TimelineModel,
    step,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_declare_start_finish_lifecycle() -> None:
    clock = FakeClock()
    model = TimelineModel(clock=clock)
    model.declare(
        [
            StepSpec(id="check", title="Check for updates"),
            StepSpec(id="check:sase", title="sase", parent_id="check"),
        ]
    )
    rows = model.snapshot()
    assert [row.id for row in rows] == ["check"]
    assert rows[0].status == "pending"
    assert [child.id for child in rows[0].children] == ["check:sase"]

    clock.advance(2.0)
    model.start("check:sase", detail="fetching…")
    model.output("check:sase", "stdout", "From origin")
    clock.advance(1.5)
    model.finish("check:sase", "done", detail="behind 4 · origin/master")

    child = model.snapshot()[0].children[0]
    assert child.status == "done"
    assert child.detail == "behind 4 · origin/master"
    assert child.started_at == pytest.approx(102.0)
    assert child.ended_at == pytest.approx(103.5)
    assert child.tail == ("From origin",)


def test_start_undeclared_id_auto_appends() -> None:
    model = TimelineModel(clock=FakeClock())
    model.start("inspect", detail="uv tool · 5 editable")
    rows = model.snapshot()
    assert [row.id for row in rows] == ["inspect"]
    assert rows[0].title == "inspect"
    assert rows[0].status == "running"


def test_finish_parent_skips_running_children_only() -> None:
    model = TimelineModel(clock=FakeClock())
    model.declare(
        [
            StepSpec(id="merge", title="Fast-forward checkouts"),
            StepSpec(id="merge:a", title="a", parent_id="merge"),
            StepSpec(id="merge:b", title="b", parent_id="merge"),
            StepSpec(id="merge:c", title="c", parent_id="merge"),
        ]
    )
    model.start("merge")
    model.start("merge:a")
    model.finish("merge:a", "done", detail="ok")
    model.start("merge:b")
    model.finish("merge", "failed", detail="conflict")

    parent = model.snapshot()[0]
    by_id = {child.id: child for child in parent.children}
    assert by_id["merge:a"].status == "done"
    assert by_id["merge:b"].status == "skipped"
    assert by_id["merge:c"].status == "pending"


def test_finish_first_write_wins() -> None:
    model = TimelineModel(clock=FakeClock())
    model.start("build")
    model.finish("build", "failed", detail="link error")
    model.finish("build", "done", detail="ok")
    assert model.snapshot()[0].status == "failed"
    assert model.snapshot()[0].detail == "link error"


def test_finalize_marks_leftovers() -> None:
    clock = FakeClock()
    model = TimelineModel(clock=clock)
    model.declare([StepSpec(id="a", title="A"), StepSpec(id="b", title="B")])
    model.start("a")
    clock.advance(1.0)
    model.finalize()
    statuses = {row.id: row.status for row in model.snapshot()}
    assert statuses == {"a": "skipped", "b": "skipped"}
    assert model.snapshot()[0].ended_at == pytest.approx(101.0)


def test_tail_bounded_at_200_lines() -> None:
    model = TimelineModel(clock=FakeClock())
    model.start("build")
    for i in range(250):
        model.output("build", "stdout", f"line {i}")
    assert len(model.snapshot()[0].tail) == 200
    assert model.snapshot()[0].tail[0] == "line 50"


def test_step_context_manager_marks_done() -> None:
    model = TimelineModel(clock=FakeClock())
    with step(model, "check", "Check for updates"):
        pass
    assert model.snapshot()[0].status == "done"


def test_step_context_manager_marks_failed_and_reraises() -> None:
    model = TimelineModel(clock=FakeClock())
    with pytest.raises(RuntimeError, match="boom"):
        with step(model, "build", "Rebuild"):
            raise RuntimeError("boom")
    assert model.snapshot()[0].status == "failed"


def test_step_context_manager_marks_interrupted() -> None:
    model = TimelineModel(clock=FakeClock())
    with pytest.raises(KeyboardInterrupt):
        with step(model, "build", "Rebuild"):
            raise KeyboardInterrupt
    assert model.snapshot()[0].status == "interrupted"


def test_step_context_manager_keeps_explicit_detail() -> None:
    model = TimelineModel(clock=FakeClock())
    with step(model, "build", "Rebuild"):
        model.finish("build", "warned", detail="cache miss · stamp-missing")
    row = model.snapshot()[0]
    assert row.status == "warned"
    assert row.detail == "cache miss · stamp-missing"


def test_output_sink_binds_step() -> None:
    model = TimelineModel(clock=FakeClock())
    model.start("build")
    sink = model.output_sink("build")
    sink("stderr", "Compiling foo")
    assert model.snapshot()[0].tail == ("Compiling foo",)


def test_null_progress_discards_everything() -> None:
    NULL_PROGRESS.declare([StepSpec(id="a", title="A")])
    NULL_PROGRESS.start("a")
    NULL_PROGRESS.output("a", "stdout", "x")
    NULL_PROGRESS.command("a", ["git", "fetch"], cwd="/tmp")
    NULL_PROGRESS.finish("a", "done")
    NULL_PROGRESS.finalize()
    assert NULL_PROGRESS.output_sink("a")("stdout", "x") is None


def test_thread_safety_smoke() -> None:
    clock = FakeClock()
    model = TimelineModel(clock=clock)
    model.start("build")
    errors: list[BaseException] = []

    def pump(worker: int) -> None:
        try:
            for i in range(100):
                model.output("build", "stdout", f"w{worker}-{i}")
        except BaseException as exc:  # noqa: BLE001 - collected, then asserted
            errors.append(exc)

    threads = [threading.Thread(target=pump, args=(w,)) for w in range(4)]
    for thread in threads:
        thread.start()
    model.finish("build", "done", detail="ok")
    for thread in threads:
        thread.join(timeout=10.0)
    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    row = model.snapshot()[0]
    assert row.status == "done"
    assert len(row.tail) == 200
