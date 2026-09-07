"""Config projection and source-preserving writes for dispatch machines."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.config import core as config_core
from sase.config._edit_yaml import set_key, unset_key
from sase.config.targets import overlay_config_path, resolve_write_path
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.feature_flags import FeatureFlag, current_flags

from .models import (
    DispatchConfig,
    DispatchConfigError,
    DispatchFeatureDisabled,
    MachineDiagnostic,
    MachineRecord,
    ProviderSettings,
    coerce_string_tuple,
    validate_machine_alias,
)

DEFAULT_PROVIDER_REFS = ("builtin@https", "builtin@tailnet")


def remote_dispatch_enabled() -> bool:
    """Return whether remote-dispatch operations may contact or mutate remotes."""
    return current_flags().enabled(FeatureFlag.remote_dispatch)


def require_remote_dispatch_enabled() -> None:
    if not remote_dispatch_enabled():
        raise DispatchFeatureDisabled(
            "remote dispatch is disabled; enable `remote_dispatch` for this invocation"
        )


def load_dispatch_config(
    config: Mapping[str, Any] | None = None,
) -> DispatchConfig:
    """Return a pure dispatch projection without provider discovery or network IO."""
    merged = config_core.load_merged_config() if config is None else dict(config)
    raw_dispatch = merged.get("dispatch", {})
    diagnostics: list[MachineDiagnostic] = []
    if raw_dispatch is None:
        raw_dispatch = {}
    if not isinstance(raw_dispatch, Mapping):
        return DispatchConfig(
            providers={ref: ProviderSettings(ref=ref) for ref in DEFAULT_PROVIDER_REFS},
            machines=(),
            diagnostics=(
                MachineDiagnostic(
                    code="dispatch_not_mapping",
                    severity="error",
                    message="dispatch config must be a mapping",
                ),
            ),
        )

    provider_settings = _load_provider_settings(raw_dispatch.get("providers"))
    machines = _load_machine_records(raw_dispatch.get("machines"), diagnostics)
    discovery = raw_dispatch.get("discovery", {})
    if not isinstance(discovery, Mapping):
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_discovery_not_mapping",
                severity="error",
                message="dispatch.discovery must be a mapping when present",
            )
        )
        discovery = {}

    return DispatchConfig(
        providers=provider_settings,
        machines=machines,
        diagnostics=tuple(diagnostics),
        discovery_enabled_provider_refs=coerce_string_tuple(
            discovery.get("enabled_providers", ())
        ),
        request_timeout_seconds=_positive_float(
            raw_dispatch.get("request_timeout_seconds"),
            default=5.0,
        ),
        status_cache_seconds=_positive_float(
            raw_dispatch.get("status_cache_seconds"),
            default=60.0,
        ),
    )


def validate_connection_plan(record: MachineRecord) -> tuple[MachineDiagnostic, ...]:
    """Validate a machine's fleet connection plan with the Rust core backend."""
    from sase.core.rust import require_rust_binding

    try:
        validator = require_rust_binding("fleet_validate_connection_plan")
        plan = record.to_connection_plan()
        # SASE provider refs commonly use ``plugin@provider`` while the Rust
        # fleet contract treats this field as routing metadata with a slightly
        # narrower opaque-reference grammar. Keep the configured ref intact and
        # validate the rest of the connection plan through the core boundary.
        plan["provider_ref"] = str(plan["provider_ref"]).replace("@", ":")
        validator(plan)
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary.
        return (
            MachineDiagnostic(
                code="invalid_connection_plan",
                alias=record.alias,
                severity="error",
                message=f"connection plan for {record.alias} is invalid: {exc}",
            ),
        )
    return ()


def provider_config(config: DispatchConfig, provider_ref: str) -> Mapping[str, Any]:
    settings = config.providers.get(provider_ref)
    return settings.config if settings is not None else {}


def write_machine_record(
    record: MachineRecord,
    *,
    use_chezmoi: bool | None = None,
    target_path: Path | None = None,
) -> Path:
    """Persist one machine alias in the active local config layer."""
    validate_machine_alias(record.alias)
    return _edit_machine_mapping(
        (("set", record.alias, record.to_config()),),
        use_chezmoi=use_chezmoi,
        target_path=target_path,
    )


def remove_machine_record(
    alias: str,
    *,
    use_chezmoi: bool | None = None,
    target_path: Path | None = None,
) -> Path:
    """Remove one machine alias from the active local config layer."""
    validate_machine_alias(alias)
    return _edit_machine_mapping(
        (("unset", alias, None),),
        use_chezmoi=use_chezmoi,
        target_path=target_path,
    )


def rename_machine_record(
    old_alias: str,
    record: MachineRecord,
    *,
    use_chezmoi: bool | None = None,
    target_path: Path | None = None,
) -> Path:
    """Rename a machine alias in one source-preserving config edit."""
    validate_machine_alias(old_alias)
    validate_machine_alias(record.alias)
    if old_alias == record.alias:
        raise DispatchConfigError("new machine alias must differ from the old alias")
    return _edit_machine_mapping(
        (
            ("set", record.alias, record.to_config()),
            ("unset", old_alias, None),
        ),
        use_chezmoi=use_chezmoi,
        target_path=target_path,
    )


def _load_provider_settings(raw: object) -> dict[str, ProviderSettings]:
    settings = {
        ref: ProviderSettings(ref=ref, enabled=(ref == "builtin@https"))
        for ref in DEFAULT_PROVIDER_REFS
    }
    if raw is None:
        return settings
    if not isinstance(raw, Mapping):
        return settings
    for ref, value in raw.items():
        ref_text = str(ref)
        if isinstance(value, Mapping):
            config = dict(value)
            fallback = settings.get(ref_text, ProviderSettings(ref_text)).enabled
            enabled = bool(config.pop("enabled", fallback))
        elif isinstance(value, bool):
            enabled = value
            config = {}
        else:
            enabled = False
            config = {}
        settings[ref_text] = ProviderSettings(
            ref=ref_text,
            enabled=enabled,
            config=config,
        )
    return settings


def _load_machine_records(
    raw: object,
    diagnostics: list[MachineDiagnostic],
) -> tuple[MachineRecord, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_machines_not_mapping",
                severity="error",
                message="dispatch.machines must be a mapping",
            )
        )
        return ()

    records: list[MachineRecord] = []
    for alias in sorted(str(key) for key in raw):
        record, record_diagnostics = MachineRecord.from_config(alias, raw.get(alias))
        diagnostics.extend(record_diagnostics)
        if record is not None:
            records.append(record)
    return tuple(records)


def _positive_float(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return default
    if candidate <= 0:
        return default
    return candidate


def _registry_target_path() -> Path:
    snapshot = config_core.get_agent_owner_config_snapshot()
    if snapshot.selected_overlay is not None:
        return snapshot.selected_overlay
    machine_name = config_core.get_machine_name()
    if machine_name:
        return overlay_config_path(machine_name)
    return config_core.CONFIG_DIR / "sase.yml"


def _read_config_text(write_path: Path, target_path: Path) -> str:
    source = write_path if write_path.exists() else target_path
    if not source.exists():
        return ""
    return source.read_text(encoding="utf-8")


def _edit_machine_mapping(
    operations: tuple[tuple[str, str, object | None], ...],
    *,
    use_chezmoi: bool | None,
    target_path: Path | None,
) -> Path:
    resolved_use_chezmoi = (
        config_core.get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    )
    target = target_path or _registry_target_path()
    write_path = resolve_write_path(str(target), use_chezmoi=resolved_use_chezmoi)
    if write_path is None:
        raise DispatchConfigError("dispatch machine registry has no writable target")

    current_text = _read_config_text(write_path, target)
    updated_text = current_text
    for operation, alias, payload in operations:
        key_path = ("dispatch", "machines", alias)
        if operation == "set":
            updated_text = set_key(updated_text, key_path, payload)
        elif operation == "unset":
            updated_text = unset_key(updated_text, key_path)
        else:  # pragma: no cover - internal invariant.
            raise AssertionError(f"unknown config operation: {operation}")

    if updated_text != current_text:
        assert_test_state_write_isolated(
            write_path,
            category="dispatch machine config",
        )
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(updated_text, encoding="utf-8")
    config_core.clear_config_cache()
    return write_path


__all__ = [
    "DEFAULT_PROVIDER_REFS",
    "load_dispatch_config",
    "provider_config",
    "remote_dispatch_enabled",
    "remove_machine_record",
    "rename_machine_record",
    "require_remote_dispatch_enabled",
    "validate_connection_plan",
    "write_machine_record",
]
