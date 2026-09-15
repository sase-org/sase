"""Data models for epic launch completion handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


EPIC_COMPLETION_GRACE_SECONDS = 90
EPIC_COMPLETION_SETTLED_TTL_SECONDS = 60 * 60
MONITOR_ARTIFACTS_ENV = "SASE_MONITOR_ARTIFACTS_DIR"
EPIC_LAUNCH_TAGS = frozenset({"epic", "launch"})


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
class DeferredCompletion:
    """One claimed planner completion notification."""

    key: str
    artifacts_dir: str
    created_at: str
    plan_file: str | None
    payload: CompletionNotificationPayload
    resume_argv: tuple[str, ...] = ()
    notification_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "artifacts_dir": self.artifacts_dir,
            "created_at": self.created_at,
            **({"plan_file": self.plan_file} if self.plan_file else {}),
            **({"resume_argv": list(self.resume_argv)} if self.resume_argv else {}),
            **(
                {"notification_id": self.notification_id}
                if self.notification_id
                else {}
            ),
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DeferredCompletion:
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("deferred epic completion payload is not an object")
        raw_resume_argv = value.get("resume_argv")
        return cls(
            key=str(value["key"]),
            artifacts_dir=str(value["artifacts_dir"]),
            created_at=str(value["created_at"]),
            plan_file=(
                str(value["plan_file"]) if value.get("plan_file") is not None else None
            ),
            payload=CompletionNotificationPayload.from_dict(payload),
            resume_argv=(
                tuple(str(item) for item in raw_resume_argv)
                if isinstance(raw_resume_argv, list)
                else ()
            ),
            notification_id=nonempty_str(value.get("notification_id")),
        )


@dataclass(frozen=True)
class EpicCompletionSweepResult:
    """Counts from one orphaned-completion sweep."""

    pending_scanned: int = 0
    active: int = 0
    young: int = 0
    flushed: int = 0
    settled_reaped: int = 0
    errors: int = 0


MonitorCompletionPublishStatus = Literal[
    "none",
    "published",
    "already_published",
    "failed",
]


def nonempty_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "CompletionNotificationPayload",
    "DeferredCompletion",
    "EPIC_COMPLETION_GRACE_SECONDS",
    "EPIC_COMPLETION_SETTLED_TTL_SECONDS",
    "EpicCompletionSweepResult",
    "MONITOR_ARTIFACTS_ENV",
    "MonitorCompletionPublishStatus",
]
