"""Retention pruning and runtime-dir sweep/delete coverage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.procs import Proc, append_proc, proc_log_path, prune_procs
from sase.procs.runtime import (
    delete_proc_runtime_dirs,
    sweep_orphan_proc_runtime_dirs,
)

from tests._procs_facade_helpers import (
    _aged_runtime_dir,
    _proc,
    _proc_runtime_dir_for_store,
)


def test_retention_and_pruning_delete_corresponding_logs_and_runtime_dirs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    store = tmp_path / "procs.jsonl"
    first = _proc(
        "0123456789ab",
        status="success",
        created_at="2026-07-25T12:00:00Z",
    )
    second = _proc(
        "0123456789ac",
        status="success",
        created_at="2026-07-25T12:01:00Z",
    )
    artifact_owned = _proc(
        "0123456789ad",
        status="success",
        created_at="2026-07-25T12:00:30Z",
    )
    artifact_owned = Proc.from_dict(
        {**artifact_owned.to_dict(), "log_owner": "artifact"}
    )
    running = _proc(
        "0123456789ae",
        status="running",
        created_at="2026-07-25T11:00:00Z",
    )
    for proc in (first, artifact_owned, second, running):
        log = proc_log_path(proc.proc_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(proc.proc_id, encoding="utf-8")
        runtime_dir = _proc_runtime_dir_for_store(store, proc.proc_id)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "request.json").write_text("{}", encoding="utf-8")
        append_proc(proc, path=store, history_limit=10)
    orphan_dir = _proc_runtime_dir_for_store(store, "0123456789af")
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "request.json").write_text("{}", encoding="utf-8")

    outcome = prune_procs(path=store, history_limit=1)

    assert outcome.pruned_proc_ids == [first.proc_id, artifact_owned.proc_id]
    assert outcome.pruned_log_proc_ids == [first.proc_id]
    assert outcome.log_retention is not None
    assert outcome.log_retention.removed == 1
    assert outcome.runtime_retention is not None
    assert outcome.runtime_retention.removed == 2
    assert outcome.state_retention is not None
    assert outcome.state_retention.failed is False
    assert [proc.proc_id for proc in outcome.snapshot.procs] == [
        second.proc_id,
        running.proc_id,
    ]
    assert not proc_log_path(first.proc_id).exists()
    assert proc_log_path(artifact_owned.proc_id).exists()
    assert proc_log_path(second.proc_id).exists()
    assert proc_log_path(running.proc_id).exists()
    assert not _proc_runtime_dir_for_store(store, first.proc_id).exists()
    assert not _proc_runtime_dir_for_store(store, artifact_owned.proc_id).exists()
    assert orphan_dir.exists()
    assert _proc_runtime_dir_for_store(store, second.proc_id).exists()
    assert _proc_runtime_dir_for_store(store, running.proc_id).exists()


def test_proc_runtime_orphan_sweep_is_bounded_and_validated(
    tmp_path: Path,
) -> None:
    now = 1_800_000_000.0
    day = 24 * 3600.0
    store = tmp_path / "procs.jsonl"
    runtime = store.parent / "runtime"
    store.write_text("", encoding="utf-8")
    active = _proc("0123456789ab", status="running")
    append_proc(active, path=store)
    _aged_runtime_dir(store, active.proc_id, now=now, age=2 * day)
    fresh = "0123456789ac"
    _aged_runtime_dir(store, fresh, now=now, age=0.5 * day)
    invalid = runtime / "not-a-proc-0"
    invalid.mkdir(parents=True)

    for index in range(4000):
        _aged_runtime_dir(store, f"{index:012x}", now=now, age=2 * day)

    symlink_id = "00000000000z"
    symlink_target = tmp_path / "outside"
    symlink_target.mkdir()
    if hasattr(os, "symlink"):
        os.symlink(symlink_target, runtime / symlink_id)

    first = sweep_orphan_proc_runtime_dirs(
        runtime_root=runtime,
        store_path=store,
        now=now,
        orphan_horizon_seconds=day,
        max_orphan_removals=2000,
    )
    second = sweep_orphan_proc_runtime_dirs(
        runtime_root=runtime,
        store_path=store,
        now=now,
        orphan_horizon_seconds=day,
        max_orphan_removals=2000,
    )

    assert first.removed == 2000
    assert first.capped
    assert second.removed == 2000
    assert not second.capped
    assert _proc_runtime_dir_for_store(store, active.proc_id).exists()
    assert _proc_runtime_dir_for_store(store, fresh).exists()
    assert invalid.exists()
    if hasattr(os, "symlink"):
        assert (runtime / symlink_id).exists()


def test_delete_pruned_runtime_revalidates_against_new_reservation(
    tmp_path: Path,
) -> None:
    store = tmp_path / "procs.jsonl"
    reused = "0123456789ab"
    removed = "0123456789ac"
    append_proc(_proc(reused, status="running"), path=store)
    _aged_runtime_dir(store, reused, now=1_800_000_000.0, age=0)
    _aged_runtime_dir(store, removed, now=1_800_000_000.0, age=0)

    result = delete_proc_runtime_dirs(
        [reused, removed],
        runtime_root=store.parent / "runtime",
        store_path=store,
    )

    assert result.removed == 1
    assert _proc_runtime_dir_for_store(store, reused).exists()
    assert not _proc_runtime_dir_for_store(store, removed).exists()


def test_proc_runtime_sweep_failed_store_read_preserves_data(
    tmp_path: Path,
) -> None:
    store = tmp_path / "procs.jsonl"
    store.mkdir()
    runtime_dir = _aged_runtime_dir(
        store, "0123456789ab", now=1_800_000_000.0, age=2 * 24 * 3600
    )

    with pytest.raises(ValueError):
        sweep_orphan_proc_runtime_dirs(
            runtime_root=store.parent / "runtime",
            store_path=store,
            now=1_800_000_000.0,
            orphan_horizon_seconds=24 * 3600,
        )

    assert runtime_dir.exists()
