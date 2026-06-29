"""One-shot post-update toast handoff for ACE restarts.

This is TUI-restart presentation state, not shared domain behavior. The old
ACE process writes a tiny receipt immediately before re-execing into freshly
updated code; the new ACE process consumes that receipt after first paint and
renders a transient confirmation toast. No CLI, web client, editor integration,
or Rust core API needs to share this handoff.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.paths import sase_home
from sase.dev_update.models import DevUpdateOutcome, DevUpdateResult
from sase.uv_tool.render import UpdateOutcome, UpdateSummary
from sase.version._utils import normalize_distribution_name

log = logging.getLogger(__name__)

_FORMAT_VERSION = 1
_MAX_PLUGIN_LINES = 3
_FRESHNESS_SECONDS = 30 * 60
_PRIMARY_DIST_KEY = normalize_distribution_name("sase")

# Test override for the backing file. ``None`` falls back to the per-user path
# under ``sase_home()``, matching the small-state helpers in this package.
_PENDING_UPDATE_TOAST_FILE: Path | None = None

ReceiptKind = Literal["managed", "dev"]


@dataclass(frozen=True)
class UpdateVersionTransition:
    """A package version transition rendered by the post-update toast."""

    name: str
    old: str | None
    new: str | None


@dataclass(frozen=True)
class UpdateToastReceipt:
    """Serializable receipt consumed once by the restarted ACE process."""

    kind: ReceiptKind
    created_at: float
    primary: UpdateVersionTransition | None
    plugins: tuple[UpdateVersionTransition, ...] = ()
    plugin_overflow: int = 0
    dependency_count: int = 0
    format: int = _FORMAT_VERSION


def build_update_receipt(
    payload: object, *, created_at: float | None = None
) -> UpdateToastReceipt | None:
    """Normalize a managed or dev update payload into a toast receipt."""
    timestamp = time.time() if created_at is None else float(created_at)
    if isinstance(payload, UpdateSummary):
        return _build_managed_receipt(payload, created_at=timestamp)
    if isinstance(payload, DevUpdateResult):
        return _build_dev_receipt(payload, created_at=timestamp)
    return None


def write_pending_update_toast(receipt: UpdateToastReceipt) -> bool:
    """Atomically persist *receipt* for the next ACE process, best-effort."""
    path = _pending_update_toast_file()
    tmp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(_receipt_to_json(receipt), tmp, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError:
        log.debug("Failed to persist pending update toast", exc_info=True)
        if tmp_path is not None:
            _safe_unlink(tmp_path)
        return False


def read_and_clear_pending_update_toast(
    *, now: float | None = None
) -> UpdateToastReceipt | None:
    """Read and delete the pending update toast receipt, if one is valid."""
    path = _pending_update_toast_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        log.debug("Failed to read pending update toast", exc_info=True)
        _safe_unlink(path)
        return None

    _safe_unlink(path)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        log.debug("Ignoring malformed pending update toast", exc_info=True)
        return None

    receipt = _receipt_from_json(payload)
    if receipt is None:
        return None
    current = time.time() if now is None else float(now)
    if abs(current - receipt.created_at) > _FRESHNESS_SECONDS:
        return None
    return receipt


def _pending_update_toast_file() -> Path:
    return _PENDING_UPDATE_TOAST_FILE or sase_home() / "pending_update_toast.json"


def _build_managed_receipt(
    summary: UpdateSummary, *, created_at: float
) -> UpdateToastReceipt | None:
    primary = next(
        (
            _transition_from_update_outcome(outcome)
            for outcome in summary.updated
            if outcome.role == "primary"
        ),
        None,
    )
    plugin_transitions = [
        _transition_from_update_outcome(outcome)
        for outcome in summary.updated
        if outcome.role == "plugin"
    ]
    plugins, plugin_overflow = _cap_plugin_transitions(plugin_transitions)
    dependency_count = len(summary.updated_dependencies)
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        dependency_count=dependency_count,
    )


def _build_dev_receipt(
    result: DevUpdateResult, *, created_at: float
) -> UpdateToastReceipt | None:
    updated = tuple(
        outcome for outcome in result.outcomes if outcome.status == "updated"
    )
    primary = next(
        (
            _transition_from_dev_outcome(outcome)
            for outcome in updated
            if normalize_distribution_name(outcome.record.name) == _PRIMARY_DIST_KEY
        ),
        None,
    )
    plugin_transitions = [
        _transition_from_dev_outcome(outcome)
        for outcome in updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role == "plugin"
        )
    ]
    plugins, plugin_overflow = _cap_plugin_transitions(plugin_transitions)
    dependency_count = sum(
        1
        for outcome in updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role != "plugin"
        )
    )
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="dev",
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        dependency_count=dependency_count,
    )


def _transition_from_update_outcome(
    outcome: UpdateOutcome,
) -> UpdateVersionTransition:
    return UpdateVersionTransition(
        name=outcome.name,
        old=outcome.old_version,
        new=outcome.new_version,
    )


def _transition_from_dev_outcome(outcome: DevUpdateOutcome) -> UpdateVersionTransition:
    return UpdateVersionTransition(
        name=outcome.record.name,
        old=outcome.old_version,
        new=outcome.new_version,
    )


def _cap_plugin_transitions(
    transitions: list[UpdateVersionTransition],
) -> tuple[tuple[UpdateVersionTransition, ...], int]:
    capped = tuple(transitions[:_MAX_PLUGIN_LINES])
    return capped, max(0, len(transitions) - len(capped))


def _receipt_to_json(receipt: UpdateToastReceipt) -> dict[str, Any]:
    return {
        "format": receipt.format,
        "created_at": receipt.created_at,
        "kind": receipt.kind,
        "primary": _transition_to_json(receipt.primary),
        "plugins": [_transition_to_json(plugin) for plugin in receipt.plugins],
        "plugin_overflow": receipt.plugin_overflow,
        "dependency_count": receipt.dependency_count,
    }


def _transition_to_json(
    transition: UpdateVersionTransition | None,
) -> dict[str, str | None] | None:
    if transition is None:
        return None
    return {
        "name": transition.name,
        "old": transition.old,
        "new": transition.new,
    }


def _receipt_from_json(payload: object) -> UpdateToastReceipt | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("format") != _FORMAT_VERSION:
        return None
    created_at = _float_value(payload.get("created_at"))
    kind = payload.get("kind")
    if created_at is None or kind not in {"managed", "dev"}:
        return None
    receipt_kind: ReceiptKind = "managed" if kind == "managed" else "dev"
    primary = _transition_from_json(payload.get("primary"))
    if payload.get("primary") is not None and primary is None:
        return None
    plugins_payload = payload.get("plugins")
    if not isinstance(plugins_payload, list):
        return None
    plugins: list[UpdateVersionTransition] = []
    for item in plugins_payload:
        plugin = _transition_from_json(item)
        if plugin is None:
            return None
        plugins.append(plugin)
    plugin_overflow = _nonnegative_int(payload.get("plugin_overflow"))
    dependency_count = _nonnegative_int(payload.get("dependency_count"))
    if plugin_overflow is None or dependency_count is None:
        return None
    return UpdateToastReceipt(
        kind=receipt_kind,
        created_at=created_at,
        primary=primary,
        plugins=tuple(plugins),
        plugin_overflow=plugin_overflow,
        dependency_count=dependency_count,
    )


def _transition_from_json(payload: object) -> UpdateVersionTransition | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    old = _optional_str(payload.get("old"))
    new = _optional_str(payload.get("new"))
    if not isinstance(name, str) or not name:
        return None
    if old is None and new is None:
        return None
    return UpdateVersionTransition(name=name, old=old, new=new)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("Failed to remove pending update toast file", exc_info=True)


__all__ = [
    "UpdateToastReceipt",
    "UpdateVersionTransition",
    "build_update_receipt",
    "read_and_clear_pending_update_toast",
    "write_pending_update_toast",
]
