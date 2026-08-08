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
    refs: list[str] | tuple[str, ...] = (),
    assignee: str = "",
    patch_name: str | int | None = None,
    patch_bug_id: str | int | None = None,
    changespec_name: str | int | None = "",
    changespec_bug_id: str | int | None = "",
    model: str = "",
    size: PhaseSize | str | None = None,
    created_by: str | None = None,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "create")
    binding = require_rust_binding("bead_create")
    changespec_name = _resolve_patch_alias(
        patch_name,
        changespec_name,
        canonical_name="patch_name",
        legacy_name="changespec_name",
    )
    changespec_bug_id = _resolve_patch_alias(
        patch_bug_id,
        changespec_bug_id,
        canonical_name="patch_bug_id",
        legacy_name="changespec_bug_id",
    )
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
            "refs": list(refs),
            "assignee": assignee,
            "changespec_name": _optional_text(changespec_name),
            "changespec_bug_id": _optional_text(changespec_bug_id),
            "model": model,
            "size": None if size is None else phase_size_value(size),
            "created_by": created_by,
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
    fields = _normalize_patch_field_aliases(fields)
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, fields)
    return _issue_payload(payload), payload


def update_many(
    beads_dir: Path | str,
    issue_ids: list[str],
    **fields: str | int | bool | None,
) -> tuple[list[Issue], dict[str, Any]]:
    _guard_bead_store_write(beads_dir, "update_many")
    binding = require_rust_binding("bead_update_many")
    fields = _normalize_patch_field_aliases(fields)
    payload = _call_issue_operation(binding, str(beads_dir), issue_ids, fields)
    return issues_from_list(payload.get("issues", [])), payload


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


def plus_one(
    beads_dir: Path | str,
    issue_id: str,
    *,
    reporter: str,
    note: str,
    refs: list[str] | tuple[str, ...] = (),
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    """Append one structured, independently attributed task report."""
    _guard_bead_store_write(beads_dir, "plus_one")
    binding = require_rust_binding("bead_plus_one")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        issue_id,
        reporter,
        note,
        list(refs),
        now,
    )
    return _issue_payload(payload), payload


def snooze(
    beads_dir: Path | str,
    issue_id: str,
    *,
    until: str,
    plus_ones: int | None = None,
    reason: str = "",
    actor: str,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    """Defer one task bead until ``until``, or until a +1 threshold."""
    _guard_bead_store_write(beads_dir, "snooze")
    binding = require_rust_binding("bead_snooze")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        issue_id,
        until,
        plus_ones,
        reason,
        actor,
        now,
    )
    return _issue_payload(payload), payload


def cancel_snooze(
    beads_dir: Path | str,
    issue_id: str,
    *,
    actor: str,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    """Undo a snooze, returning the bead to ``ready``."""
    _guard_bead_store_write(beads_dir, "cancel_snooze")
    binding = require_rust_binding("bead_snooze_cancel")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, actor, now)
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


def preclaim_epic_work(
    beads_dir: Path | str,
    epic_id: str,
    assignments: list[tuple[str, str]],
    *,
    land_agent_name: str,
    now: str | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    """Assign every rendered phase and the epic before agent launch."""
    _guard_bead_store_write(beads_dir, "preclaim_epic_work")
    binding = require_rust_binding("bead_preclaim_epic_work")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        epic_id,
        [
            {"bead_id": bead_id, "agent_name": agent_name}
            for bead_id, agent_name in assignments
        ],
        land_agent_name,
        now,
    )
    return issues_from_list(payload.get("issues", [])), payload


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


def _optional_text(value: str | int | bool | None) -> str:
    return "" if value is None else str(value)


def _resolve_patch_alias(
    canonical_value: str | int | bool | None,
    legacy_value: str | int | bool | None,
    *,
    canonical_name: str,
    legacy_name: str,
) -> str:
    legacy_text = _optional_text(legacy_value)
    if canonical_value is None:
        return legacy_text
    canonical_text = _optional_text(canonical_value)
    if canonical_text and legacy_text and canonical_text != legacy_text:
        raise ValueError(f"{canonical_name} conflicts with {legacy_name}")
    return canonical_text or legacy_text


def _normalize_patch_field_aliases(
    fields: dict[str, str | int | bool | None],
) -> dict[str, str | int | bool | None]:
    normalized = dict(fields)
    for canonical_name, legacy_name in (
        ("patch_name", "changespec_name"),
        ("patch_bug_id", "changespec_bug_id"),
    ):
        canonical_value = normalized.pop(canonical_name, None)
        if canonical_value is None:
            continue
        normalized[legacy_name] = _resolve_patch_alias(
            canonical_value,
            normalized.get(legacy_name),
            canonical_name=canonical_name,
            legacy_name=legacy_name,
        )
    return normalized


__all__ = [
    "add_dependency",
    "append_note",
    "cancel_snooze",
    "claim_for_agent_launch",
    "claim_for_agent_wait",
    "close",
    "create",
    "export_jsonl",
    "init_store",
    "mark_ready_to_work",
    "open_issue",
    "preclaim_epic_work",
    "release_agent_claim",
    "remove",
    "remove_dependencies",
    "remove_many",
    "snooze",
    "unmark_ready_to_work",
    "update",
    "update_many",
]
