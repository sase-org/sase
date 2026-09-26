from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_claim,
    tool_run_failures,
    tool_run_finish,
    tool_run_list,
    tool_run_observe,
    tool_run_reconcile,
    tool_run_request_stop,
    tool_run_show,
    tool_run_store_stats,
    tool_run_triage_classify,
    tool_run_triage_extract,
    tool_run_triage_record,
    tool_run_triage_settle,
    tool_run_triage_show,
    tool_run_triage_verdict,
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


@pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_claim"),
    reason="tool_run_claim is not in this wheel",
)
def test_handoff_reserve_claim_stop_finish_reconcile(tmp_path: Path) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    definition = {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "check",
        "stages": "run_silent",
        "inputs": ["Justfile"],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    started = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["just", "check"],
            "project": "sase",
            "now_ts": 10,
            "commit_running": False,
            "launch_mode": "handoff",
            "owner_kind": "proc",
            "owner_id": "proc-1",
            "owner_log_path": "logs/proc-1.log",
            "wrapper_pid": 111,
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:111",
            "launch": {
                "argv": ["just", "check"],
                "tool_name": "check",
                "extra_args": [],
                "display_argv": ["just", "check"],
                "definition": definition,
                "adhoc": False,
            },
        },
        store_path=store,
    )
    assert started["run"]["state"] == "created"
    run_id = started["run"]["run_id"]
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": "proc-1",
            "wrapper_pid": 4242,
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:4242",
            "now_ts": 11,
        },
        store_path=store,
    )
    assert claimed["outcome"] == "claimed"
    assert claimed["launch"]["argv"] == ["just", "check"]
    stopped = tool_run_request_stop(
        {
            "schema_version": 1,
            "run_id": run_id,
            "requested_by": "agent-1",
            "now_ts": 12,
        },
        store_path=store,
    )
    assert stopped["outcome"] == "recorded"
    finished = tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "signaled",
            "terminal_cause": "stop_requested",
            "diagnostics": ["stopped by request"],
            "duration_ms": 5,
            "now_ts": 13,
        },
        store_path=store,
    )
    assert finished["run"]["terminal_cause"] == "stop_requested"
    assert "stopped by request" in finished["run"]["diagnostics"]
    reconciled = tool_run_reconcile(
        {
            "schema_version": 1,
            "facts": [
                {
                    "run_id": run_id,
                    "wrapper_pid": 4242,
                    "boot_id": "boot-1",
                    "process_start_identity": "boot-1:4242",
                    "observation": "dead",
                    "owner": {
                        "kind": "proc",
                        "id": "proc-1",
                        "state": "terminal",
                        "exit_code": 0,
                        "termination_reason": "success",
                    },
                }
            ],
            "now_ts": 14,
        },
        store_path=store,
    )
    assert reconciled["persisted"] is True
    assert reconciled["settled"] == []


@pytest.mark.skipif(
    not all(
        hasattr(importlib.import_module("sase_core_rs"), name)
        for name in (
            "tool_run_failures",
            "tool_run_triage_classify",
            "tool_run_triage_extract",
            "tool_run_triage_record",
            "tool_run_triage_settle",
            "tool_run_triage_show",
            "tool_run_triage_verdict",
        )
    ),
    reason="triage bindings are not in this wheel",
)
def test_triage_binding_round_trips(tmp_path: Path) -> None:
    store = str(tmp_path / "tools" / "runs.sqlite")
    definition = {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "check",
        "stages": "run_silent",
        "inputs": ["Justfile"],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    started = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["just", "check"],
            "project": "sase",
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store,
    )
    record_run_id = started["run"]["run_id"]
    pytest_item = tool_run_triage_extract(
        {
            "stage_key": "test (scoped)",
            "output": "FAILED tests/test_triage.py::test_round_trip",
            "project_root": str(tmp_path),
        }
    )["items"][0]
    assert pytest_item["extractor"] == "pytest"
    mypy_item = tool_run_triage_extract(
        {
            "stage_key": "lint (mypy)",
            "output": "src/foo.py:10:5: error: Bad thing  [attr-defined]\n",
            "project_root": str(tmp_path),
        }
    )["items"][0]
    recorded = tool_run_triage_record(
        {
            "run_id": record_run_id,
            "stages": [
                {
                    "stage_key": "lint (mypy)",
                    "stage_id": "stage-1",
                    "extraction_status": "parsed",
                    "output_path": "logs/stage.log",
                    "decision": None,
                    "items": [mypy_item],
                }
            ],
            "run_facts": {
                "continuation_mode": "never",
                "recipe_finished_ts": 10,
                "triaged_ts": 11,
                "diagnostics": ["round trip"],
            },
            "now_ts": 12,
        },
        store_path=store,
    )
    assert recorded["items_inserted"] == 1
    assert (
        tool_run_triage_show({"run_id": record_run_id}, store_path=store)["items"][0][
            "signature"
        ]
        == mypy_item["signature"]
    )

    def subject(run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "project": "sase",
            "tool": "check",
            "extra_args_digest": "",
            "workspace": "subject-workspace",
            "base_head": "subject-head",
            "dirty_paths": [],
            "complete_fingerprint": True,
            "fingerprint_digest": f"{run_id}-fingerprint",
            "ad_hoc": False,
        }

    subject_item = {
        key: pytest_item[key]
        for key in (
            "stage_key",
            "extractor",
            "extractor_version",
            "signature",
            "locator_paths",
        )
    }
    witness = {
        "run_id": "witness",
        "project": "sase",
        "tool": "check",
        "extra_args_digest": "",
        "workspace": "witness-workspace",
        "base_head": "subject-head",
        "dirty_paths": [],
        "complete_fingerprint": True,
        "fingerprint_digest": "witness-fingerprint",
        "ad_hoc": False,
        "agent": "witness-agent",
        "settled_ts": 9,
        "clean_tree": True,
        "dirty_unknown": False,
        "failed": True,
        "stage_completions": [],
        "items": [
            {
                key: pytest_item[key]
                for key in ("extractor", "extractor_version", "signature", "stage_key")
            }
        ],
        "selection_source": False,
    }
    classify_common = {
        "subjects": [subject_item],
        "selection_records": [],
        "ancestry": ["subject-head"],
        "flake_baseline": [],
        "owner_candidates": [],
        "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
        "now_ts": 20,
    }
    known = tool_run_triage_classify(
        {**classify_common, "subject_run": subject("known"), "evidence_runs": [witness]}
    )
    assert known["labels"][0]["class"] == "known"
    unknown = tool_run_triage_classify(
        {
            **classify_common,
            "subject_run": subject("unknown"),
            "evidence_runs": [],
        }
    )
    assert unknown["labels"][0]["class"] == "unknown"
    verdict = tool_run_triage_verdict(
        {
            "exit_code": 1,
            "legacy_state": "failed",
            "legacy_exit_code": 1,
            "has_completed_stage": False,
            "has_failed_stage": True,
            "all_stages_complete": False,
            "recipe_finished": True,
            "is_stageful_tool": True,
            "triaged": True,
            "has_unparsed_failed_stage": False,
            "items": [{"class": "known"}],
        }
    )
    assert verdict["kind"] == "verification"

    settled_run = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["just", "check"],
            "project": "sase",
            "workspace": "settled-workspace",
            "now_ts": 30,
            "commit_running": True,
        },
        store_path=store,
    )["run"]
    settled_run_id = settled_run["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": settled_run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "sase",
                "repos": [
                    {"identity": "sase", "head": "subject-head", "dirty_paths": []}
                ],
                "completeness": {"complete": True},
            },
        },
        store_path=store,
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": settled_run_id,
            "state": "failed",
            "exit_code": 1,
            "duration_ms": 1,
            "now_ts": 31,
        },
        store_path=store,
    )
    settled = tool_run_triage_settle(
        {
            "run_id": settled_run_id,
            "stages": [
                {
                    "stage_key": "lint (mypy)",
                    "stage_id": "stage-1",
                    "output": "src/foo.py:10:5: error: Bad thing  [attr-defined]\n",
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": str(tmp_path),
            "workspace_roots": [],
            "ancestry": ["subject-head"],
            "flake_baseline": [],
            "selection_records": [],
            "owner_candidates": [],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "continuation_mode": "never",
            "recipe_finished_ts": 32,
            "now_ts": 32,
        },
        store_path=store,
    )
    assert settled["triaged"] is True
    failures = tool_run_failures(
        {"project": "sase", "tool": "check", "days": 7, "limit": 10, "now_ts": 33},
        store_path=store,
    )
    assert any(
        group["signature"] == mypy_item["signature"] for group in failures["groups"]
    )


def test_triage_settle_stores_location_matched_owner_only(tmp_path: Path) -> None:
    """Owner-pin round trip: settle stores the location-matching candidate only.

    Regression for the sase-191.3 probe: the old token-substring matcher
    suggested beads shaped like sase-106 for src/sase/tool/executor.py on
    shared path tokens. The path-level matcher must store exactly the
    location-matching candidate, with matched_on.
    """
    store = str(tmp_path / "tools" / "runs.sqlite")
    definition = {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "check",
        "stages": "run_silent",
        "inputs": ["Justfile"],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    settled_run_id = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["just", "check"],
            "project": "sase",
            "workspace": "owner-pin-workspace",
            "now_ts": 30,
            "commit_running": True,
        },
        store_path=store,
    )["run"]["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": settled_run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "sase",
                "repos": [
                    {"identity": "sase", "head": "owner-pin-head", "dirty_paths": []}
                ],
                "completeness": {"complete": True},
            },
        },
        store_path=store,
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": settled_run_id,
            "state": "failed",
            "exit_code": 1,
            "duration_ms": 1,
            "now_ts": 31,
        },
        store_path=store,
    )
    settled = tool_run_triage_settle(
        {
            "run_id": settled_run_id,
            "stages": [
                {
                    "stage_key": "lint (mypy)",
                    "stage_id": "stage-1",
                    "output": (
                        "src/sase/tool/executor.py:10:5: "
                        "error: Bad thing  [attr-defined]\n"
                    ),
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": str(tmp_path),
            "workspace_roots": [],
            "ancestry": ["owner-pin-head"],
            "flake_baseline": [],
            "selection_records": [],
            "owner_candidates": [
                {
                    "node_id": "sase-900",
                    "location": "src/sase/tool/executor.py",
                    "title": "fix executor failure",
                    "status": "open",
                },
                {
                    "node_id": "sase-106",
                    "location": None,
                    "title": "gate shell handoff",
                    "status": "open",
                },
            ],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "continuation_mode": "never",
            "recipe_finished_ts": 32,
            "now_ts": 32,
        },
        store_path=store,
    )
    assert settled["triaged"] is True
    shown = tool_run_triage_show({"run_id": settled_run_id}, store_path=store)
    assert len(shown["items"]) == 1
    assert shown["items"][0]["label"]["possible_owners"] == [
        {
            "id": "sase-900",
            "status": "open",
            "reason": "possible owner",
            "matched_on": "location",
        }
    ]
