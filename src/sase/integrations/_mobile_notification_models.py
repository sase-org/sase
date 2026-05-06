"""Shared models for the mobile notification bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MobileNotificationBridgeCounts:
    priority: int = 0
    rest: int = 0
    muted: int = 0


@dataclass(frozen=True)
class MobileNotificationBridgeRow:
    id: str
    timestamp: str
    sender: str
    priority: bool
    notes: list[str] = field(default_factory=list)
    display_files: list[str] = field(default_factory=list)
    host_files: list[str] = field(default_factory=list)
    action: str | None = None
    action_state: str = "unsupported"
    display_action_data: dict[str, str] = field(default_factory=dict)
    host_action_data: dict[str, str] = field(default_factory=dict)
    read: bool = False
    dismissed: bool = False
    silent: bool = False
    muted: bool = False
    snooze_until: str | None = None


@dataclass(frozen=True)
class MobileAttachmentManifest:
    id: str
    token: str | None
    display_name: str
    kind: str
    content_type: str | None
    byte_size: int | None
    source_notification_id: str
    downloadable: bool
    download_requires_auth: bool
    can_inline: bool
    path_available: bool


@dataclass(frozen=True)
class MobileNotificationBridgeSnapshot:
    rows: list[MobileNotificationBridgeRow] = field(default_factory=list)
    counts: MobileNotificationBridgeCounts = field(
        default_factory=MobileNotificationBridgeCounts
    )
    expired_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MobilePlanActionResult:
    prefix: str
    notification_id: str
    response_file: str
    response_json: dict[str, Any]
    message: str


class MobilePlanActionError(RuntimeError):
    """Deterministic host-side plan action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target
