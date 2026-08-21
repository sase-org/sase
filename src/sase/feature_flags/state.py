"""Thin adapter around the Rust machine-local feature-flag preference store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, cast

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FeatureFlagError,
    FeatureFlagMutationOutcome,
    FeatureFlagStateError,
    FlagSource,
    is_feature_flag_key,
)


FEATURE_FLAG_STATE_FILENAME = "feature_flags.json"
FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION = 1

_SNAPSHOT_FIELDS = frozenset({"version", "flags", "path", "diagnostics"})
_SET_FIELDS = frozenset(
    {
        "version",
        "flag",
        "enabled",
        "previous",
        "changed",
        "flags",
        "path",
        "diagnostics",
    }
)
_DIAGNOSTIC_FIELDS = frozenset({"severity", "code", "message", "path"})
_PROCESS_PIN_SOURCES: frozenset[FlagSource] = frozenset({"override", "cli"})


@dataclass(frozen=True)
class SavedFeatureFlagState:
    """Decoded machine-local preference snapshot plus read diagnostics."""

    version: int
    flags: Mapping[str, bool]
    path: str
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Freeze mapping inputs so callers cannot mutate a snapshot."""
        object.__setattr__(self, "flags", MappingProxyType(dict(self.flags)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class SavedFeatureFlagSetOutcome:
    """Decoded exclusive-lock set outcome from the Rust store."""

    version: int
    flag: str
    enabled: bool
    previous: bool | None
    changed: bool
    flags: Mapping[str, bool]
    path: str
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Freeze mapping inputs so callers cannot mutate an outcome."""
        object.__setattr__(self, "flags", MappingProxyType(dict(self.flags)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def feature_flag_state_path() -> str:
    """Return the machine-local preference path under the current ``SASE_HOME``."""
    return str(sase_home() / FEATURE_FLAG_STATE_FILENAME)


def load_saved_feature_flags() -> SavedFeatureFlagState:
    """Read the preference snapshot through the Rust binding."""
    path = feature_flag_state_path()
    payload = _call_binding("feature_flag_state_get", str(sase_home()), path=path)
    return _snapshot_from_wire(payload, fallback_path=path)


def _persist_saved_feature_flag(key: str, enabled: bool) -> SavedFeatureFlagSetOutcome:
    """Write one snake_case key through the Rust binding."""
    path = feature_flag_state_path()
    payload = _call_binding(
        "feature_flag_state_set", str(sase_home()), key, enabled, path=path
    )
    return _set_outcome_from_wire(payload, fallback_path=path, key=key, enabled=enabled)


def set_saved_feature_flag(key: str, enabled: bool) -> FeatureFlagMutationOutcome:
    """Persist *key* and synchronize this process's transport and snapshot."""
    key_text = str(key)
    if type(enabled) is not bool:
        raise FeatureFlagError(f"feature flag {key_text!r} must be boolean")
    if not is_feature_flag_key(key_text):
        raise FeatureFlagError(f"feature flag key must be snake_case: {key_text!r}")

    from sase.feature_flags.registry import feature_flag_definitions
    from sase.feature_flags.snapshot import current_flags, sync_saved_feature_flag

    if key_text not in feature_flag_definitions():
        raise FeatureFlagError(f"unknown feature flag: {key_text}")

    before = current_flags().decision(key_text)
    rust_outcome = _persist_saved_feature_flag(key_text, enabled)
    sync_saved_feature_flag(key_text, enabled)
    after_snapshot = current_flags()
    after = after_snapshot.decision(key_text)
    shadowed = _is_shadowed(after, enabled)
    return FeatureFlagMutationOutcome(
        key=key_text,
        enabled=enabled,
        previous_saved=rust_outcome.previous,
        changed=rust_outcome.changed,
        before=before,
        after=after,
        shadowed=shadowed,
        shadowing_source=after.source if shadowed else None,
        state_path=rust_outcome.path,
        diagnostics=after_snapshot.diagnostics,
    )


def _is_shadowed(after: FeatureFlagDecision, enabled: bool) -> bool:
    """Return whether a higher-precedence process pin still wins."""
    if after.source in _PROCESS_PIN_SOURCES:
        return True
    return after.source == "env" and after.enabled != enabled


def _call_binding(name: str, *args: Any, path: str) -> Any:
    try:
        binding = require_rust_binding(name)
        return binding(*args)
    except FeatureFlagStateError:
        raise
    except Exception as exc:
        message = str(exc) or f"{type(exc).__name__} from {name}"
        if path and path not in message:
            message = f"{message} ({path})"
        raise FeatureFlagStateError(message, path=path) from exc


def _snapshot_from_wire(
    payload: object, *, fallback_path: str
) -> SavedFeatureFlagState:
    data = _require_mapping(payload, "feature-flag state snapshot", path=fallback_path)
    _require_fields(
        data, _SNAPSHOT_FIELDS, "feature-flag state snapshot", fallback_path
    )
    path = _require_path(data.get("path"), fallback_path)
    version = _require_version(data.get("version"), path)
    flags = _require_flags(data.get("flags"), path)
    diagnostics = _require_diagnostics(data.get("diagnostics"), path)
    return SavedFeatureFlagState(
        version=version,
        flags=flags,
        path=path,
        diagnostics=diagnostics,
    )


def _set_outcome_from_wire(
    payload: object,
    *,
    fallback_path: str,
    key: str,
    enabled: bool,
) -> SavedFeatureFlagSetOutcome:
    data = _require_mapping(
        payload, "feature-flag state set outcome", path=fallback_path
    )
    _require_fields(data, _SET_FIELDS, "feature-flag state set outcome", fallback_path)
    path = _require_path(data.get("path"), fallback_path)
    version = _require_version(data.get("version"), path)
    flag = data.get("flag")
    if type(flag) is not str or flag != key:
        raise FeatureFlagStateError(
            f"feature-flag state set outcome flag mismatch: {flag!r}",
            path=path,
        )
    stored = data.get("enabled")
    if type(stored) is not bool or stored is not enabled:
        raise FeatureFlagStateError(
            f"feature-flag state set outcome enabled mismatch: {stored!r}",
            path=path,
        )
    previous = data.get("previous")
    if previous is not None and type(previous) is not bool:
        raise FeatureFlagStateError(
            f"feature-flag state previous must be a boolean or null: {previous!r}",
            path=path,
        )
    changed = data.get("changed")
    if type(changed) is not bool:
        raise FeatureFlagStateError(
            f"feature-flag state changed must be a boolean: {changed!r}",
            path=path,
        )
    flags = _require_flags(data.get("flags"), path)
    diagnostics = _require_diagnostics(data.get("diagnostics"), path)
    return SavedFeatureFlagSetOutcome(
        version=version,
        flag=flag,
        enabled=stored,
        previous=previous,
        changed=changed,
        flags=flags,
        path=path,
        diagnostics=diagnostics,
    )


def _require_mapping(payload: object, label: str, *, path: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FeatureFlagStateError(f"{label} is not an object: {payload!r}", path=path)
    return payload


def _require_fields(
    payload: Mapping[str, Any],
    required: frozenset[str],
    label: str,
    path: str,
) -> None:
    actual = set(payload)
    if actual == required:
        return
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    details: list[str] = []
    if missing:
        details.append(f"missing {', '.join(missing)}")
    if extra:
        details.append(f"unknown {', '.join(extra)}")
    raise FeatureFlagStateError(
        f"invalid {label} fields: {'; '.join(details)}",
        path=path,
    )


def _require_version(value: object, path: str) -> int:
    if type(value) is not int or value != FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION:
        raise FeatureFlagStateError(
            f"unsupported feature-flag state wire version: {value!r}",
            path=path,
        )
    return value


def _require_path(value: object, fallback: str) -> str:
    if type(value) is not str or not value:
        raise FeatureFlagStateError(
            f"feature-flag state path must be a non-empty string: {value!r}",
            path=fallback,
        )
    return value


def _require_flags(value: object, path: str) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise FeatureFlagStateError(
            f"feature-flag state flags must be an object: {value!r}",
            path=path,
        )
    flags: dict[str, bool] = {}
    for raw_key, raw_enabled in value.items():
        key = str(raw_key)
        if type(raw_key) is not str or not is_feature_flag_key(key):
            raise FeatureFlagStateError(
                f"feature-flag state flag key must be snake_case: {raw_key!r}",
                path=path,
            )
        if type(raw_enabled) is not bool:
            raise FeatureFlagStateError(
                f"feature-flag state value for {key!r} must be boolean",
                path=path,
            )
        flags[key] = raw_enabled
    return flags


def _require_diagnostics(value: object, path: str) -> tuple[FeatureFlagDiagnostic, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise FeatureFlagStateError(
            f"feature-flag state diagnostics must be a list: {value!r}",
            path=path,
        )
    diagnostics: list[FeatureFlagDiagnostic] = []
    for item in value:
        diagnostics.append(_diagnostic_from_wire(item, fallback_path=path))
    return tuple(diagnostics)


def _diagnostic_from_wire(
    payload: object, *, fallback_path: str
) -> FeatureFlagDiagnostic:
    data = _require_mapping(
        payload, "feature-flag state diagnostic", path=fallback_path
    )
    _require_fields(
        data, _DIAGNOSTIC_FIELDS, "feature-flag state diagnostic", fallback_path
    )
    severity = data.get("severity")
    if severity not in ("warning", "error"):
        raise FeatureFlagStateError(
            f"feature-flag state diagnostic severity is invalid: {severity!r}",
            path=fallback_path,
        )
    code = data.get("code")
    message = data.get("message")
    source_path = data.get("path")
    if type(code) is not str or not code:
        raise FeatureFlagStateError(
            f"feature-flag state diagnostic code must be a string: {code!r}",
            path=fallback_path,
        )
    if type(message) is not str or not message:
        raise FeatureFlagStateError(
            f"feature-flag state diagnostic message must be a string: {message!r}",
            path=fallback_path,
        )
    if type(source_path) is not str:
        raise FeatureFlagStateError(
            f"feature-flag state diagnostic path must be a string: {source_path!r}",
            path=fallback_path,
        )
    if source_path and source_path not in message:
        message = f"{message} ({source_path})"
    return FeatureFlagDiagnostic(
        severity=cast(Literal["warning", "error"], severity),
        code=code,
        message=message,
        source="state",
    )


__all__ = [
    "FEATURE_FLAG_STATE_FILENAME",
    "FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION",
    "SavedFeatureFlagSetOutcome",
    "SavedFeatureFlagState",
    "feature_flag_state_path",
    "load_saved_feature_flags",
    "set_saved_feature_flag",
]
