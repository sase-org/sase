"""Retention selection for visual screenshot maintenance run directories."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    encoding_pair,
    init_repo,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_SUCCESS,
    KEEP_RECENT_COUNT,
    main,
    prune_old_runs,
    select_runs_to_prune,
)


DAY = 24 * 60 * 60


def _make_run(
    repo: Path,
    name: str,
    *,
    age_seconds: float,
    now: float,
    journal: object | None = None,
    raw_journal: bytes | None = None,
    fresh_descendant: bool = False,
) -> Path:
    run_dir = repo / ".pytest_cache" / "sase-visual" / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": name}) + "\n", encoding="utf-8"
    )
    if journal is not None:
        (run_dir / "apply-journal.json").write_text(
            json.dumps(journal) + "\n", encoding="utf-8"
        )
    if raw_journal is not None:
        (run_dir / "apply-journal.json").write_bytes(raw_journal)
    if fresh_descendant:
        (run_dir / "capture.log").write_text("fresh\n", encoding="utf-8")
    old = now - age_seconds
    for path in sorted(run_dir.rglob("*")):
        if not path.is_symlink():
            os.utime(path, (old, old))
    os.utime(run_dir, (old, old))
    if fresh_descendant:
        fresh = run_dir / "capture.log"
        os.utime(fresh, (now, now))
    return run_dir


def test_prune_keeps_protected_runs_and_drops_old_fillers(tmp_path: Path) -> None:
    now = time.time()
    repo = tmp_path
    current = _make_run(repo, "current-run", age_seconds=0, now=now)
    os.utime(current, (now, now))
    for index in range(11):
        _make_run(repo, f"filler-{index:02d}", age_seconds=2 * DAY + index, now=now)
    _make_run(repo, "old-latest", age_seconds=3 * DAY, now=now)
    (repo / ".pytest_cache" / "sase-visual" / "latest-report.json").write_text(
        json.dumps({"run_id": "old-latest", "manifest": "runs/old-latest/x"}) + "\n",
        encoding="utf-8",
    )
    _make_run(
        repo,
        "old-unfinished",
        age_seconds=3 * DAY + 1,
        now=now,
        journal={"kind": "visual_maintenance_journal", "status": "planned"},
    )
    _make_run(
        repo,
        "old-applying",
        age_seconds=3 * DAY + 2,
        now=now,
        journal={"kind": "visual_maintenance_journal", "status": "applying"},
    )
    _make_run(
        repo,
        "old-unreadable",
        age_seconds=3 * DAY + 3,
        now=now,
        raw_journal=b"\x00\x01 not json",
    )
    _make_run(
        repo,
        "old-recent-touch",
        age_seconds=3 * DAY + 4,
        now=now,
        fresh_descendant=True,
    )

    pruned = prune_old_runs(repo, current_run_id="current-run", now=now)

    runs_dir = repo / ".pytest_cache" / "sase-visual" / "runs"
    survivors = {entry.name for entry in runs_dir.iterdir()}
    for name in (
        "current-run",
        "old-latest",
        "old-unfinished",
        "old-applying",
        "old-unreadable",
        "old-recent-touch",
    ):
        assert name in survivors, name
    assert sorted(pruned) == ["filler-09", "filler-10"]
    assert len(survivors) == KEEP_RECENT_COUNT + 5


def test_prune_keeps_ten_most_recent(tmp_path: Path) -> None:
    now = time.time()
    for index in range(12):
        _make_run(tmp_path, f"run-{index:02d}", age_seconds=2 * DAY + index, now=now)

    pruned = prune_old_runs(tmp_path, now=now)

    assert sorted(pruned) == ["run-10", "run-11"]
    runs_dir = tmp_path / ".pytest_cache" / "sase-visual" / "runs"
    assert len(list(runs_dir.iterdir())) == 10


def test_prune_never_follows_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("do not touch\n", encoding="utf-8")
    runs_dir = tmp_path / ".pytest_cache" / "sase-visual" / "runs"
    runs_dir.mkdir(parents=True)
    link = runs_dir / "sneaky-link"
    link.symlink_to(outside, target_is_directory=True)
    now = time.time()
    for index in range(10):
        _make_run(tmp_path, f"filler-{index:02d}", age_seconds=2 * DAY, now=now)
    victim = _make_run(tmp_path, "old-run", age_seconds=3 * DAY, now=now)
    (victim / "inner-link").symlink_to(secret)
    old = now - 3 * DAY
    os.utime(victim, (old, old))

    pruned = prune_old_runs(tmp_path, now=now)

    assert pruned == ("old-run",)
    assert link.is_symlink()
    assert secret.read_text(encoding="utf-8") == "do not touch\n"


def test_prune_without_runs_dir_is_empty(tmp_path: Path) -> None:
    assert prune_old_runs(tmp_path) == ()
    assert select_runs_to_prune(tmp_path) == []


def test_maintenance_run_prunes_stale_run_dir(tmp_path: Path) -> None:
    init_repo(tmp_path)
    first, _second = encoding_pair()
    write_golden(tmp_path, "ace", "shot.png", first)
    write_golden(tmp_path, "pager", "shot.png", first)
    commit_all(tmp_path)
    now = time.time()
    stale = _make_run(tmp_path, "stale-run", age_seconds=4 * DAY, now=now)
    assert stale.is_dir()
    for index in range(10):
        _make_run(tmp_path, f"filler-{index:02d}", age_seconds=3 * DAY + index, now=now)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", first),
            ScriptedCapture(PAGER_NODE, "shot", "pager", first),
        ],
        repo_root=tmp_path,
    )

    assert main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={}) == (
        EXIT_SUCCESS
    )

    assert not stale.exists()
    runs_dir = tmp_path / ".pytest_cache" / "sase-visual" / "runs"
    assert any(entry.is_dir() for entry in runs_dir.iterdir())
