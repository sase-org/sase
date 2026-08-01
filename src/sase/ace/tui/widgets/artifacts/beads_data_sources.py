"""Off-thread sources used by the Artifacts Beads snapshot loader."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.bead.model import Issue
from sase.plan_documents import PlanWorkspace, resolve_plan_path

from .beads_data_models import PendingTriage
from .plans_data_models import PlansProject
from .plans_data_sources import (
    hierarchical_id_key,
    project_beads_dir,
    project_document_roots,
    resolve_projects,
    timestamp_recency_key,
)


def load_project_beads(
    beads_dir: Path,
) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
    """Read one bead store entirely through the Rust-backed facade."""
    from sase.core import bead_read_facade

    issues = bead_read_facade.list_issues(beads_dir)
    ready_ids = frozenset(issue.id for issue in bead_read_facade.ready(beads_dir))
    blocked_ids = frozenset(issue.id for issue in bead_read_facade.blocked(beads_dir))
    return issues, ready_ids, blocked_ids


def store_mtime_key(beads_dir: Path | None) -> tuple[tuple[str, int, int], ...]:
    """Return a content-sensitive key without parsing the bead store."""
    if beads_dir is None:
        return ()
    paths: list[Path] = [beads_dir / "issues.jsonl", beads_dir / "config.json"]
    events_dir = beads_dir / "events"
    if events_dir.is_dir():
        paths.extend(path for path in events_dir.rglob("*") if path.is_file())
    return _path_mtime_key(paths)


def notifications_mtime_key() -> tuple[tuple[str, int, int], ...]:
    """Return the notification-store signature used by triage matching."""
    from sase.notifications.store import notifications_file_path

    return _path_mtime_key((notifications_file_path(),))


def load_pending_triage() -> dict[tuple[str, str], PendingTriage]:
    """Match pending TaskTriage gates by their trusted request payload."""
    from sase.notification_gates.paths import resolve_notification_bundle
    from sase.notifications.store import load_notifications

    matches: dict[tuple[str, str], PendingTriage] = {}
    for notification in load_notifications(include_dismissed=False):
        if notification.action != "TaskTriage":
            continue
        try:
            bundle = resolve_notification_bundle(notification)
            if bundle is None:
                continue
            envelope = json.loads(bundle.request.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if not isinstance(envelope, Mapping):
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping):
            continue
        bead_id = payload.get("bead_id")
        project = payload.get("project")
        if not isinstance(bead_id, str) or not bead_id.strip():
            continue
        if not isinstance(project, str) or not project.strip():
            continue
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            request_id = notification.action_data.get("request_id", "")
        created_at = envelope.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            created_at = notification.timestamp
        key = (project, bead_id)
        candidate = PendingTriage(
            notification_id=notification.id,
            request_id=request_id,
            created_at=created_at,
        )
        previous = matches.get(key)
        if previous is None or (candidate.created_at, candidate.notification_id) > (
            previous.created_at,
            previous.notification_id,
        ):
            matches[key] = candidate
    return matches


def resolve_plan_link(
    reference: str,
    *,
    workspace_dir: str | None,
    plans_root: Path | None,
) -> str:
    """Resolve a bead's design reference without reading the document body."""
    value = reference.strip()
    if not value or plans_root is None:
        return ""
    try:
        resolved = resolve_plan_path(
            value,
            workspaces=(
                PlanWorkspace(
                    workspace_dir=workspace_dir or "",
                    plans_root=str(plans_root),
                ),
            ),
        )
    except (OSError, RuntimeError, ValueError):
        return ""
    if resolved.status != "success" or resolved.path is None:
        return ""
    return str(resolved.path)


def _path_mtime_key(paths: object) -> tuple[tuple[str, int, int], ...]:
    keyed: list[tuple[str, int, int]] = []
    for path in sorted(set(paths)):  # type: ignore[call-overload]
        try:
            stat = path.stat()
        except OSError:
            continue
        keyed.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(keyed)


# Stable private aliases keep the data module easy to patch in focused tests.
_hierarchical_id_key = hierarchical_id_key
_project_beads_dir = project_beads_dir
_project_document_roots = project_document_roots
_resolve_projects = resolve_projects
_timestamp_recency_key = timestamp_recency_key


__all__ = [
    "load_pending_triage",
    "load_project_beads",
    "notifications_mtime_key",
    "resolve_plan_link",
    "store_mtime_key",
]
