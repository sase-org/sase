"""Python facade for Rust-backed bead mutation operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
)
from sase.bead.project import AlreadyReadyError, NotAPlanError
from sase.core.bead_wire import (
    issue_from_dict,
    issue_type_value,
    issues_from_list,
    phase_size_value,
    tier_value,
)
from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_bead_store_write_sandboxed


def init_store(
    root_dir: Path | str,
    beads_dirname: str,
    *,
    issue_prefix: str,
    owner: str = "",
) -> dict[str, Any]:
    _guard_bead_store_write(Path(root_dir) / beads_dirname, "init_store")
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
    model: str = "",
    size: PhaseSize | str | None = None,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "create")
    binding = require_rust_binding("bead_create")
    payload = _call_issue_operation(
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
            "model": model,
            "size": None if size is None else phase_size_value(size),
            "now": now,
        },
    )
    return _issue_payload(payload), payload


def update(
    beads_dir: Path | str,
    issue_id: str,
    **fields: str | int | bool | None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "update")
    binding = require_rust_binding("bead_update")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, fields)
    return _issue_payload(payload), payload


def append_note(
    beads_dir: Path | str,
    issue_id: str,
    entry: str,
    *,
    author: str | None = None,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "append_note")
    binding = require_rust_binding("bead_append_note")
    payload = _call_issue_operation(
        binding, str(beads_dir), issue_id, entry, author, now
    )
    return _issue_payload(payload), payload


def claim_for_agent_launch(
    beads_dir: Path | str,
    bead_id: str,
    agent_name: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "claim_for_agent_launch")
    binding = require_rust_binding("bead_claim_for_agent_launch")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        bead_id,
        agent_name,
        now,
    )
    return _issue_payload(payload), payload


def claim_for_agent_wait(
    beads_dir: Path | str,
    bead_id: str,
    agent_name: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "claim_for_agent_wait")
    binding = require_rust_binding("bead_claim_for_agent_wait")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        bead_id,
        agent_name,
        now,
    )
    return _issue_payload(payload), payload


def release_agent_claim(
    beads_dir: Path | str,
    bead_id: str,
    agent_name: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "release_agent_claim")
    binding = require_rust_binding("bead_release_agent_claim")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        bead_id,
        agent_name,
        now,
    )
    return _issue_payload(payload), payload


def close(
    beads_dir: Path | str,
    issue_ids: list[str],
    *,
    reason: str | None = None,
    resolution: Resolution | str | None = None,
    force: bool = False,
    note: str | None = None,
    author: str | None = None,
    now: str | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "close")
    binding = require_rust_binding("bead_close")
    resolution_value = (
        resolution.value if isinstance(resolution, Resolution) else resolution
    )
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        issue_ids,
        reason,
        resolution_value,
        force,
        now,
        note,
        author,
    )
    return issues_from_list(payload.get("issues", [])), payload


def open_issue(
    beads_dir: Path | str,
    issue_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "open")
    binding = require_rust_binding("bead_open")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, now)
    return _issue_payload(payload), payload


def remove(
    beads_dir: Path | str,
    issue_id: str,
) -> tuple[list[Issue], dict[str, Any]]:
    return remove_many(beads_dir, [issue_id])


def remove_many(
    beads_dir: Path | str,
    issue_ids: list[str],
) -> tuple[list[Issue], dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "remove_many")
    binding = require_rust_binding("bead_remove_many")
    payload = _call_issue_operation(binding, str(beads_dir), issue_ids)
    return issues_from_list(payload.get("issues", [])), payload


def add_dependency(
    beads_dir: Path | str,
    issue_id: str,
    depends_on_id: str,
    *,
    now: str | None = None,
) -> tuple[Dependency, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "add_dependency")
    binding = require_rust_binding("bead_dep_add")
    payload = _call_issue_operation(
        binding, str(beads_dir), issue_id, depends_on_id, now
    )
    dep = payload["dependency"]
    return (
        Dependency(
            issue_id=str(dep["issue_id"]),
            depends_on_id=str(dep["depends_on_id"]),
            created_at=str(dep.get("created_at", "")),
            created_by=str(dep.get("created_by", "")),
        ),
        payload,
    )


def remove_dependencies(
    beads_dir: Path | str,
    issue_id: str,
    depends_on_ids: list[str],
    *,
    now: str | None = None,
) -> tuple[list[Dependency], dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "remove_dependencies")
    binding = require_rust_binding("bead_dep_remove")
    payload = _call_issue_operation(
        binding, str(beads_dir), issue_id, depends_on_ids, now
    )
    return (
        [
            Dependency(
                issue_id=str(dep["issue_id"]),
                depends_on_id=str(dep["depends_on_id"]),
                created_at=str(dep.get("created_at", "")),
                created_by=str(dep.get("created_by", "")),
            )
            for dep in payload.get("dependencies", [])
        ],
        payload,
    )


def mark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "mark_ready_to_work")
    binding = require_rust_binding("bead_mark_ready_to_work")
    payload = _call_issue_operation(binding, str(beads_dir), epic_id, now)
    return _issue_payload(payload), payload


def unmark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "unmark_ready_to_work")
    binding = require_rust_binding("bead_unmark_ready_to_work")
    payload = _call_issue_operation(binding, str(beads_dir), epic_id, now)
    return _issue_payload(payload), payload


def export_jsonl(beads_dir: Path | str) -> dict[str, Any]:
    _guard_bead_store_write(beads_dir, "export_jsonl")
    binding = require_rust_binding("bead_export_jsonl")
    return dict(binding(str(beads_dir)))


def _guard_bead_store_write(beads_dir: Path | str, operation: str) -> None:
    assert_bead_store_write_sandboxed(beads_dir, operation=operation)


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


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


__all__ = [
    "add_dependency",
    "append_note",
    "claim_for_agent_launch",
    "claim_for_agent_wait",
    "close",
    "create",
    "export_jsonl",
    "init_store",
    "mark_ready_to_work",
    "open_issue",
    "release_agent_claim",
    "remove",
    "remove_dependencies",
    "remove_many",
    "unmark_ready_to_work",
    "update",
]
