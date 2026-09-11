"""Single-use prepared-completion binding during monitor start."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from sase.core.continuation_facade import seal_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.paths import sase_projects_dir
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.monitor.models import MonitorError
from sase.monitor.request import StartMonitorRequest, monitor_request_fingerprint
from sase.monitor.start import start_monitor
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, patch_project_records, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _sealed_intent() -> dict[str, object]:
    return seal_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "creator": {
                "project": "sase",
                "run_id": "run-1",
                "agent_name": "agent-1",
            },
            "context": {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "turn_nonce": "nonce-1",
                "plan_digest": _digest("plan"),
                "context_digest": _digest("context"),
                "obligation_ids": ["repo-main"],
            },
            "success_message": "Required checks passed.",
            "verification_command": ["just", "check-full"],
            "declaration": {
                "schema_version": 2,
                "context_digest": _digest("context"),
                "plan_digest": _digest("plan"),
                "payloads": [
                    {
                        "instance_id": "commit",
                        "payload": {
                            "repositories": [
                                {
                                    "repo_id": "repo-main",
                                    "action": "commit",
                                    "message": "fix: finish the change",
                                }
                            ],
                            "deferrals": [],
                        },
                    }
                ],
            },
            "observations": [
                {
                    "repo_id": "repo-main",
                    "kind": "main",
                    "name": "main",
                    "head": _digest("head"),
                    "head_tree": _digest("head-tree"),
                    "index_tree": _digest("index-tree"),
                    "complete": True,
                    "paths": [
                        {
                            "path": "src/app.py",
                            "kind": "file",
                            "protected": False,
                            "foreign": False,
                        }
                    ],
                }
            ],
            "executors": [
                {
                    "instance_id": "commit",
                    "provider_ref": "builtin@commit",
                    "headless": True,
                    "durable_replay": True,
                    "requires_model": False,
                }
            ],
        }
    )


def _starter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--0")
    return starter_dir


def test_fingerprint_includes_completion_intent() -> None:
    shared = {"lane": "acme", "label": "just check-full"}
    base = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=30.0,
        cwd="/tmp/work",
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
        next_action="Fix failures.",
    )
    with_ref = StartMonitorRequest(
        command="just check-full",
        reason="verify",
        timeout_seconds=30.0,
        cwd="/tmp/work",
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
        next_action="Fix failures.",
        completion_ref="file:explicit:completion",
        profile="verify",
    )

    assert monitor_request_fingerprint(base, **shared) != monitor_request_fingerprint(
        with_ref, **shared
    )


def test_changed_command_creates_no_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starter_dir = _starter(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(_sealed_intent(), artifacts_dir=starter_dir)

    with pytest.raises(MonitorError, match="does not match"):
        start_monitor(
            StartMonitorRequest(
                command="just check",
                reason="verify",
                timeout_seconds=30.0,
                cwd=str(tmp_path),
                project_name="proj",
                start_status="TESTING",
                stop_status="TESTED",
                lane="acme",
                completion_ref=prepared.intent_ref,
            )
        )

    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        path.parent
        for path in artifacts_root.glob("*/*/*/agent_meta.json")
        if path.parent != Path(starter_dir)
    ]
    assert member_dirs == []
    reloaded = load_prepared_completion(prepared.intent_ref, artifacts_dir=starter_dir)
    assert reloaded["status"] == "prepared"


def test_failed_start_rolls_back_the_bound_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starter_dir = _starter(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(_sealed_intent(), artifacts_dir=starter_dir)

    import sase.procs.spawn as spawn_module

    def fake_popen(*args: object, **kwargs: object) -> None:
        raise OSError("no more processes")

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    with pytest.raises(MonitorError):
        start_monitor(
            StartMonitorRequest(
                command="just check-full",
                reason="verify",
                timeout_seconds=30.0,
                cwd=str(tmp_path),
                project_name="proj",
                start_status="TESTING",
                stop_status="TESTED",
                lane="acme",
                completion_ref=prepared.intent_ref,
            )
        )

    reloaded = load_prepared_completion(prepared.intent_ref, artifacts_dir=starter_dir)
    assert reloaded["status"] == "prepared"


def test_duplicate_bind_is_rejected_after_a_live_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starter_dir = _starter(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(_sealed_intent(), artifacts_dir=starter_dir)
    bound = json.loads(prepared.path.read_text(encoding="utf-8"))
    bound["status"] = "bound"
    bound["binding"] = {
        "monitor_id": "already-used",
        "request_fingerprint": "sha256:old",
        "bound_command": ["just", "check-full"],
    }
    prepared.path.write_text(json.dumps(bound), encoding="utf-8")

    with pytest.raises(MonitorError, match="not reusable"):
        start_monitor(
            StartMonitorRequest(
                command="just check-full",
                reason="verify",
                timeout_seconds=30.0,
                cwd=str(tmp_path),
                project_name="proj",
                start_status="TESTING",
                stop_status="TESTED",
                lane="acme",
                completion_ref=prepared.intent_ref,
            )
        )
