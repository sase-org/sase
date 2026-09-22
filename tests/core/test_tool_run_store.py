from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_list,
    tool_run_observe,
    tool_run_reconcile,
    tool_run_show,
    tool_run_store_stats,
    tool_run_unknown_evidence,
    tool_run_wire_schema_version,
    tools_dir,
)


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_begin"),
    reason="tool_run bindings are not in this wheel",
)


def test_tools_dir_is_under_sase_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    assert tools_dir() == tmp_path / "home" / "tools"


def test_adapter_round_trip_and_unknown_evidence(tmp_path: Path) -> None:
    assert tool_run_wire_schema_version() == 1
    unknown = tool_run_unknown_evidence("PSI unavailable")
    assert unknown["completeness"]["complete"] is False
    store = str(tmp_path / "tools" / "runs.sqlite")
    started = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["just", "check"],
                "description": "check",
                "stages": "run_silent",
                "inputs": ["Justfile"],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["just", "check"],
            "project": "sase",
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store,
    )
    assert started["run"]["state"] == "running"
    run_id = started["run"]["run_id"]
    finished = tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 3,
            "duration_ms": 4,
            "now_ts": 14,
        },
        store_path=store,
    )
    assert finished["run"]["state"] == "failed"
    assert finished["run"]["exit_code"] == 3
    listed = tool_run_list({"schema_version": 1, "limit": 10}, store_path=store)
    assert listed["runs"][0]["run_id"] == run_id
    shown = tool_run_show(run_id, store_path=store)
    assert shown["run"]["run_id"] == run_id
    stats = tool_run_store_stats(store_path=store)
    assert stats["run_count"] == 1
    assert shown["run"]["logs"]["has_private_argv"] is False
    assert "private_argv" not in shown["run"]


def test_observe_persists_child_facts_and_reconcile_authorizes_reap(
    tmp_path: Path,
) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    started = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["just", "check"],
                "description": "check",
                "stages": "run_silent",
                "inputs": ["Justfile"],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["just", "check"],
            "project": "sase",
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store,
    )
    run_id = started["run"]["run_id"]
    observed = tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "child_pid": 4242,
            "child_pgid": 4242,
            "child_process_start_identity": "boot-1:12345",
        },
        store_path=store,
    )
    assert observed["replayed"] is False
    assert observed["run"]["child_pgid"] == 4242
    assert observed["run"]["child_process_start_identity"] == "boot-1:12345"
    replayed = tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "child_pid": 4242,
            "child_pgid": 4242,
            "child_process_start_identity": "boot-1:12345",
        },
        store_path=store,
    )
    assert replayed["replayed"] is True

    reconciled = tool_run_reconcile(
        {
            "schema_version": 1,
            "facts": [
                {
                    "run_id": run_id,
                    "wrapper_pid": 4242,
                    "boot_id": "boot-other",
                    "process_start_identity": "start-1",
                    "observation": "dead",
                    "reason": "runner gone",
                }
            ],
            "now_ts": 11,
        },
        store_path=store,
    )
    assert reconciled["marked_lost"] == [run_id]
    assert reconciled["reap_candidates"] == [
        {
            "run_id": run_id,
            "pgid": 4242,
            "child_process_start_identity": "boot-1:12345",
        }
    ]
