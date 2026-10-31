"""Durable identity and delivery state for staged pipe successors."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.agent.gate_intent import atomic_write_json
from sase.agent._staged_handoff_recovery import (
    read_recovery_context,
    write_recovery_context_locked,
)
from sase.agent._staged_handoff_store import (
    StagedHandoffError,
    artifacts_root,
    path_exists,
    read_json_object,
)

STAGED_SUCCESSOR_FILENAME = ".sase_handoff_successor.json"
STAGED_SUCCESSOR_PROMPT_FILENAME = "staged_successor_prompt.md"
STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME = "staged_successor_origin_prompt.md"
_DELIVERY_STATES = ("prepared", "created", "submitted", "started", "terminal")
_NEXT_STATES = {
    "prepared": {"prepared", "created", "submitted", "started", "terminal"},
    "created": {"created", "submitted", "started", "terminal"},
    "submitted": {"submitted", "started", "terminal"},
    "started": {"started", "terminal"},
    "terminal": {"terminal"},
}
_IMMUTABLE_SUCCESSOR_FIELDS = (
    "agent_name",
    "role_suffix",
    "artifacts_dir",
    "artifacts_timestamp",
    "launch_timestamp",
    "launch_identity",
    "prompt_ref",
    "launch_prompt_ref",
    "launch_prompt_digest",
    "origin_prompt_ref",
    "prompt_digest",
    "model",
    "provider",
    "workspace_dir",
    "workspace_num",
    "project_name",
    "project_file",
    "origin_artifacts_timestamp",
    "is_home_mode",
    "cl_name",
    "vcs_ref",
    "attach_plan",
)


def successor_prompt_digest(prompt: str) -> str:
    """Return a stable digest for the exact persisted continuation prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def write_successor_prompt(
    artifacts_dir: str | Path,
    prompt: str,
    *,
    filename: str = STAGED_SUCCESSOR_PROMPT_FILENAME,
) -> Path:
    """Atomically persist a continuation prompt before making its child runnable."""
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    fd, temporary = tempfile.mkstemp(prefix=f".{filename}.", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(prompt)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StagedHandoffError(f"staged successor {field} must be non-empty text")
    return value


def _validate_successor_record(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != 1:
        raise StagedHandoffError("unsupported staged successor schema version")
    staged_id = _text(value.get("staged_id"), "staged_id")
    if value.get("kind") != "pipe":
        raise StagedHandoffError("staged successor record kind must be 'pipe'")
    origin = _text(value.get("origin_artifacts_dir"), "origin_artifacts_dir")
    delivery_state = value.get("delivery_state")
    if delivery_state not in _DELIVERY_STATES:
        raise StagedHandoffError("staged successor delivery_state is invalid")
    successor = value.get("successor")
    if not isinstance(successor, dict):
        raise StagedHandoffError("staged successor identity is missing")
    for field in (
        "agent_name",
        "role_suffix",
        "artifacts_dir",
        "artifacts_timestamp",
        "launch_timestamp",
        "launch_identity",
        "prompt_ref",
        "prompt_digest",
        "project_name",
        "project_file",
        "origin_artifacts_timestamp",
        "cl_name",
    ):
        _text(successor.get(field), field)
    if successor.get("provider") is not None:
        _text(successor.get("provider"), "provider")
    if successor.get("model") is not None:
        _text(successor.get("model"), "model")
    if successor.get("workspace_dir") is not None:
        _text(successor.get("workspace_dir"), "workspace_dir")
    else:
        raise StagedHandoffError("staged successor workspace_dir is required")
    if (
        successor.get("workspace_num") is not None
        and type(successor.get("workspace_num")) is not int
    ):
        raise StagedHandoffError("staged successor workspace_num must be an integer")
    if not isinstance(successor.get("is_home_mode"), bool):
        raise StagedHandoffError("staged successor is_home_mode must be boolean")
    for field in ("relationships", "continuation_refs", "loop_state"):
        if not isinstance(successor.get(field), dict):
            raise StagedHandoffError(f"staged successor {field} must be an object")
    attach_plan = successor.get("attach_plan")
    if attach_plan is not None and not isinstance(attach_plan, dict):
        raise StagedHandoffError("staged successor attach_plan must be an object")
    if successor.get("launch_prompt_ref") is not None:
        _text(successor.get("launch_prompt_ref"), "launch_prompt_ref")
    if successor.get("launch_prompt_digest") is not None:
        _text(successor.get("launch_prompt_digest"), "launch_prompt_digest")
    if successor.get("vcs_ref") is not None:
        vcs_ref = successor["vcs_ref"]
        if (
            not isinstance(vcs_ref, list)
            or len(vcs_ref) != 2
            or not all(isinstance(item, str) and item for item in vcs_ref)
        ):
            raise StagedHandoffError("staged successor vcs_ref must be a pair")
    return {
        **value,
        "schema_version": 1,
        "staged_id": staged_id,
        "origin_artifacts_dir": origin,
        "delivery_state": delivery_state,
        "successor": dict(successor),
    }


def staged_successor_path(artifacts_dir: str | Path) -> Path:
    """Return the staged successor manifest path."""
    return Path(artifacts_dir) / STAGED_SUCCESSOR_FILENAME


def read_staged_successor(
    artifacts_dir: str | None = None,
    *,
    staged_id: str | None = None,
) -> dict[str, Any] | None:
    """Read a validated successor manifest; malformed state is a refusal."""
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_SUCCESSOR_FILENAME
    if not path_exists(path):
        return None
    record = _validate_successor_record(
        read_json_object(path, label="staged successor manifest")
    )
    if record["origin_artifacts_dir"] != str(root):
        raise StagedHandoffError("staged successor manifest has a mismatched origin")
    if staged_id is not None and record["staged_id"] != staged_id:
        raise StagedHandoffError("staged successor manifest belongs to another stage")
    return record


def write_staged_successor_locked(
    record: dict[str, Any],
    *,
    artifacts_dir: str | Path,
) -> dict[str, Any]:
    """Write a new successor manifest while the caller holds the adoption lock."""
    root = Path(artifacts_dir)
    normalized = _validate_successor_record(record)
    if normalized["origin_artifacts_dir"] != str(root):
        raise StagedHandoffError("staged successor manifest has a mismatched origin")
    path = root / STAGED_SUCCESSOR_FILENAME
    if path_exists(path):
        current = read_staged_successor(str(root), staged_id=normalized["staged_id"])
        if current is None:
            raise StagedHandoffError("staged successor manifest disappeared")
        for field in _IMMUTABLE_SUCCESSOR_FIELDS:
            if current["successor"].get(field) != normalized["successor"].get(field):
                raise StagedHandoffError(
                    f"staged successor {field} changed after it was persisted"
                )
        return current
    atomic_write_json(path, normalized)
    recovery_context = read_recovery_context(
        str(root), staged_id=normalized["staged_id"]
    )
    if recovery_context is not None:
        recovery_context["prompt_ref"] = normalized["successor"]["prompt_ref"]
        write_recovery_context_locked(recovery_context, artifacts_dir=root)
    return normalized


def update_staged_successor_locked(
    artifacts_dir: str | Path,
    staged_id: str,
    *,
    delivery_state: str,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a monotonic delivery update while the caller holds the adoption lock."""
    root = Path(artifacts_dir)
    current = read_staged_successor(str(root), staged_id=staged_id)
    if current is None:
        raise StagedHandoffError("staged successor manifest is missing")
    if delivery_state not in _NEXT_STATES[current["delivery_state"]]:
        raise StagedHandoffError(
            "staged successor delivery state cannot move backward from "
            f"{current['delivery_state']!r} to {delivery_state!r}"
        )
    next_record = {**current, "delivery_state": delivery_state}
    successor = dict(current["successor"])
    for key, value in (updates or {}).items():
        if key in _IMMUTABLE_SUCCESSOR_FIELDS and successor.get(key) != value:
            raise StagedHandoffError(f"staged successor {key} is immutable")
        successor[key] = value
    next_record["successor"] = successor
    normalized = _validate_successor_record(next_record)
    atomic_write_json(root / STAGED_SUCCESSOR_FILENAME, normalized)
    return normalized


__all__ = [
    "STAGED_SUCCESSOR_FILENAME",
    "STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME",
    "STAGED_SUCCESSOR_PROMPT_FILENAME",
    "read_staged_successor",
    "staged_successor_path",
    "successor_prompt_digest",
    "update_staged_successor_locked",
    "write_staged_successor_locked",
    "write_successor_prompt",
]
