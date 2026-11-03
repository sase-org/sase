"""Shared real-controller host-completion builders.

Public helpers live here so the split
``test_monitor_host_completion_controller_*`` modules can share them without
importing ``_``-private names across test modules.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.continuation_facade import bind_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.prepare import (
    persist_prepared_completion,
    prepare_conditional_completion,
)
from sase.monitor.diagnostics import diagnostic_manifest_path
from sase.monitor.followup import launch_followup_agent
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

from ..finalizer_declaration_channel_test_helpers import (
    stub_run_silent_check_catalog,
    valid_manifest,
)

__all__ = [
    "bind_prepared",
    "capture",
    "check_full_stages",
    "controller_catalog",
    "controller_meta",
    "controller_recovery",
    "observation",
    "write_stages",
]


@pytest.fixture(autouse=True)
def controller_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror the sase checkout's stage-reporting check tools, so prepare seals stage_source: run_silent."""

    stub_run_silent_check_catalog(monkeypatch)


def capture() -> OutputCapture:
    return OutputCapture()


def _passed_stage(stage_id: str, name: str) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "name": name,
        "status": "passed",
        "exit_code": 0,
        "diagnostic_refs": [],
        "counts": {},
        "retained_ranges": [],
        "capture_errors": [],
    }


def check_full_stages() -> list[dict[str, Any]]:
    return [
        _passed_stage("formatting", "fmt (python)"),
        _passed_stage("ruff", "lint (ruff)"),
        _passed_stage("mypy", "lint (mypy)"),
        _passed_stage("validation", "SASE validation"),
        _passed_stage("full_tests", "test (full)"),
    ]


def write_stages(artifacts: Path, stages: list[dict[str, Any]]) -> None:
    path = diagnostic_manifest_path(artifacts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "stages": stages}
        ),
        encoding="utf-8",
    )


def observation(
    repo_id: str, *, name: str = "main", kind: str = "main"
) -> dict[str, Any]:
    digest = "a" * 64
    return {
        "repo_id": repo_id,
        "kind": kind,
        "name": name,
        "head": digest,
        "head_tree": digest,
        "index_tree": digest,
        "complete": True,
        "paths": [
            {
                "path": "src/app.py",
                "xy": "M",
                "content_hash": digest,
                "mode": "100644",
                "kind": "file",
                "protected": False,
                "foreign": False,
            }
        ],
    }


def controller_recovery(
    recoveries: list[str],
) -> Any:
    required = {
        name
        for name, parameter in inspect.signature(
            launch_followup_agent
        ).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    }

    def launch_recovery(
        artifacts_dir: str,
        meta: dict[str, Any],
        *,
        monitor_state: str,
        exit_code: int | None,
        elapsed_seconds: float,
        capture: OutputCapture,
        project_name: str,
        timeout_kind: str | None = None,
        transfer_from_pid: int | None = None,
    ) -> FollowupLaunchResult:
        del meta, elapsed_seconds, timeout_kind, transfer_from_pid
        missing = required - {
            "monitor_state",
            "exit_code",
            "elapsed_seconds",
            "capture",
            "project_name",
        }
        assert not missing
        assert monitor_state == "completed"
        assert exit_code == 0
        assert isinstance(capture, OutputCapture)
        assert project_name == "proj"
        recoveries.append(artifacts_dir)
        return FollowupLaunchResult(launched=True, agent_name="acme--2")

    return launch_recovery


def controller_meta(artifacts: Path, intent_ref: str) -> dict[str, Any]:
    return {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": intent_ref,
        "monitor_profile": "verify",
        "monitor_command": "just check-full",
        "monitor_execution_argv": ["just", "check-full"],
        "workspace_dir": "/ws/20",
        "workspace_num": 20,
        "continuation_workspace_ref": "/ws/20",
        "continuation_monitor_result_id": "result-1",
        "monitor_next_action": "Diagnose failures or stale verification, then finish.",
        "name": "agent-1",
    }


def bind_prepared(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    observations: list[dict[str, Any]],
) -> str:
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: observations,
    )
    for module in (
        "sase.monitor.host_completion_settle",
        "sase.monitor.host_completion_run",
        "sase.monitor.host_completion_execute",
        "sase.monitor.host_completion_complete",
        "sase.monitor.host_completion_state",
    ):
        monkeypatch.setattr(
            f"{module}.observe_completion_repositories",
            lambda _root: observations,
            raising=False,
        )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed in {duration}.",
            "verification": {"command": ["just", "check-full"]},
            "declaration": valid_manifest(publication),
        },
        artifacts_dir=str(artifacts),
    )
    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared.intent,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )
    persist_prepared_completion(bound, artifacts_dir=artifacts)
    return prepared.intent_ref
