"""Shared helpers for prepared-bridge finalizer tests."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import write_staged_handoff
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.declaration_store import FinalizerDeclarationError
from sase.finalizers.prepare import prepare_conditional_completion
from sase.finalizers.prepared_coverage import PREPARED_RESERVATION_PAYLOAD_KEY

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    stub_run_silent_check_catalog,
    valid_manifest,
)


STAGED_ID = "123e4567-e89b-12d3-a456-426614174000"
MONITOR_ID = "monitor-1"
FINGERPRINT = "sha256:prepared-bridge"
COMMAND = ["just", "check"]


@pytest.fixture(autouse=True)
def run_silent_check_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_run_silent_check_catalog(monkeypatch)


def digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _observation(repo_id: str, *, head_tree: str | None = None) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "kind": "main",
        "name": "main",
        "head": digest("head"),
        "head_tree": head_tree or digest("head-tree"),
        "index_tree": digest("index-tree"),
        "complete": True,
        "paths": [
            {
                "path": "src/app.py",
                "xy": "M",
                "content_hash": digest("app"),
                "mode": "100644",
                "kind": "file",
                "protected": False,
                "foreign": False,
            }
        ],
    }


def reservation() -> dict[str, Any]:
    return {
        "staged_id": STAGED_ID,
        "monitor_id": MONITOR_ID,
        "request_fingerprint": FINGERPRINT,
        "command": list(COMMAND),
    }


def stage_monitor(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    *,
    prepared_intent_ref: str,
    reservation: dict[str, Any] | None = None,
    kind: str = "monitor",
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    payload: dict[str, Any] = {"prepared_intent_ref": prepared_intent_ref}
    if reservation is not None:
        payload[PREPARED_RESERVATION_PAYLOAD_KEY] = reservation
    record = {
        "schema_version": 1,
        "staged_id": STAGED_ID,
        "kind": kind,
        "created_at": "2026-10-29T12:00:00Z",
        "payload": payload,
        "successor_workspace": "inherit",
        "carry_allowed": False,
        "dirty_obligations_at_stage": [],
    }
    write_staged_handoff(record, artifacts_dir=str(artifacts), command="test stage")
    return record


def seal_prepared(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    *,
    command: list[str] = COMMAND,
) -> tuple[Any, Any, list[dict[str, object]], str]:
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = publication.context.obligations[0].obligation_id
    observations = [_observation(repo_id)]
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: observations,
    )
    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed.",
            "verification": {"command": list(command)},
            "declaration": valid_manifest(publication),
        },
        artifacts_dir=str(artifacts),
    )
    return publication, prepared, observations, repo_id
