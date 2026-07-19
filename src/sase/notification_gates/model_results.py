"""Creation and execution result models for notification gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.model_validation import GateError, json_object


@dataclass(frozen=True)
class GateCreationResult:
    """Stable machine-readable result returned after durable creation."""

    schema_version: int
    notification_id: str | None
    request_id: str
    kind: str
    bundle_path: Path
    request_path: Path
    response_path: Path
    preview_path: Path | None
    continuation_mode: str
    auto_resolution: dict[str, Any]
    hashes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "notification_id": self.notification_id,
            "request_id": self.request_id,
            "kind": self.kind,
            "bundle_path": str(self.bundle_path),
            "request_path": str(self.request_path),
            "response_path": str(self.response_path),
            "preview_path": (
                None if self.preview_path is None else str(self.preview_path)
            ),
            "continuation_mode": self.continuation_mode,
            "auto_resolution": self.auto_resolution,
            "hashes": self.hashes,
        }

    @classmethod
    def from_mapping(cls, value: object) -> GateCreationResult:
        data = json_object(value, "creation result")
        preview_path = data.get("preview_path")
        notification_id = data.get("notification_id")
        if notification_id is not None and not isinstance(notification_id, str):
            raise GateError(
                "invalid_state", "notification_id", "notification_id must be a string"
            )
        if preview_path is not None and not isinstance(preview_path, str):
            raise GateError(
                "invalid_state", "preview_path", "preview_path must be a string"
            )
        return cls(
            schema_version=int(data["schema_version"]),
            notification_id=notification_id,
            request_id=str(data["request_id"]),
            kind=str(data["kind"]),
            bundle_path=Path(str(data["bundle_path"])),
            request_path=Path(str(data["request_path"])),
            response_path=Path(str(data["response_path"])),
            preview_path=None if preview_path is None else Path(preview_path),
            continuation_mode=str(data["continuation_mode"]),
            auto_resolution=json_object(
                data.get("auto_resolution", {}), "auto_resolution"
            ),
            hashes=json_object(data.get("hashes", {}), "hashes"),
        )


@dataclass(frozen=True)
class GateExecutionResult:
    """Result of resolving a terminal gate choice."""

    response: dict[str, Any]
    already_completed: bool = False
