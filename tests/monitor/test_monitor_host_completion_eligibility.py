"""Eligibility coverage for host completion: sidecar archive commits stay eligible."""

from __future__ import annotations

from sase.core.continuation_facade import (
    bind_conditional_completion,
    evaluate_conditional_completion,
    seal_conditional_completion,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from tests.core._continuation_facade_helpers import (
    digest,
    make_passed_stage,
    make_prepare_request,
)

from ._host_completion import sandbox_home as sandbox_home

__all__ = [
    "test_unrelated_prompt_archive_commit_does_not_stale_prepared_completion",
]


def test_unrelated_prompt_archive_commit_does_not_stale_prepared_completion() -> None:
    request = make_prepare_request()
    sidecar = {
        "repo_id": "repo-agents",
        "kind": "sibling",
        "name": "agents",
        "head": digest("agents-before"),
        "head_tree": digest("agents-tree-before"),
        "index_tree": digest("agents-tree-before"),
        "complete": True,
        "paths": [
            {
                "path": "files/objects/sha256/40/40de62",
                "xy": "??",
                "content_hash": digest("pending-object"),
                "mode": "100644",
                "kind": "untracked",
                "protected": True,
                "foreign": True,
            }
        ],
    }
    request["observations"].append(sidecar)
    prepared = seal_conditional_completion(request)
    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )
    changed_sidecar = {
        **sidecar,
        "head": digest("agents-after"),
        "head_tree": digest("agents-tree-after"),
        "index_tree": digest("agents-tree-after"),
        "paths": [],
    }
    stages = [
        make_passed_stage("formatting", "fmt (python)"),
        make_passed_stage("ruff", "lint (ruff)"),
        make_passed_stage("mypy", "lint (mypy)"),
        make_passed_stage("validation", "SASE validation"),
        make_passed_stage("full_tests", "test (full)"),
    ]

    decision = evaluate_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "outcome": "completed",
            "exit_code": 0,
            "command": ["just", "check-full"],
            "observations": [request["observations"][0], changed_sidecar],
            "stages": stages,
            "executors": request["executors"],
            "workspace_identity": "/ws/20",
            "original_workspace_identity": "/ws/20",
            "degraded_workspace": False,
            "current_plan_digest": digest("plan"),
            "current_obligation_ids": ["repo-main"],
            "substitutions": {"duration": "3m 02s"},
        }
    )

    assert decision["eligible"] is True
    assert decision["action"] == "complete"
