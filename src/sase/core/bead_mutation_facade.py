"""Python facade for Rust-backed bead mutation operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status
from sase.bead.project import AlreadyReadyError, NotAPlanError
from sase.core.bead_wire import (
    issue_from_dict,
    issue_type_value,
    issues_from_list,
    tier_value,
)
from sase.core.rust import require_rust_binding


def init_store(
    root_dir: Path | str,
    beads_dirname: str,
    *,
    issue_prefix: str,
    owner: str = "",
) -> dict[str, Any]:
    binding = require_rust_binding("bead_init_store")
    return dict(binding(str(root_dir), beads_dirname, issue_prefix, owner))


def create(
    beads_dir: Path | str,
    *,
    title: str,
    issue_type: IssueType,
    tier: BeadTier | str | None = None,
    parent_id: str | None = None,
    description: str = "",
    notes: str = "",
    design: str = "",
    assignee: str = "",
    changespec_name: str | int | None = "",
    changespec_bug_id: str | int | None = "",
    epic_count: int | None = None,
    model: str = "",
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "create",
        "beads_dir": str(beads_dir),
        "create": {
            "title": title,
            "issue_type": issue_type_value(issue_type),
            "tier": None if tier is None else tier_value(tier),
            "parent_id": parent_id,
            "description": description,
            "notes": notes,
            "design": design,
            "assignee": assignee,
            "changespec_name": _optional_text(changespec_name),
            "changespec_bug_id": _optional_text(changespec_bug_id),
            "epic_count": epic_count,
            "model": model,
            "now": now,
        },
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_create(
            beads_dir,
            title=title,
            issue_type=issue_type,
            tier=tier,
            parent_id=parent_id,
            description=description,
            notes=notes,
            design=design,
            assignee=assignee,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
            epic_count=epic_count,
            model=model,
            now=now,
        ),
    )
    return _issue_payload(result), result


def _direct_create(
    beads_dir: Path | str,
    *,
    title: str,
    issue_type: IssueType,
    tier: BeadTier | str | None = None,
    parent_id: str | None = None,
    description: str = "",
    notes: str = "",
    design: str = "",
    assignee: str = "",
    changespec_name: str | int | None = "",
    changespec_bug_id: str | int | None = "",
    epic_count: int | None = None,
    model: str = "",
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_create")
    return _call_issue_operation(
        binding,
        str(beads_dir),
        {
            "title": title,
            "issue_type": issue_type_value(issue_type),
            "tier": None if tier is None else tier_value(tier),
            "parent_id": parent_id,
            "description": description,
            "notes": notes,
            "design": design,
            "assignee": assignee,
            "changespec_name": _optional_text(changespec_name),
            "changespec_bug_id": _optional_text(changespec_bug_id),
            "epic_count": epic_count,
            "model": model,
            "now": now,
        },
    )


def update(
    beads_dir: Path | str,
    issue_id: str,
    **fields: str | int | bool | None,
) -> tuple[Issue, dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "open" if fields.get("status") == "open" else "update",
        "beads_dir": str(beads_dir),
        "issue_id": issue_id,
        "update": dict(fields),
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_update(beads_dir, issue_id, **fields),
    )
    return _issue_payload(result), result


def _direct_update(
    beads_dir: Path | str,
    issue_id: str,
    **fields: str | int | bool | None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_update")
    return _call_issue_operation(binding, str(beads_dir), issue_id, fields)


def preclaim_epic_work(
    beads_dir: Path | str,
    epic_id: str,
    assignments: list[tuple[str, str]],
    *,
    now: str | None = None,
) -> tuple[list[Issue], list[tuple[str, Status, str]], dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "preclaim_epic_work",
        "beads_dir": str(beads_dir),
        "issue_id": epic_id,
        "assignments": [
            {"bead_id": bead_id, "agent_name": agent_name}
            for bead_id, agent_name in assignments
        ],
        "now": now,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_preclaim_epic_work(
            beads_dir, epic_id, assignments, now=now
        ),
    )
    rollback = _rollback_preclaims(result)
    return issues_from_list(result.get("issues", [])), rollback, result


def _direct_preclaim_epic_work(
    beads_dir: Path | str,
    epic_id: str,
    assignments: list[tuple[str, str]],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_preclaim_epic_work")
    return _call_issue_operation(
        binding,
        str(beads_dir),
        epic_id,
        [
            {"bead_id": bead_id, "agent_name": agent_name}
            for bead_id, agent_name in assignments
        ],
        now,
    )


def close(
    beads_dir: Path | str,
    issue_ids: list[str],
    *,
    reason: str | None = None,
    now: str | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "close",
        "beads_dir": str(beads_dir),
        "issue_ids": issue_ids,
        "reason": reason,
        "now": now,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_close(
            beads_dir, issue_ids, reason=reason, now=now
        ),
    )
    return issues_from_list(result.get("issues", [])), result


def _direct_close(
    beads_dir: Path | str,
    issue_ids: list[str],
    *,
    reason: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_close")
    return _call_issue_operation(binding, str(beads_dir), issue_ids, reason, now)


def remove(
    beads_dir: Path | str,
    issue_id: str,
) -> tuple[list[Issue], dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "rm",
        "beads_dir": str(beads_dir),
        "issue_id": issue_id,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_remove(beads_dir, issue_id),
    )
    return issues_from_list(result.get("issues", [])), result


def _direct_remove(beads_dir: Path | str, issue_id: str) -> dict[str, Any]:
    binding = require_rust_binding("bead_remove")
    return _call_issue_operation(binding, str(beads_dir), issue_id)


def add_dependency(
    beads_dir: Path | str,
    issue_id: str,
    depends_on_id: str,
    *,
    now: str | None = None,
) -> tuple[Dependency, dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "dep_add",
        "beads_dir": str(beads_dir),
        "issue_id": issue_id,
        "depends_on_id": depends_on_id,
        "now": now,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_add_dependency(
            beads_dir, issue_id, depends_on_id, now=now
        ),
    )
    return _dependency_payload(result), result


def _direct_add_dependency(
    beads_dir: Path | str,
    issue_id: str,
    depends_on_id: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_dep_add")
    return _call_issue_operation(
        binding, str(beads_dir), issue_id, depends_on_id, now
    )


def mark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "mark_ready_to_work",
        "beads_dir": str(beads_dir),
        "issue_id": epic_id,
        "now": now,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_mark_ready_to_work(
            beads_dir, epic_id, now=now
        ),
    )
    return _issue_payload(result), result


def _direct_mark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_mark_ready_to_work")
    return _call_issue_operation(binding, str(beads_dir), epic_id, now)


def unmark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    payload = {
        "schema_version": 1,
        "operation": "unmark_ready_to_work",
        "beads_dir": str(beads_dir),
        "issue_id": epic_id,
        "now": now,
    }
    result = _write_or_fallback(
        beads_dir,
        payload,
        direct_writer=lambda: _direct_unmark_ready_to_work(
            beads_dir, epic_id, now=now
        ),
    )
    return _issue_payload(result), result


def _direct_unmark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    binding = require_rust_binding("bead_unmark_ready_to_work")
    return _call_issue_operation(binding, str(beads_dir), epic_id, now)


def export_jsonl(beads_dir: Path | str) -> dict[str, Any]:
    binding = require_rust_binding("bead_export_jsonl")
    return dict(binding(str(beads_dir)))


def sync_is_clean(beads_dir: Path | str) -> bool:
    binding = require_rust_binding("bead_sync_is_clean")
    return bool(binding(str(beads_dir)))


def _call_issue_operation(binding: Any, *args: Any) -> dict[str, Any]:
    try:
        return dict(binding(*args))
    except ValueError as exc:
        message = str(exc)
        if "not_found:" in message or "Issue not found:" in message:
            issue_id = message.rsplit("Issue not found:", 1)[-1].strip()
            raise KeyError(f"Issue not found: {issue_id}") from exc
        if "not_a_plan:" in message:
            raise NotAPlanError(message.split("not_a_plan:", 1)[-1].strip()) from exc
        if "already_ready:" in message:
            raise AlreadyReadyError(
                message.split("already_ready:", 1)[-1].strip()
            ) from exc
        raise


def _issue_payload(payload: dict[str, Any]) -> Issue:
    return issue_from_dict(payload["issue"])


def _dependency_payload(payload: dict[str, Any]) -> Dependency:
    dep = payload["dependency"]
    return Dependency(
        issue_id=str(dep["issue_id"]),
        depends_on_id=str(dep["depends_on_id"]),
        created_at=str(dep.get("created_at", "")),
        created_by=str(dep.get("created_by", "")),
    )


def _rollback_preclaims(payload: dict[str, Any]) -> list[tuple[str, Status, str]]:
    return [
        (
            str(item["bead_id"]),
            Status(str(item["status"])),
            "" if item.get("assignee") is None else str(item.get("assignee", "")),
        )
        for item in payload.get("rollback_preclaims", [])
    ]


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


def _write_or_fallback(
    beads_dir: Path | str,
    payload: dict[str, Any],
    *,
    direct_writer: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    from sase.daemon.write_facade import write_or_fallback

    result = write_or_fallback(
        "beads",
        daemon_writer=lambda daemon: _daemon_write(daemon, beads_dir, payload),
        direct_writer=direct_writer,
        required_capability="beads.write",
    )
    return result.value


def _daemon_write(
    daemon: Any,
    beads_dir: Path | str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = daemon.write(
        "beads",
        {
            "schema_version": 1,
            "project_id": _project_id_for_beads_dir(beads_dir),
            "idempotency_key": _idempotency_key(beads_dir, payload),
            "actor": _actor_payload(),
            "payload": payload,
        },
    )
    outcome = response.get("outcome")
    if not isinstance(outcome, dict):
        raise ValueError("daemon bead write response is missing outcome")
    snapshot = outcome.get("projection_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("daemon bead write response is missing mutation snapshot")
    return snapshot


def _project_id_for_beads_dir(beads_dir: Path | str) -> str:
    path = Path(beads_dir).resolve()
    parts = path.parts
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return path.parents[1].name
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return path.parents[2].name
    return path.parent.name or "default"


def _idempotency_key(beads_dir: Path | str, payload: dict[str, Any]) -> str:
    stable = {
        "beads_dir": str(Path(beads_dir).resolve()),
        "payload": payload,
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return "beads:" + hashlib.sha256(encoded).hexdigest()


def _actor_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "actor_type": "cli",
        "name": "sase",
        "version": None,
        "runtime": "python",
    }


__all__ = [
    "add_dependency",
    "close",
    "create",
    "export_jsonl",
    "init_store",
    "mark_ready_to_work",
    "preclaim_epic_work",
    "remove",
    "sync_is_clean",
    "unmark_ready_to_work",
    "update",
]
