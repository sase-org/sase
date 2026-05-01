"""Python facade for Rust-backed bead mutation operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import Dependency, Issue, IssueType
from sase.bead.project import AlreadyReadyError, NotAPlanError
from sase.core.bead_wire import issue_from_dict, issue_type_value, issues_from_list
from sase.core.rust import require_rust_binding


# pyvision: public_api_methods.txt
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
    parent_id: str | None = None,
    description: str = "",
    notes: str = "",
    design: str = "",
    assignee: str = "",
    changespec_name: str | int | None = "",
    changespec_bug_id: str | int | None = "",
    now: str | None = None,
    workspace_beads_dirs: list[Path] | list[str] | None = None,
) -> tuple[Issue, dict[str, Any]]:
    binding = require_rust_binding("bead_create")
    payload = _call_issue_operation(
        binding,
        str(beads_dir),
        {
            "title": title,
            "issue_type": issue_type_value(issue_type),
            "parent_id": parent_id,
            "description": description,
            "notes": notes,
            "design": design,
            "assignee": assignee,
            "changespec_name": _optional_text(changespec_name),
            "changespec_bug_id": _optional_text(changespec_bug_id),
            "now": now,
            "workspace_beads_dirs": _path_strings(workspace_beads_dirs or []),
        },
    )
    return _issue_payload(payload), payload


def update(
    beads_dir: Path | str,
    issue_id: str,
    **fields: str | int | bool | None,
) -> tuple[Issue, dict[str, Any]]:
    binding = require_rust_binding("bead_update")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, fields)
    return _issue_payload(payload), payload


def open_issue(
    beads_dir: Path | str,
    issue_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    binding = require_rust_binding("bead_open")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id, now)
    return _issue_payload(payload), payload


def close(
    beads_dir: Path | str,
    issue_ids: list[str],
    *,
    reason: str | None = None,
    now: str | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    binding = require_rust_binding("bead_close")
    payload = _call_issue_operation(binding, str(beads_dir), issue_ids, reason, now)
    return issues_from_list(payload.get("issues", [])), payload


def remove(
    beads_dir: Path | str,
    issue_id: str,
) -> tuple[list[Issue], dict[str, Any]]:
    binding = require_rust_binding("bead_remove")
    payload = _call_issue_operation(binding, str(beads_dir), issue_id)
    return issues_from_list(payload.get("issues", [])), payload


def add_dependency(
    beads_dir: Path | str,
    issue_id: str,
    depends_on_id: str,
    *,
    now: str | None = None,
) -> tuple[Dependency, dict[str, Any]]:
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


def mark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    binding = require_rust_binding("bead_mark_ready_to_work")
    payload = _call_issue_operation(binding, str(beads_dir), epic_id, now)
    return _issue_payload(payload), payload


def unmark_ready_to_work(
    beads_dir: Path | str,
    epic_id: str,
    *,
    now: str | None = None,
) -> tuple[Issue, dict[str, Any]]:
    binding = require_rust_binding("bead_unmark_ready_to_work")
    payload = _call_issue_operation(binding, str(beads_dir), epic_id, now)
    return _issue_payload(payload), payload


# pyvision: public_api_methods.txt
def export_jsonl(beads_dir: Path | str) -> dict[str, Any]:
    binding = require_rust_binding("bead_export_jsonl")
    return dict(binding(str(beads_dir)))


# pyvision: public_api_methods.txt
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


def _path_strings(paths: list[Path] | list[str]) -> list[str]:
    return [str(path) for path in paths]


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


__all__ = [
    "add_dependency",
    "close",
    "create",
    "export_jsonl",
    "init_store",
    "mark_ready_to_work",
    "open_issue",
    "remove",
    "sync_is_clean",
    "unmark_ready_to_work",
    "update",
]
