"""Process-local feature-flag snapshot management."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

from sase.feature_flags.env import (
    SASE_FEATURE_FLAGS_ENV,
    apply_feature_flags_env,
    merge_feature_flags_env,
)
from sase.feature_flags.models import (
    FeatureFlagDiagnostic,
    FeatureFlagSnapshot,
)
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import FeatureFlagLayerInput, resolve_feature_flags
from sase.feature_flags.state import (
    SavedFeatureFlagReconcileOutcome,
    reconcile_saved_feature_flags,
)


log = logging.getLogger(__name__)

_lock = threading.RLock()
_snapshot: FeatureFlagSnapshot | None = None
_installed = False
_override_stack: list[dict[str, bool]] = []
_cli_values: dict[str, bool] = {}
_cleanup_request: _FeatureFlagCleanupRequest | None = None
_cleanup_running = False


@dataclass(frozen=True)
class FeatureFlagCleanupNotice:
    """Ready-to-display feature-flag cleanup notice."""

    title: str
    message: str
    plain_message: str
    severity: Literal["information", "warning"]
    timeout: float


@dataclass(frozen=True)
class _FeatureFlagCleanupRequest:
    registered_keys: tuple[str, ...]
    candidate_keys: tuple[str, ...]
    state_path: str


def _current_overrides() -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for values in _override_stack:
        merged.update(values)
    return merged


def _project_layer_inputs() -> tuple[
    tuple[FeatureFlagLayerInput, ...],
    tuple[FeatureFlagDiagnostic, ...],
]:
    from sase.config.core import load_config_layers

    inputs: list[FeatureFlagLayerInput] = []
    diagnostics: list[FeatureFlagDiagnostic] = []
    for layer in load_config_layers():
        raw_value = layer.data.get("feature_flags")
        if raw_value is None:
            values: Mapping[str, Any] = {}
        elif isinstance(raw_value, Mapping):
            values = raw_value
        else:
            diagnostics.append(
                FeatureFlagDiagnostic(
                    severity="warning",
                    code="not_a_mapping",
                    message="feature_flags must be a mapping of flag keys to booleans",
                    source=layer.name,
                )
            )
            values = {}
        inputs.append(
            FeatureFlagLayerInput(
                name=layer.name,
                detail=layer.path or "",
                values=values,
            )
        )
    return tuple(inputs), tuple(diagnostics)


def _saved_state_input() -> tuple[
    Mapping[str, bool],
    tuple[FeatureFlagDiagnostic, ...],
    str,
]:
    from sase.feature_flags.state import load_saved_feature_flags

    loaded = load_saved_feature_flags()
    return dict(loaded.flags), loaded.diagnostics, loaded.path


def _build_snapshot() -> FeatureFlagSnapshot:
    layers, projection_diagnostics = _project_layer_inputs()
    saved_flags, saved_diagnostics, saved_path = _saved_state_input()
    snapshot = resolve_feature_flags(
        definitions=feature_flag_definitions(),
        layers=layers,
        saved=saved_flags,
        saved_detail=saved_path,
        overrides=_current_overrides(),
        env_value=os.environ.get(SASE_FEATURE_FLAGS_ENV),
        legacy_env=os.environ,
        cli=dict(_cli_values) if _cli_values else None,
    )
    return FeatureFlagSnapshot(
        decisions=snapshot.decisions,
        diagnostics=(
            *projection_diagnostics,
            *saved_diagnostics,
            *snapshot.diagnostics,
        ),
        saved=snapshot.saved,
        state_path=snapshot.state_path,
    )


def set_cli_feature_flags(values: Mapping[str, bool]) -> None:
    """Record CLI flag values as the highest-precedence source."""
    global _snapshot
    recorded = dict(values)
    with _lock:
        _cli_values.clear()
        _cli_values.update(recorded)
        _snapshot = None
        merge_feature_flags_env(recorded)


def sync_saved_feature_flag(key: str, enabled: bool) -> None:
    """Merge a saved preference into process transport and drop the cache."""
    global _snapshot
    with _lock:
        merge_feature_flags_env({key: enabled})
        _snapshot = None


def current_flag_layers() -> tuple[FeatureFlagLayerInput, ...]:
    """Return the current process config layers used for flag resolution."""
    layers, _diagnostics = _project_layer_inputs()
    return layers


def current_flags() -> FeatureFlagSnapshot:
    """Return the immutable process feature-flag snapshot."""
    global _snapshot
    with _lock:
        if _snapshot is None:
            _snapshot = _build_snapshot()
        return _snapshot


def _log_install(
    snapshot: FeatureFlagSnapshot,
    *,
    suppress_state_unknowns: bool = False,
) -> None:
    non_default = snapshot.non_default()
    if non_default:
        details = ", ".join(
            f"{decision.key}={decision.enabled} ({decision.source})"
            for decision in non_default
        )
    else:
        details = "none"
    log.info("feature flags resolved; non-default: %s", details)
    for diagnostic in snapshot.diagnostics:
        if (
            suppress_state_unknowns
            and diagnostic.source == "state"
            and diagnostic.code == "unknown_key"
        ):
            continue
        log.warning(
            "feature flag diagnostic [%s] from %s: %s",
            diagnostic.code,
            diagnostic.source,
            diagnostic.message,
        )


def install_process_feature_flags(
    *,
    defer_cleanup: bool = False,
) -> FeatureFlagSnapshot:
    """Pin this process and its children to one resolved feature-flag snapshot."""
    global _cleanup_request, _cleanup_running, _installed, _snapshot
    sync_request: _FeatureFlagCleanupRequest | None = None
    with _lock:
        if _installed and _snapshot is not None:
            return _snapshot
        if _snapshot is None:
            _snapshot = _build_snapshot()
        request = _cleanup_request_from_snapshot(
            _snapshot,
            feature_flag_definitions(),
        )
        if request is not None and defer_cleanup:
            if not _cleanup_running:
                _cleanup_request = request
            _log_install(_snapshot, suppress_state_unknowns=True)
            apply_feature_flags_env(_snapshot)
            _installed = True
            return _snapshot
        if request is not None:
            _cleanup_request = None
            _cleanup_running = True
            sync_request = request
        else:
            _log_install(_snapshot)
            apply_feature_flags_env(_snapshot)
            _installed = True
            return _snapshot

    assert sync_request is not None
    outcome, notice = _execute_cleanup_request(sync_request)
    with _lock:
        _cleanup_running = False
        if outcome is not None:
            _settle_cleanup_result_locked(sync_request, outcome)
        if _snapshot is None:
            _snapshot = _build_snapshot()
        _log_install(_snapshot, suppress_state_unknowns=True)
        apply_feature_flags_env(_snapshot)
        _installed = True
        snapshot = _snapshot
    if notice is not None:
        _emit_cleanup_notice_stderr(notice)
    return snapshot


def has_pending_feature_flag_cleanup() -> bool:
    """Return whether ACE has deferred saved-state cleanup work to run."""
    with _lock:
        return _cleanup_request is not None and not _cleanup_running


def run_pending_feature_flag_cleanup() -> FeatureFlagCleanupNotice | None:
    """Run ACE's deferred feature-flag cleanup request once, if present."""
    global _cleanup_request, _cleanup_running
    with _lock:
        if _cleanup_request is None or _cleanup_running:
            return None
        request = _cleanup_request
        _cleanup_request = None
        _cleanup_running = True
    outcome, notice = _execute_cleanup_request(request)
    with _lock:
        _cleanup_running = False
        if outcome is not None:
            _settle_cleanup_result_locked(request, outcome)
    return notice


def _execute_cleanup_request(
    request: _FeatureFlagCleanupRequest,
) -> tuple[SavedFeatureFlagReconcileOutcome | None, FeatureFlagCleanupNotice | None]:
    try:
        outcome = reconcile_saved_feature_flags(request.registered_keys)
    except Exception as exc:
        return None, _cleanup_failure_notice(
            request=request,
            reason=str(exc) or type(exc).__qualname__,
        )
    return outcome, _cleanup_notice_from_outcome(request, outcome)


def _cleanup_request_from_snapshot(
    snapshot: FeatureFlagSnapshot,
    definitions: Mapping[str, object],
) -> _FeatureFlagCleanupRequest | None:
    registered_keys = tuple(sorted(str(key) for key in definitions))
    candidates = tuple(sorted(key for key in snapshot.saved if key not in definitions))
    if not candidates:
        return None
    return _FeatureFlagCleanupRequest(
        registered_keys=registered_keys,
        candidate_keys=candidates,
        state_path=snapshot.state_path,
    )


def _settle_cleanup_result_locked(
    request: _FeatureFlagCleanupRequest,
    outcome: SavedFeatureFlagReconcileOutcome,
) -> None:
    global _snapshot
    if outcome.status not in ("cleaned", "unchanged"):
        return
    if any(key in outcome.flags for key in request.candidate_keys):
        return
    if _snapshot is None:
        return
    _snapshot = FeatureFlagSnapshot(
        decisions=_snapshot.decisions,
        diagnostics=tuple(
            diagnostic
            for diagnostic in _snapshot.diagnostics
            if not (diagnostic.source == "state" and diagnostic.code == "unknown_key")
        ),
        saved=dict(outcome.flags),
        state_path=outcome.path,
    )


def _cleanup_notice_from_outcome(
    request: _FeatureFlagCleanupRequest,
    outcome: SavedFeatureFlagReconcileOutcome,
) -> FeatureFlagCleanupNotice | None:
    if outcome.status == "cleaned":
        return _cleanup_success_notice(outcome.removed, path=outcome.path)
    if outcome.status == "unchanged" and all(
        key not in outcome.flags for key in request.candidate_keys
    ):
        return _cleanup_already_clean_notice(
            request.candidate_keys,
            path=outcome.path,
        )
    if outcome.status in ("failed", "unusable"):
        reason = (
            outcome.diagnostics[0].message
            if outcome.diagnostics
            else "feature-flag state could not be reconciled"
        )
        return _cleanup_failure_notice(request=request, reason=reason)
    return None


def _cleanup_success_notice(
    removed: tuple[str, ...],
    *,
    path: str,
) -> FeatureFlagCleanupNotice:
    count = len(removed)
    line = (
        f"Removed {count} unregistered saved "
        f"{_plural(count, 'flag')}: {_plain_key_list(removed)}"
    )
    return FeatureFlagCleanupNotice(
        title="Feature flags cleaned up",
        message=(f"[bold green]AUTO-CLEANED[/]\n{line}\nState: {_escape_markup(path)}"),
        plain_message=f"AUTO-CLEANED\n{line}\nState: {path}",
        severity="information",
        timeout=15.0,
    )


def _cleanup_already_clean_notice(
    candidates: tuple[str, ...],
    *,
    path: str,
) -> FeatureFlagCleanupNotice:
    count = len(candidates)
    line = (
        f"Previously unregistered saved {_plural(count, 'flag')} "
        f"{'is' if count == 1 else 'are'} already absent: "
        f"{_plain_key_list(candidates)}"
    )
    return FeatureFlagCleanupNotice(
        title="Feature flag state cleaned up",
        message=(
            "[bold green]ALREADY CLEAN[/]\n"
            f"{_escape_markup(line)}\n"
            f"State: {_escape_markup(path)}"
        ),
        plain_message=f"ALREADY CLEAN\n{line}\nState: {path}",
        severity="information",
        timeout=15.0,
    )


def _cleanup_failure_notice(
    *,
    request: _FeatureFlagCleanupRequest,
    reason: str,
) -> FeatureFlagCleanupNotice:
    state_path = request.state_path or "unknown"
    plain = (
        "CLEANUP FAILED\n"
        f"State: {state_path}\n"
        f"Reason: {reason}\n"
        "Will retry on next startup"
    )
    return FeatureFlagCleanupNotice(
        title="Feature flag cleanup failed",
        message=(
            "[bold yellow]CLEANUP FAILED[/]\n"
            f"State: {_escape_markup(state_path)}\n"
            f"Reason: {_escape_markup(reason)}\n"
            "Will retry on next startup"
        ),
        plain_message=plain,
        severity="warning",
        timeout=15.0,
    )


def _emit_cleanup_notice_stderr(notice: FeatureFlagCleanupNotice) -> None:
    import sys

    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console(stderr=True)
    if console.is_terminal:
        border = "green" if notice.severity == "information" else "yellow"
        console.print(
            Panel(
                Text.from_markup(notice.message),
                title=notice.title,
                border_style=border,
            )
        )
        return
    print(notice.title, file=sys.stderr)
    print(notice.plain_message, file=sys.stderr)


def _escape_markup(value: str) -> str:
    from rich.markup import escape

    return escape(value)


def _plain_key_list(keys: tuple[str, ...]) -> str:
    displayed = tuple(_truncate_key(key) for key in keys[:5])
    text = ", ".join(displayed)
    overflow = len(keys) - len(displayed)
    if overflow > 0:
        text = f"{text}, +{overflow} more"
    return text


def _truncate_key(key: str, *, limit: int = 80) -> str:
    if len(key) <= limit:
        return key
    return f"{key[: limit - 1]}..."


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"


@contextmanager
def override_flags(**values: bool) -> Iterator[FeatureFlagSnapshot]:
    """Temporarily resolve feature flags with explicit override values."""
    global _installed, _snapshot
    with _lock:
        previous_snapshot = _snapshot
        previous_installed = _installed
        _override_stack.append(dict(values))
        _snapshot = None
        _installed = False
    try:
        yield current_flags()
    finally:
        with _lock:
            _override_stack.pop()
            _snapshot = previous_snapshot
            _installed = previous_installed
