"""Result types and small stateless helpers shared by monitor resume's
decision and delivery logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from sase.continuation_capture import (
    AuthoredCheckpoint,
    AuthoredCheckpointError,
    load_authored_checkpoint,
)

from .logs import monitor_log_path
from .models import MonitorError, MonitorRecord
from .output import OutputCapture


class MonitorResumeError(MonitorError):
    """A monitor cannot be resumed safely."""

    def __init__(
        self,
        message: str,
        *,
        suggested_command: str | None = None,
        code: str = "not_resumable",
    ) -> None:
        super().__init__(message)
        self.suggested_command = suggested_command
        self.code = code


@dataclass(frozen=True, slots=True)
class MonitorResumeResult:
    """Result of a monitor resume or terminal delivery reconciliation."""

    monitor_id: str
    branch: str
    agent_name: str | None
    delivery_disposition: str | None
    launched: bool
    spawned: bool
    manual_revision: bool = False
    reused_revision: bool = False
    ownership_outcome: str = "unknown"
    message: str = ""


def selected_model(meta: Mapping[str, Any], model: str | None) -> str | None:
    if model is not None:
        stripped = model.strip()
        return stripped or None
    existing = meta.get("monitor_next_model")
    return existing if isinstance(existing, str) and existing.strip() else None


def load_checkpoint(path: str | None) -> AuthoredCheckpoint | None:
    if not path:
        return None
    try:
        return load_authored_checkpoint(path)
    except AuthoredCheckpointError:
        raise


def capture_from_log(record: MonitorRecord) -> OutputCapture:
    capture = OutputCapture()
    path = (
        Path(record.output_path)
        if record.output_path
        else monitor_log_path(record.artifacts_dir)
    )
    for candidate in (path.with_name(f"{path.name}.1"), path):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        if data:
            capture.append_bytes(data)
    return capture


def elapsed_seconds(meta: Mapping[str, Any]) -> float:
    started = _parse_time(meta.get("run_started_at"))
    stopped = _parse_time(meta.get("stopped_at"))
    if started is None or stopped is None:
        return 0.0
    return max(0.0, (stopped - started).total_seconds())


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def conditional_completion_state(
    meta: Mapping[str, Any],
    record: MonitorRecord,
) -> bool:
    status = meta.get("monitor_host_completion_status") or record.host_completion_status
    if isinstance(status, str) and status:
        return True
    return False


def capture_needs_recovery(meta: Mapping[str, Any]) -> bool:
    return str(meta.get("continuation_capture_disposition") or "") == "needs_recovery"


def read_meta(artifacts_dir: str) -> dict[str, Any]:
    return read_json_object(Path(artifacts_dir) / "agent_meta.json")


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "capture_from_log",
    "capture_needs_recovery",
    "conditional_completion_state",
    "elapsed_seconds",
    "load_checkpoint",
    "read_json_object",
    "read_meta",
    "selected_model",
    "utc_now_iso",
]
