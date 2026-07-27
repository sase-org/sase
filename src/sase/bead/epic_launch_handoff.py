"""Durable handoff for planner completion notifications during epic launch."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_subdir
from sase.logs._bounded import log_file_lock


EPIC_COMPLETION_GRACE_SECONDS = 90
EPIC_COMPLETION_SETTLED_TTL_SECONDS = 60 * 60
_EPIC_LAUNCH_TAGS = frozenset({"epic", "launch"})


@dataclass(frozen=True)
class CompletionNotificationPayload:
    """Serializable arguments for ``notify_workflow_complete``."""

    sender: str
    cl_name: str | None
    success: bool
    notes: list[str]
    action: str | None
    action_data: dict[str, str]
    extra_files: list[str]
    silent: bool
    tags: list[str] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender": self.sender,
            "cl_name": self.cl_name,
            "success": self.success,
            "notes": list(self.notes),
            "action": self.action,
            "action_data": dict(self.action_data),
            "extra_files": list(self.extra_files),
            "silent": self.silent,
            "tags": list(self.tags) if self.tags is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CompletionNotificationPayload:
        tags = value.get("tags")
        return cls(
            sender=str(value["sender"]),
            cl_name=(
                str(value["cl_name"]) if value.get("cl_name") is not None else None
            ),
            success=bool(value["success"]),
            notes=[str(item) for item in value.get("notes") or []],
            action=(str(value["action"]) if value.get("action") is not None else None),
            action_data={
                str(key): str(item)
                for key, item in dict(value.get("action_data") or {}).items()
            },
            extra_files=[str(item) for item in value.get("extra_files") or []],
            silent=bool(value.get("silent", False)),
            tags=([str(item) for item in tags] if isinstance(tags, list) else None),
        )


@dataclass(frozen=True)
class _DeferredCompletion:
    """One claimed planner completion notification."""

    key: str
    artifacts_dir: str
    created_at: str
    plan_file: str | None
    payload: CompletionNotificationPayload

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "artifacts_dir": self.artifacts_dir,
            "created_at": self.created_at,
            **({"plan_file": self.plan_file} if self.plan_file else {}),
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> _DeferredCompletion:
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("deferred epic completion payload is not an object")
        return cls(
            key=str(value["key"]),
            artifacts_dir=str(value["artifacts_dir"]),
            created_at=str(value["created_at"]),
            plan_file=(
                str(value["plan_file"]) if value.get("plan_file") is not None else None
            ),
            payload=CompletionNotificationPayload.from_dict(payload),
        )


@dataclass(frozen=True)
class _EpicCompletionSweepResult:
    """Counts from one orphaned-completion sweep."""

    pending_scanned: int = 0
    active: int = 0
    young: int = 0
    flushed: int = 0
    settled_reaped: int = 0
    errors: int = 0


def _epic_completion_key(artifacts_dir: str | Path | None) -> str | None:
    """Return the workflow-independent planner identity for an artifact path."""
    if artifacts_dir is None:
        return None
    try:
        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        return None
    if info is None:
        return None
    return f"{info.project_name}__{info.timestamp}"


def defer_epic_completion(
    artifacts_dir: str | Path | None,
    payload: CompletionNotificationPayload,
) -> bool:
    """Persist *payload* until epic launch settles.

    Returns ``True`` only when the notification was safely deferred. Any
    unusable identity or store failure returns ``False`` so the caller sends
    immediately.
    """
    key = _epic_completion_key(artifacts_dir)
    if key is None or artifacts_dir is None:
        return False
    pending_path, settled_path = _handoff_paths(key)
    try:
        with log_file_lock(pending_path):
            if settled_path.exists():
                _read_json_object(settled_path)
                settled_path.unlink()
                return False
            deferred = _DeferredCompletion(
                key=key,
                artifacts_dir=str(artifacts_dir),
                created_at=_utc_now(),
                plan_file=_read_plan_file(artifacts_dir),
                payload=payload,
            )
            _write_json_atomic(pending_path, deferred.to_dict())
        return True
    except Exception:
        return False


def claim_epic_completion(
    artifacts_dir: str | Path | None,
    *,
    outcome: Mapping[str, Any],
) -> _DeferredCompletion | None:
    """Claim a deferred completion or leave a marker for a later runner."""
    key = _epic_completion_key(artifacts_dir)
    if key is None:
        return None
    pending_path, settled_path = _handoff_paths(key)
    try:
        with log_file_lock(pending_path):
            if pending_path.exists():
                deferred = _DeferredCompletion.from_dict(
                    _read_json_object(pending_path)
                )
                pending_path.unlink()
                return deferred
            settled = dict(outcome)
            settled.setdefault("settled_at", _utc_now())
            _write_json_atomic(settled_path, settled)
    except Exception:
        return None
    return None


def send_completion_payload(payload: CompletionNotificationPayload) -> None:
    """Send a previously serialized completion notification."""
    from sase.notifications.senders import notify_workflow_complete

    notify_workflow_complete(**payload.to_dict())


def fold_epic_launch_outcome(
    deferred: _DeferredCompletion,
    *,
    success: bool,
    epic_id: str | None,
    plan_file: str,
    archived_plan_path: str | Path | None,
    detail: str,
    resume_argv: list[str],
) -> CompletionNotificationPayload:
    """Append the launch result to a planner completion payload."""
    payload = deferred.payload
    notes = list(payload.notes)
    if success:
        notes.extend(
            [
                f"Epic {epic_id} launched from {Path(plan_file).name}",
                f"Plan: {archived_plan_path or plan_file}",
            ]
        )
        tags = payload.tags
    else:
        notes.extend(
            [
                f"Epic launch failed: {detail}",
                f"Resume with: {shlex.join(resume_argv)}",
            ]
        )
        tags = [tag for tag in payload.tags or [] if tag != "done"] or None
    return replace(
        payload,
        success=success,
        notes=notes,
        action="JumpToAgent",
        tags=tags,
    )


def flush_orphaned_deferrals(
    *,
    now: datetime | None = None,
    grace_seconds: int = EPIC_COMPLETION_GRACE_SECONDS,
    settled_ttl_seconds: int = EPIC_COMPLETION_SETTLED_TTL_SECONDS,
) -> _EpicCompletionSweepResult:
    """Flush old unowned deferrals and reap stale settle markers."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    active_keys = _active_epic_launch_keys()
    store_dir = _epic_completion_store_dir()
    try:
        pending_paths = list(store_dir.glob("*.pending.json"))
        settled_paths = list(store_dir.glob("*.settled.json"))
    except Exception:
        return _EpicCompletionSweepResult(errors=1)

    result = _EpicCompletionSweepResult()
    for pending_path in pending_paths:
        result = replace(result, pending_scanned=result.pending_scanned + 1)
        try:
            with log_file_lock(pending_path):
                if not pending_path.exists():
                    continue
                deferred = _DeferredCompletion.from_dict(
                    _read_json_object(pending_path)
                )
                age_seconds = _age_seconds(deferred.created_at, reference)
                if age_seconds < grace_seconds:
                    result = replace(result, young=result.young + 1)
                    continue
                if deferred.key in active_keys:
                    result = replace(result, active=result.active + 1)
                    continue
                pending_path.unlink()
            payload = _unknown_outcome_payload(deferred)
            try:
                send_completion_payload(payload)
            except Exception:
                _restore_pending(pending_path, deferred)
                raise
            result = replace(result, flushed=result.flushed + 1)
        except Exception:
            result = replace(result, errors=result.errors + 1)

    for settled_path in settled_paths:
        pending_path = settled_path.with_name(
            settled_path.name.removesuffix(".settled.json") + ".pending.json"
        )
        try:
            with log_file_lock(pending_path):
                if not settled_path.exists():
                    continue
                settled = _read_json_object(settled_path)
                settled_at = str(settled["settled_at"])
                if _age_seconds(settled_at, reference) < settled_ttl_seconds:
                    continue
                settled_path.unlink()
            result = replace(
                result,
                settled_reaped=result.settled_reaped + 1,
            )
        except Exception:
            result = replace(result, errors=result.errors + 1)
    return result


def _epic_completion_store_dir() -> Path:
    return sase_subdir("notifications") / "epic_completions"


def _handoff_paths(key: str) -> tuple[Path, Path]:
    store_dir = _epic_completion_store_dir()
    return (
        store_dir / f"{key}.pending.json",
        store_dir / f"{key}.settled.json",
    )


def _read_plan_file(artifacts_dir: str | Path) -> str | None:
    try:
        value = _read_json_object(Path(artifacts_dir) / "plan_path.json").get(
            "plan_path"
        )
    except Exception:
        return None
    return str(value) if isinstance(value, str) and value else None


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(value), stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _restore_pending(path: Path, deferred: _DeferredCompletion) -> None:
    try:
        with log_file_lock(path):
            if not path.exists():
                _write_json_atomic(path, deferred.to_dict())
    except Exception:
        pass


def _active_epic_launch_keys() -> set[str]:
    from sase.tasks import ACTIVE_TASK_STATUSES, DETACHED_TASK_KIND, read_tasks

    try:
        tasks = read_tasks(
            status=ACTIVE_TASK_STATUSES,
            kind=DETACHED_TASK_KIND,
        )
    except Exception:
        return set()
    keys: set[str] = set()
    for task in tasks:
        if not _EPIC_LAUNCH_TAGS.issubset(task.tags):
            continue
        artifacts_dir = _command_option(task.command, "--artifacts-dir")
        key = _epic_completion_key(artifacts_dir)
        if key is not None:
            keys.add(key)
    return keys


def _command_option(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
        return command[index + 1]
    except (ValueError, IndexError):
        return None


def _unknown_outcome_payload(
    deferred: _DeferredCompletion,
) -> CompletionNotificationPayload:
    from sase.bead.epic_launch import build_epic_launch_argv

    plan_file = deferred.plan_file or "<approved-plan>"
    argv = build_epic_launch_argv(
        plan_file,
        artifacts_dir=deferred.artifacts_dir,
        cl_name=deferred.payload.cl_name,
        yes_to_all=False,
    )
    tags = [tag for tag in deferred.payload.tags or [] if tag != "done"] or None
    return replace(
        deferred.payload,
        success=False,
        notes=[
            *deferred.payload.notes,
            "Epic launch outcome is unknown.",
            f"Resume with: {shlex.join(argv)}",
        ],
        action="JumpToAgent",
        tags=tags,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _age_seconds(timestamp: str, now: datetime) -> float:
    created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0.0, (now.astimezone(UTC) - created.astimezone(UTC)).total_seconds())


__all__ = [
    "CompletionNotificationPayload",
    "EPIC_COMPLETION_GRACE_SECONDS",
    "EPIC_COMPLETION_SETTLED_TTL_SECONDS",
    "claim_epic_completion",
    "defer_epic_completion",
    "flush_orphaned_deferrals",
    "fold_epic_launch_outcome",
    "send_completion_payload",
]
