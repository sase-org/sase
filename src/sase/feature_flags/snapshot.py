"""Process-local feature-flag snapshot management."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

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


log = logging.getLogger(__name__)

_lock = threading.RLock()
_snapshot: FeatureFlagSnapshot | None = None
_installed = False
_override_stack: list[dict[str, bool]] = []
_cli_values: dict[str, bool] = {}


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


def _log_install(snapshot: FeatureFlagSnapshot) -> None:
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
        log.warning(
            "feature flag diagnostic [%s] from %s: %s",
            diagnostic.code,
            diagnostic.source,
            diagnostic.message,
        )


def install_process_feature_flags() -> FeatureFlagSnapshot:
    """Pin this process and its children to one resolved feature-flag snapshot."""
    global _installed, _snapshot
    with _lock:
        if _installed and _snapshot is not None:
            return _snapshot
        if _snapshot is None:
            _snapshot = _build_snapshot()
        _log_install(_snapshot)
        apply_feature_flags_env(_snapshot)
        _installed = True
        return _snapshot


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
