from __future__ import annotations

import time
from pathlib import Path

from sase.config.tools import get_tool_runs_config
from sase.core.disk_footprint_reap_tool_run import tool_run_reap_step
from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_retention_preview,
)


def test_retention_preview_selects_settled_log_files(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    store = str(home / "tools" / "runs.sqlite")
    stdout = home / "tools" / "logs" / "run-old" / "stdout.log"
    stdout.parent.mkdir(parents=True)
    stdout.write_bytes(b"hello-log")
    started = tool_run_begin(
        {
            "schema_version": 1,
            "run_id": "run-old",
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["true"],
                "description": "",
                "stages": "none",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "log_stdout_path": str(stdout),
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store,
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": started["run"]["run_id"],
            "state": "succeeded",
            "exit_code": 0,
            "duration_ms": 1,
            "now_ts": 11,
        },
        store_path=store,
    )
    policy = {"schema_version": 1, **get_tool_runs_config()}
    preview = tool_run_retention_preview(
        {"schema_version": 1, "policy": policy, "now_ts": 11 + 20 * 86400},
        store_path=store,
    )
    paths = [
        candidate.get("path")
        for candidate in preview.get("file_candidates") or ()
        if isinstance(candidate, dict)
    ]
    assert str(stdout) in paths
    assert preview.get("protected_unsettled") == 0


def test_reap_reclaims_quarantined_store_at_log_horizon(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    store = str(home / "tools" / "runs.sqlite")
    tool_run_begin(
        {
            "schema_version": 1,
            "run_id": "run-live",
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["true"],
                "description": "",
                "stages": "none",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store,
    )
    # Nanos of 1 quarantines at the epoch: older than any horizon.
    old = home / "tools" / "runs.sqlite.corrupt-1"
    old.write_bytes(b"q" * 64)
    # Quarantined "now": younger than the default 14-day log horizon.
    young_nanos = int(time.time() * 1_000_000_000)
    young = home / "tools" / f"runs.sqlite.corrupt-{young_nanos}"
    young.write_bytes(b"y" * 32)

    preview = tool_run_reap_step(apply=False)
    candidates = (preview.details or {}).get("file_candidates") or ()
    paths = [
        candidate.get("path") for candidate in candidates if isinstance(candidate, dict)
    ]
    assert str(old) in paths
    assert str(young) not in paths
    kinds = {
        candidate.get("path"): candidate.get("kind")
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    assert kinds[str(old)] == "quarantined_store"

    applied = tool_run_reap_step(apply=True)
    assert not old.exists()
    assert young.exists()
    assert Path(store).exists()
    assert applied.reclaimed_bytes == 64
    assert (applied.details or {}).get("removed_files") == 1


def test_reap_apply_deletes_selected_tool_run_logs(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    log = home / "tools" / "logs" / "run-1" / "stdout.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"abcdef")
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_wire_schema_version",
        lambda: 1,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_store_stats",
        lambda store_path=None: {"exists": True, "run_count": 1},
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap_tool_run.tool_run_retention_apply",
        lambda request, store_path=None: {
            "schema_version": 1,
            "dry_run": False,
            "summary_rows": 0,
            "detail_rows": 0,
            "file_candidates": [
                {
                    "kind": "stdout",
                    "run_id": "run-1",
                    "path": str(log),
                    "protected": False,
                    "reason": "log_days",
                }
            ],
            "protected_unsettled": 0,
            "diagnostics": [],
        },
    )
    step = tool_run_reap_step(apply=True)
    assert not log.exists()
    assert step.reclaimed_bytes == 6
