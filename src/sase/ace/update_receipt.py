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
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.agent_clis.models import AgentCliUpdateResult, UpdateResultStatus
from sase.core.paths import sase_home
from sase.dev_update.models import DevUpdateOutcome, DevUpdateResult, RepoDiffStat
from sase.main.update_types import CombinedUpdateResult
from sase.mode_switch.models import ModeSwitchResult
from sase.plugins.operations import (
    InstallManyOutcome,
    InstallOutcome,
    UninstallOutcome,
    UpdateOutcome as PluginUpdateOutcome,
)
from sase.uv_tool.render import UpdateOutcome as ManagedUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from sase.version._utils import normalize_distribution_name

log = logging.getLogger(__name__)

_FORMAT_VERSION = 2
_LEGACY_FORMAT_VERSION = 1
_MAX_PLUGIN_LINES = 3
_MAX_PROVIDER_LINES = 8
_FRESHNESS_SECONDS = 30 * 60
_PRIMARY_DIST_KEY = normalize_distribution_name("sase")

# Test override for the backing file. ``None`` falls back to the per-user path
# under ``sase_home()``, matching the small-state helpers in this package.
_PENDING_UPDATE_TOAST_FILE: Path | None = None

ReceiptKind = Literal["managed", "dev", "mode_switch_dev", "mode_switch_pypi"]
ProviderReceiptStatus = Literal[
    "updated",
    "already_current",
    "failed",
    "skipped",
]


@dataclass(frozen=True)
class UpdateVersionTransition:
    """A package version transition rendered by the post-update toast."""

    name: str
    old: str | None
    new: str | None
    diffstat: RepoDiffStat | None = None


@dataclass(frozen=True)
class _ProviderUpdateReceiptResult:
    """Bounded provider outcome retained across an ACE code restart."""

    name: str
    display_name: str
    status: ProviderReceiptStatus
    old_version: str | None = None
    new_version: str | None = None
    reason: str | None = None
    docs_url: str | None = None
    command: tuple[str, ...] | None = None
    suggested_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class UpdateToastReceipt:
    """Serializable receipt consumed once by the restarted ACE process."""

    kind: ReceiptKind
    created_at: float
    primary: UpdateVersionTransition | None
    plugins: tuple[UpdateVersionTransition, ...] = ()
    plugin_overflow: int = 0
    plugin_overflow_diffstat: RepoDiffStat | None = None
    dependency_count: int = 0
    provider_results: tuple[_ProviderUpdateReceiptResult, ...] = ()
    provider_overflow: int = 0
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
    if isinstance(payload, CombinedUpdateResult):
        return _build_combined_receipt(payload, created_at=timestamp)
    if isinstance(payload, ComprehensiveUpdateResult):
        return _build_comprehensive_receipt(payload, created_at=timestamp)
    if isinstance(payload, ModeSwitchResult):
        return _build_mode_switch_receipt(payload, created_at=timestamp)
    if isinstance(payload, InstallOutcome):
        return _build_plugin_install_receipt(payload, created_at=timestamp)
    if isinstance(payload, InstallManyOutcome):
        return _build_plugin_install_many_receipt(payload, created_at=timestamp)
    if isinstance(payload, PluginUpdateOutcome):
        return _build_plugin_update_receipt(payload, created_at=timestamp)
    if isinstance(payload, UninstallOutcome):
        return _build_plugin_uninstall_receipt(payload, created_at=timestamp)
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
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
    dependency_count = len(summary.updated_dependencies)
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
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
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
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
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_combined_receipt(
    result: CombinedUpdateResult, *, created_at: float
) -> UpdateToastReceipt | None:
    """Merge editable transitions with managed dependency transitions."""
    dev_updated = (
        tuple(
            outcome
            for outcome in result.dev_result.outcomes
            if outcome.status == "updated"
        )
        if result.dev_result is not None
        else ()
    )
    managed_updated = (
        result.managed_summary.updated if result.managed_summary is not None else ()
    )
    primary = next(
        (
            _transition_from_dev_outcome(outcome)
            for outcome in dev_updated
            if normalize_distribution_name(outcome.record.name) == _PRIMARY_DIST_KEY
        ),
        None,
    ) or next(
        (
            _transition_from_update_outcome(outcome)
            for outcome in managed_updated
            if outcome.role == "primary"
        ),
        None,
    )
    transitions = [
        _transition_from_dev_outcome(outcome)
        for outcome in dev_updated
        if outcome.record.role == "plugin"
    ]
    transitions.extend(
        _transition_from_update_outcome(outcome)
        for outcome in managed_updated
        if outcome.role == "plugin"
    )
    plugins, overflow, overflow_diffstat = _cap_plugin_transitions(transitions)
    dependency_count = sum(
        1
        for outcome in dev_updated
        if (
            normalize_distribution_name(outcome.record.name) != _PRIMARY_DIST_KEY
            and outcome.record.role != "plugin"
        )
    ) + sum(1 for outcome in managed_updated if outcome.role == "dependency")
    if primary is None and not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind=(
            "dev"
            if result.dev_result is not None and result.dev_result.changed
            else "managed"
        ),
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=overflow,
        plugin_overflow_diffstat=overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_comprehensive_receipt(
    result: ComprehensiveUpdateResult,
    *,
    created_at: float,
) -> UpdateToastReceipt | None:
    """Attach bounded provider outcomes to the changed SASE receipt."""
    if not result.code_changed or result.sase.payload is None:
        return None
    base = build_update_receipt(result.sase.payload, created_at=created_at)
    if base is None:
        kind: ReceiptKind = (
            "dev"
            if isinstance(result.sase.payload, (DevUpdateResult, CombinedUpdateResult))
            else "managed"
        )
        base = UpdateToastReceipt(
            kind=kind,
            created_at=created_at,
            primary=None,
        )

    provider_results = [
        _provider_receipt_result(provider) for provider in result.provider_results
    ]
    if result.provider_error:
        provider_results.append(
            _ProviderUpdateReceiptResult(
                name="agent-clis",
                display_name="Agent CLIs",
                status="failed",
                reason=result.provider_error,
            )
        )
    capped = tuple(provider_results[:_MAX_PROVIDER_LINES])
    return replace(
        base,
        provider_results=capped,
        provider_overflow=max(0, len(provider_results) - len(capped)),
    )


def _provider_receipt_result(
    result: AgentCliUpdateResult,
) -> _ProviderUpdateReceiptResult:
    status: ProviderReceiptStatus = result.status.value  # type: ignore[assignment]
    return _ProviderUpdateReceiptResult(
        name=result.name,
        display_name=result.display_name,
        status=status,
        old_version=result.old_version,
        new_version=result.new_version,
        reason=result.reason,
        docs_url=result.docs_url,
        command=result.command,
        suggested_command=result.suggested_command,
    )


def _build_mode_switch_receipt(
    result: ModeSwitchResult, *, created_at: float
) -> UpdateToastReceipt | None:
    if not result.changed:
        return None
    primary = next(
        (
            UpdateVersionTransition(
                name=outcome.name,
                old=outcome.old_version,
                new=outcome.new_version,
            )
            for outcome in result.outcomes
            if outcome.role == "host"
        ),
        None,
    )
    plugin_transitions = [
        UpdateVersionTransition(
            name=outcome.name,
            old=outcome.old_version,
            new=outcome.new_version,
        )
        for outcome in result.outcomes
        if outcome.role == "plugin"
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        plugin_transitions
    )
    dependency_count = sum(1 for outcome in result.outcomes if outcome.role == "core")
    kind: ReceiptKind = (
        "mode_switch_dev" if result.plan.target_mode == "dev" else "mode_switch_pypi"
    )
    return UpdateToastReceipt(
        kind=kind,
        created_at=created_at,
        primary=primary,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _transition_from_update_outcome(
    outcome: ManagedUpdateOutcome,
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
        diffstat=outcome.diffstat,
    )


def _build_plugin_install_receipt(
    outcome: InstallOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    spec = outcome.plan.spec
    target_key = spec.normalized_name
    transition = _transition_from_change(
        outcome.change_set.get(spec.requirement.name),
        fallback_name=spec.requirement.name,
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys={target_key},
    )
    if transition is None and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=(transition,) if transition is not None else (),
        dependency_count=dependency_count,
    )


def _build_plugin_install_many_receipt(
    outcome: InstallManyOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_keys = {spec.normalized_name for spec in outcome.plan.specs}
    transitions = [
        transition
        for spec in outcome.plan.specs
        if (
            transition := _transition_from_change(
                outcome.change_set.get(spec.requirement.name),
                fallback_name=spec.requirement.name,
            )
        )
        is not None
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        transitions
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys=target_keys,
    )
    if not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_plugin_update_receipt(
    outcome: PluginUpdateOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_keys = {
        normalize_distribution_name(target) for target in outcome.plan.targets
    }
    transitions = [
        transition
        for target in outcome.plan.targets
        if (
            transition := _transition_from_change(
                outcome.change_set.get(target),
                fallback_name=target,
            )
        )
        is not None
    ]
    plugins, plugin_overflow, plugin_overflow_diffstat = _cap_plugin_transitions(
        transitions
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys=target_keys,
    )
    if not plugins and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=plugins,
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
    )


def _build_plugin_uninstall_receipt(
    outcome: UninstallOutcome, *, created_at: float
) -> UpdateToastReceipt | None:
    target_key = outcome.plan.normalized_name
    transition = _transition_from_change(
        outcome.change_set.get(outcome.plan.dist_name),
        fallback_name=outcome.plan.dist_name,
    )
    dependency_count = _dependency_change_count(
        outcome.change_set,
        target_keys={target_key},
    )
    if transition is None and dependency_count == 0:
        return None
    return UpdateToastReceipt(
        kind="managed",
        created_at=created_at,
        primary=None,
        plugins=(transition,) if transition is not None else (),
        dependency_count=dependency_count,
    )


def _transition_from_change(
    change: UvPackageChange | None, *, fallback_name: str
) -> UpdateVersionTransition | None:
    if change is None or change.kind is ChangeKind.UNCHANGED:
        return None
    old = change.old_version
    new = change.new_version
    if old is None and new is None:
        return None
    return UpdateVersionTransition(name=change.name or fallback_name, old=old, new=new)


def _dependency_change_count(change_set: UvChangeSet, *, target_keys: set[str]) -> int:
    return sum(
        1
        for change in change_set.changes
        if normalize_distribution_name(change.name) not in target_keys
        and change.kind is not ChangeKind.UNCHANGED
    )


def _cap_plugin_transitions(
    transitions: list[UpdateVersionTransition],
) -> tuple[tuple[UpdateVersionTransition, ...], int, RepoDiffStat | None]:
    capped = tuple(transitions[:_MAX_PLUGIN_LINES])
    overflow = transitions[_MAX_PLUGIN_LINES:]
    return (
        capped,
        len(overflow),
        _sum_diffstats(transition.diffstat for transition in overflow),
    )


def _receipt_to_json(receipt: UpdateToastReceipt) -> dict[str, Any]:
    return {
        "format": receipt.format,
        "created_at": receipt.created_at,
        "kind": receipt.kind,
        "primary": _transition_to_json(receipt.primary),
        "plugins": [_transition_to_json(plugin) for plugin in receipt.plugins],
        "plugin_overflow": receipt.plugin_overflow,
        "plugin_overflow_diffstat": _diffstat_to_json(receipt.plugin_overflow_diffstat),
        "dependency_count": receipt.dependency_count,
        "provider_results": [
            _provider_result_to_json(result) for result in receipt.provider_results
        ],
        "provider_overflow": receipt.provider_overflow,
    }


def _provider_result_to_json(
    result: _ProviderUpdateReceiptResult,
) -> dict[str, object]:
    return {
        "name": result.name,
        "display_name": result.display_name,
        "status": result.status,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "reason": result.reason,
        "docs_url": result.docs_url,
        "command": list(result.command) if result.command is not None else None,
        "suggested_command": (
            list(result.suggested_command)
            if result.suggested_command is not None
            else None
        ),
    }


def _transition_to_json(
    transition: UpdateVersionTransition | None,
) -> dict[str, object] | None:
    if transition is None:
        return None
    return {
        "name": transition.name,
        "old": transition.old,
        "new": transition.new,
        "diffstat": _diffstat_to_json(transition.diffstat),
    }


def _receipt_from_json(payload: object) -> UpdateToastReceipt | None:
    if not isinstance(payload, dict):
        return None
    format_version = payload.get("format")
    if (
        isinstance(format_version, bool)
        or not isinstance(format_version, int)
        or format_version not in {_LEGACY_FORMAT_VERSION, _FORMAT_VERSION}
    ):
        return None
    created_at = _float_value(payload.get("created_at"))
    kind = payload.get("kind")
    if created_at is None or kind not in {
        "managed",
        "dev",
        "mode_switch_dev",
        "mode_switch_pypi",
    }:
        return None
    receipt_kind: ReceiptKind = kind  # type: ignore[assignment]
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
    plugin_overflow_diffstat = _diffstat_from_json(
        payload.get("plugin_overflow_diffstat")
    )
    provider_results: tuple[_ProviderUpdateReceiptResult, ...] = ()
    provider_overflow = 0
    if format_version == _FORMAT_VERSION:
        provider_payload = payload.get("provider_results")
        if (
            not isinstance(provider_payload, list)
            or len(provider_payload) > _MAX_PROVIDER_LINES
        ):
            return None
        decoded_provider_results: list[_ProviderUpdateReceiptResult] = []
        for item in provider_payload:
            provider_result = _provider_result_from_json(item)
            if provider_result is None:
                return None
            decoded_provider_results.append(provider_result)
        provider_results = tuple(decoded_provider_results)
        decoded_overflow = _nonnegative_int(payload.get("provider_overflow"))
        if decoded_overflow is None:
            return None
        provider_overflow = decoded_overflow
    return UpdateToastReceipt(
        kind=receipt_kind,
        created_at=created_at,
        primary=primary,
        plugins=tuple(plugins),
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
        provider_results=provider_results,
        provider_overflow=provider_overflow,
        format=format_version,
    )


def _provider_result_from_json(
    payload: object,
) -> _ProviderUpdateReceiptResult | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    display_name = payload.get("display_name")
    status = payload.get("status")
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(display_name, str)
        or not display_name
        or status not in {item.value for item in UpdateResultStatus}
    ):
        return None
    command = _command_from_json(payload.get("command"))
    if payload.get("command") is not None and command is None:
        return None
    suggested = _command_from_json(payload.get("suggested_command"))
    if payload.get("suggested_command") is not None and suggested is None:
        return None
    for key in ("old_version", "new_version", "reason", "docs_url"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            return None
    typed_status: ProviderReceiptStatus = status  # type: ignore[assignment]
    return _ProviderUpdateReceiptResult(
        name=name,
        display_name=display_name,
        status=typed_status,
        old_version=_optional_str(payload.get("old_version")),
        new_version=_optional_str(payload.get("new_version")),
        reason=_optional_str(payload.get("reason")),
        docs_url=_optional_str(payload.get("docs_url")),
        command=command,
        suggested_command=suggested,
    )


def _command_from_json(payload: object) -> tuple[str, ...] | None:
    if not isinstance(payload, list) or not payload:
        return None
    if any(not isinstance(part, str) or not part for part in payload):
        return None
    return tuple(payload)


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
    return UpdateVersionTransition(
        name=name,
        old=old,
        new=new,
        diffstat=_diffstat_from_json(payload.get("diffstat")),
    )


def _diffstat_to_json(diffstat: RepoDiffStat | None) -> dict[str, int] | None:
    if diffstat is None:
        return None
    return {
        "files_changed": diffstat.files_changed,
        "insertions": diffstat.insertions,
        "deletions": diffstat.deletions,
    }


def _diffstat_from_json(payload: object) -> RepoDiffStat | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    files_changed = _nonnegative_int(payload.get("files_changed"))
    insertions = _nonnegative_int(payload.get("insertions"))
    deletions = _nonnegative_int(payload.get("deletions"))
    if files_changed is None or insertions is None or deletions is None:
        return None
    return RepoDiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


def _sum_diffstats(diffstats: Iterable[RepoDiffStat | None]) -> RepoDiffStat | None:
    files_changed = 0
    insertions = 0
    deletions = 0
    found = False
    for diffstat in diffstats:
        if diffstat is None or diffstat.is_empty:
            continue
        found = True
        files_changed += diffstat.files_changed
        insertions += diffstat.insertions
        deletions += diffstat.deletions
    if not found:
        return None
    return RepoDiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


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
