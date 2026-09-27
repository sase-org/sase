"""Coverage for the step channel and bounded live sink (sase-1b2.6)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sase.finalizers import bounded_subprocess as bounded
from sase.finalizers.bounded_subprocess import (
    cleanup_live_sink,
    run_bounded_subprocess,
)
from sase.finalizers.commit_repair_stitch import record_stitch_artifacts
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.executor_support import (
    op_channel_paths,
    op_progress_tick,
    retain_live_sink,
    sanitized_env,
)
from sase.finalizers.status_summary import FinalizerStatusTracker
from sase.finalizers.steps import (
    STEPS_ENV_VAR,
    STEPS_FILE_CEILING_BYTES,
    emit_step,
    latest_step_summary,
    make_progress_tick,
    read_steps_tail,
)
from sase.output import print_status


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_emit_step_noop_without_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(STEPS_ENV_VAR, raising=False)
    emit_step("hello", state="start")
    emit_step("hello", state="warn", detail="d")


def test_emit_step_record_shape_and_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = tmp_path / "attempt-1.run.steps.jsonl"
    monkeypatch.setenv(STEPS_ENV_VAR, str(steps))
    emit_step("x" * 200, state="start", detail="y" * 900)
    emit_step("bad-state", state="bogus")
    emit_step("   ", state="start")
    records = _read_jsonl(steps)
    assert len(records) == 1
    assert records[0]["v"] == 1
    assert records[0]["state"] == "start"
    assert len(records[0]["step"]) == 120
    assert len(records[0]["detail"]) == 500
    assert isinstance(records[0]["t"], float)


def test_emit_step_stops_at_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = tmp_path / "steps.jsonl"
    steps.write_text("p" * (STEPS_FILE_CEILING_BYTES - 10), encoding="utf-8")
    monkeypatch.setenv(STEPS_ENV_VAR, str(steps))
    emit_step("one more step that would cross the ceiling", state="start")
    assert steps.stat().st_size == STEPS_FILE_CEILING_BYTES - 10


def test_warning_print_status_feeds_step_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    steps = tmp_path / "attempt-1.run.steps.jsonl"
    monkeypatch.setenv(STEPS_ENV_VAR, str(steps))
    print_status("something looks off", "warning")
    print_status("just info", "info")
    capsys.readouterr()
    records = _read_jsonl(steps)
    assert len(records) == 1
    assert records[0]["state"] == "warn"
    assert records[0]["step"] == "something looks off"


def test_warning_print_status_quiet_without_channel(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv(STEPS_ENV_VAR, raising=False)
    print_status("something looks off", "warning")
    capsys.readouterr()


def test_sanitized_env_injects_steps_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STEPS_ENV_VAR, "/tmp/parent-channel.jsonl")
    env = sanitized_env([])
    assert STEPS_ENV_VAR not in env
    env = sanitized_env([], extra={STEPS_ENV_VAR: "/tmp/op-channel.jsonl"})
    assert env[STEPS_ENV_VAR] == "/tmp/op-channel.jsonl"


def test_op_channel_paths_prefix(tmp_path: Path) -> None:
    context = FinalizerExecutionContext(
        artifacts_dir=str(tmp_path / "artifacts"), plan_digest=None
    )
    steps_path, live_path = op_channel_paths(context, "check", "attempt-1.run")
    assert steps_path is not None and steps_path.endswith("attempt-1.run.steps.jsonl")
    assert live_path is not None and live_path.endswith("attempt-1.run.live")
    assert Path(steps_path).parent.is_dir()


def test_op_channel_paths_without_artifacts() -> None:
    context = FinalizerExecutionContext(artifacts_dir=None, plan_digest=None)
    assert op_channel_paths(context, "check", "attempt-1.run") == (None, None)
    assert op_progress_tick(context, "check", None) is None


def test_latest_step_summary_counts_warns(tmp_path: Path) -> None:
    steps = tmp_path / "steps.jsonl"
    rows = [
        {"v": 1, "t": 1.0, "step": "first", "state": "start"},
        {"v": 1, "t": 2.0, "step": "wobble", "state": "warn"},
        {"v": 1, "t": 3.0, "step": "second", "state": "ok"},
        {"v": 1, "t": 4.0, "step": "wobble again", "state": "warn"},
    ]
    steps.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    latest, warnings = latest_step_summary(steps)
    assert latest == "wobble again"
    assert warnings == 2
    assert latest_step_summary(tmp_path / "missing.jsonl") == (None, 0)


def test_read_steps_tail_skips_garbage(tmp_path: Path) -> None:
    steps = tmp_path / "steps.jsonl"
    steps.write_text(
        "\nnot json\n" + json.dumps({"v": 1, "step": "kept", "state": "ok"}) + "\n",
        encoding="utf-8",
    )
    assert read_steps_tail(steps) == [{"v": 1, "step": "kept", "state": "ok"}]


def test_progress_tick_refreshes_tracker(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    steps = artifacts / "finalizers" / "check" / "attempt-1.run.steps.jsonl"
    steps.parent.mkdir(parents=True)
    steps.write_text(
        json.dumps({"v": 1, "t": 1.0, "step": "before hook: just fix", "state": "ok"})
        + "\n"
        + json.dumps({"v": 1, "t": 2.0, "step": "odd output", "state": "warn"})
        + "\n",
        encoding="utf-8",
    )
    tracker = FinalizerStatusTracker(str(artifacts))
    tracker.seal_planned(plan_digest="abc", instance_ids=["check"])
    make_progress_tick(tracker, "check", steps)()
    instances = {entry["id"]: entry for entry in tracker.payload()["instances"]}
    assert instances["check"]["step"] == "odd output"
    assert instances["check"]["warnings"] == 1


def test_progress_tick_without_steps_is_quiet(tmp_path: Path) -> None:
    tracker = FinalizerStatusTracker(str(tmp_path / "artifacts"))
    tracker.seal_planned(plan_digest="abc", instance_ids=["check"])
    make_progress_tick(tracker, "check", tmp_path / "missing.jsonl")()


def test_subprocess_tick_sees_slow_steps(tmp_path: Path) -> None:
    steps = tmp_path / "attempt-1.run.steps.jsonl"
    child = (
        "import json, os, time; "
        "p = os.environ['STEPS_OUT']; "
        "open(p, 'w').write(json.dumps({'v': 1, 't': 1.0, 'step': 'one', 'state': 'start'}) + chr(10)); "
        "time.sleep(0.6); "
        "open(p, 'a').write(json.dumps({'v': 1, 't': 2.0, 'step': 'two', 'state': 'ok'}) + chr(10)); "
        "time.sleep(0.6)"
    )
    seen: list[tuple[str | None, int]] = []
    env = dict(os.environ)
    env["STEPS_OUT"] = str(steps)

    def _tick() -> None:
        seen.append(latest_step_summary(steps))

    completed = run_bounded_subprocess(
        [sys.executable, "-c", child],
        cwd=str(tmp_path),
        env=env,
        input_bytes=None,
        timeout=30,
        progress_tick=_tick,
        progress_tick_interval=0.2,
    )
    assert completed.returncode == 0
    assert seen, "expected at least one progress tick while the child ran"
    assert seen[-1][0] == "two"


def test_progress_tick_error_is_swallowed(tmp_path: Path) -> None:
    def _boom() -> None:
        raise RuntimeError("tick blew up")

    completed = run_bounded_subprocess(
        [sys.executable, "-c", "pass"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=30,
        progress_tick=_boom,
        progress_tick_interval=0.01,
    )
    assert completed.returncode == 0


def test_live_sink_captures_both_streams(tmp_path: Path) -> None:
    live = tmp_path / "attempt-1.run.live"
    completed = run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('out-line\\n'); sys.stderr.write('err-line\\n')",
        ],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=30,
        live_path=live,
    )
    assert completed.returncode == 0
    body = live.read_bytes()
    assert b"out-line" in body
    assert b"err-line" in body


def test_plugin_live_sink_tees_stderr_only(tmp_path: Path) -> None:
    live = tmp_path / "attempt-1.execute.live"
    completed = run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            "import json, sys; "
            "sys.stdout.write(json.dumps({'status': 'ok'}) + '\\n'); "
            "sys.stderr.write('worker note\\n')",
        ],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=30,
        live_path=live,
        live_streams={"stderr"},
    )
    assert completed.returncode == 0
    body = live.read_bytes()
    assert b"worker note" in body
    assert b"status" not in body


def test_live_sink_rotation_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bounded, "LIVE_SINK_ROTATE_BYTES", 1024)
    live = tmp_path / "attempt-1.run.live"
    completed = run_bounded_subprocess(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000)"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=30,
        live_path=live,
    )
    assert completed.returncode == 0
    assert (tmp_path / "attempt-1.run.live.1").is_file()
    cleanup_live_sink(live)
    assert not live.exists()
    assert not (tmp_path / "attempt-1.run.live.1").exists()
    cleanup_live_sink(None)


def test_live_sink_failure_swallowed(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    completed = run_bounded_subprocess(
        [sys.executable, "-c", "print('fine')"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=30,
        live_path=blocker / "x.live",
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == b"fine"


def test_timeout_kill_leaves_live(tmp_path: Path) -> None:
    live = tmp_path / "attempt-1.run.live"
    completed = run_bounded_subprocess(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stdout.write('started\\n'); "
            "sys.stdout.flush(); time.sleep(60)",
        ],
        cwd=str(tmp_path),
        env=dict(os.environ),
        input_bytes=None,
        timeout=2,
        live_path=live,
    )
    assert completed.timed_out
    assert retain_live_sink(completed)
    assert live.is_file()
    assert b"started" in live.read_bytes()


def test_retain_live_sink_outcomes() -> None:
    from sase.finalizers.bounded_subprocess import BoundedCompletedProcess

    clean = BoundedCompletedProcess(
        returncode=0, stdout=b"", stderr=b"", duration_seconds=1.0
    )
    killed = BoundedCompletedProcess(
        returncode=-9, stdout=b"", stderr=b"", duration_seconds=1.0
    )
    assert not retain_live_sink(clean)
    assert retain_live_sink(killed)


def test_record_stitch_artifacts_references_present_channels(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    context = FinalizerExecutionContext(artifacts_dir=str(artifacts), plan_digest=None)
    instance_dir = artifacts / "finalizers" / "commit"
    instance_dir.mkdir(parents=True)
    (instance_dir / "attempt-1.main.steps.jsonl").write_text(
        json.dumps({"v": 1, "t": 1.0, "step": "create_commit", "state": "ok"}) + "\n",
        encoding="utf-8",
    )
    live = instance_dir / "attempt-1.main.live"
    live.write_bytes(b"tail bytes")
    result = StitchCommandResult(
        returncode=0, stdout="ok\n", stderr="", duration_seconds=1.0
    )
    record_stitch_artifacts(context, "commit", 1, result, label="main")
    outcome = json.loads(
        (instance_dir / "attempt-1.main.outcome.json").read_text(encoding="utf-8")
    )
    assert outcome["steps"] == "attempt-1.main.steps.jsonl"
    assert "live" not in outcome["logs"]
    assert not live.exists()


def test_record_stitch_artifacts_retains_live_on_timeout(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    context = FinalizerExecutionContext(artifacts_dir=str(artifacts), plan_digest=None)
    instance_dir = artifacts / "finalizers" / "commit"
    instance_dir.mkdir(parents=True)
    live = instance_dir / "attempt-1.main.live"
    live.write_bytes(b"tail bytes")
    result = StitchCommandResult(
        returncode=-9,
        stdout="partial\n",
        stderr="",
        duration_seconds=2.0,
        timed_out=True,
    )
    record_stitch_artifacts(context, "commit", 1, result, label="main")
    outcome = json.loads(
        (instance_dir / "attempt-1.main.outcome.json").read_text(encoding="utf-8")
    )
    assert outcome["logs"]["live"] == "attempt-1.main.live"
    assert "steps" not in outcome
    assert live.is_file()


def test_stitch_emits_steps_only_when_channel_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.workflows.commit.command_hooks import _emit_hook_step
    from sase.workflows.commit.workflow import _emit_stitch_step
    from sase.workflows.commit.workflow_publication import _emit_publication_step

    monkeypatch.delenv(STEPS_ENV_VAR, raising=False)
    _emit_hook_step("before", "just fix", state="start", detail="just fix")
    _emit_stitch_step("create_commit", state="start")
    _emit_publication_step(state="start")

    steps = tmp_path / "attempt-1.main.steps.jsonl"
    monkeypatch.setenv(STEPS_ENV_VAR, str(steps))
    _emit_hook_step("before", "just fix", state="start", detail="just fix")
    _emit_hook_step("before", "just fix", state="ok")
    _emit_stitch_step("create_commit", state="start")
    _emit_stitch_step("create_commit", state="ok")
    _emit_stitch_step("push", state="ok")
    _emit_publication_step(state="start")
    _emit_publication_step(state="ok")
    records = _read_jsonl(steps)
    assert [(row["step"], row["state"]) for row in records] == [
        ("before hook: just fix", "start"),
        ("before hook: just fix", "ok"),
        ("create_commit", "start"),
        ("create_commit", "ok"),
        ("push", "ok"),
        ("publication", "start"),
        ("publication", "ok"),
    ]


def test_slow_step_file_tail_bounded(tmp_path: Path) -> None:
    steps = tmp_path / "steps.jsonl"
    steps.write_bytes(b"x" * 100 + b"\n" + b'{"v": 1, "step": "last", "state": "ok"}\n')
    assert read_steps_tail(steps, max_bytes=60) == [
        {"v": 1, "step": "last", "state": "ok"}
    ]
