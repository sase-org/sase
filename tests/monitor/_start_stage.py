"""Shared builders for staged-monitor start tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_monitor_start_stage_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.core.continuation_facade import seal_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.monitor.start import StartMonitorRequest
from sase.running_field import WorkspaceClaim
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = [
    "SANDBOX_CATALOG",
    "read_reservations",
    "sandbox_home",
    "sandbox_project",
    "sealed_intent",
    "stage_env",
    "stage_request",
]


SANDBOX_CATALOG = """\
tools:
  check:
    argv: ["true"]
    description: sandbox verify probe
    stages: none
    inputs: []
    env: []
    args: deny
    fingerprint:
      repos: []
      toolchain: {}
"""


def read_reservations(artifacts_dir: str | Path) -> dict[str, Any]:
    """Return the prepared-completion reservation map for *artifacts_dir*."""
    path = (
        Path(artifacts_dir)
        / "continuation"
        / "completion_intents"
        / "reservations.json"
    )
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["reservations"]


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox ``SASE_HOME`` and clear agent identity env for staging tests."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)


def sandbox_project(tmp_path: Path, name: str = "proj") -> Path:
    """Create a git project root with a sandbox tool catalog."""
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir(parents=True)
    (sase_dir / "sase.yml").write_text(SANDBOX_CATALOG, encoding="utf-8")
    return root


def stage_request(
    tmp_path: Path,
    *,
    command: str = "true",
    cwd: str | None = None,
    join_run_id: str | None = None,
    profile: str | None = None,
    completion_ref: str | None = None,
    checkpoint_ref: str | None = None,
    checkpoint_document: dict[str, object] | None = None,
) -> StartMonitorRequest:
    """Build a staged-monitor start request rooted at *tmp_path*."""
    return StartMonitorRequest(
        command=command,
        reason="verify staging",
        timeout_seconds=30.0,
        cwd=cwd or str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
        join_run_id=join_run_id,
        profile=profile,
        completion_ref=completion_ref,
        checkpoint_ref=checkpoint_ref,
        checkpoint_document=checkpoint_document,
    )


def sealed_intent(command: list[str]) -> dict[str, Any]:
    """Return a sealed conditional-completion intent for *command*."""

    def digest(label: str) -> str:
        return sha256(label.encode()).hexdigest()

    context_digest = digest("context")
    plan_digest = digest("plan")
    return seal_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "creator": {
                "project": "sase",
                "run_id": "run-1",
                "agent_name": "acme",
            },
            "context": {
                "run_id": "run-1",
                "agent_id": "acme",
                "turn_nonce": "nonce-1",
                "plan_digest": plan_digest,
                "context_digest": context_digest,
                "obligation_ids": ["repo-main"],
            },
            "success_message": "Required checks passed.",
            "verification_command": command,
            "declaration": {
                "schema_version": 2,
                "context_digest": context_digest,
                "plan_digest": plan_digest,
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
                    "head": digest("head"),
                    "head_tree": digest("head-tree"),
                    "index_tree": digest("index-tree"),
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


def stage_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cwd: str | None = None,
    workspace_num: int = 3,
    workspace_dir: str | None = None,
    starter_workspace_dir: str | None = None,
    starter_name: str = "acme",
    agent_session: str | None = "acme",
) -> list[str]:
    """Register a starter agent and project records for a staged monitor."""
    write_project_file(
        "proj",
        workspace_dir=workspace_dir,
        running_claims=[
            WorkspaceClaim(workspace_num, "ace-run", "acme", pid=os.getpid())
        ],
    )
    starter_meta: dict[str, object] = {
        "model": "claude-sonnet-5",
        "workspace_dir": starter_workspace_dir or workspace_dir or cwd or str(tmp_path),
        "workspace_num": workspace_num,
        "pid": os.getpid(),
        "cl_name": "acme",
    }
    if agent_session is not None:
        starter_meta["agent_session"] = agent_session
    if starter_name != "acme" and agent_session is not None:
        starter_meta.update(
            workflow_name=agent_session,
            role_suffix="--1",
            agent_session_role="member",
        )
    starter_dir = make_starter_agent(
        "proj", "20260812120000", starter_name, **starter_meta
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", starter_name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    dirs = [starter_dir]
    patch_project_records(monkeypatch, dirs)
    return dirs
