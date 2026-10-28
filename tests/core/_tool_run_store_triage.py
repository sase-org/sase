"""Tool-run store triage tests (classify/extract/record/settle)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_failures,
    tool_run_finish,
    tool_run_observe,
    tool_run_triage_classify,
    tool_run_triage_extract,
    tool_run_triage_record,
    tool_run_triage_settle,
    tool_run_triage_show,
    tool_run_triage_verdict,
)
from tests.core._tool_run_store_helpers import make_definition, make_store_path


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_begin"),
    reason="tool_run bindings are not in this wheel",
)


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
    store = make_store_path(tmp_path)
    definition = make_definition()
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
    store = make_store_path(tmp_path)
    definition = make_definition()
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
