"""Finalizer provider discovery, provenance, and configuration diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from sase.config.core import load_merged_config
from sase.core.finalizer_wire import FinalizerPlanWire
from sase.finalizers.config import ConfiguredFinalizerInstance, FinalizerConfig
from sase.plugins.inventory import PluginInventory, collect_plugin_inventory
from sase.plugins.qualified_id import (
    BUILTIN_PLUGIN_PREFIX,
    PluginQualifiedIdError,
    canonical_plugin_prefix,
    canonical_plugin_qualified_id,
    parse_plugin_qualified_id,
)
from sase.plugins.required import resolve_required_plugins
from sase.version._utils import normalize_distribution_name


FINALIZER_ENTRY_POINT_GROUP = "sase_finalizers"
BUILTIN_COMMIT_PROVIDER_REF = "builtin@commit"
BUILTIN_COMMAND_PROVIDER_REF = "builtin@command"
BUILTIN_PROVIDER_REFS = frozenset(
    {BUILTIN_COMMIT_PROVIDER_REF, BUILTIN_COMMAND_PROVIDER_REF}
)

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DURATION_RE = re.compile(r"^([0-9]+)(ms|s|m|h)$")
_DURATION_MULTIPLIERS = {
    "ms": 0.001,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}
_COMMAND_CONFIG_KEYS = frozenset({"command", "cwd", "timeout", "submission", "env"})


@dataclass(frozen=True)
class FinalizerProviderDiagnostic:
    """One structured finalizer provider/config diagnostic."""

    severity: str
    code: str
    message: str
    instance_id: str | None = None
    provider_ref: str | None = None
    layer: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class FinalizerProviderRecord:
    """One discoverable finalizer provider."""

    provider_ref: str
    provider_id: str
    package: str
    version: str
    entry_point: str | None
    builtin: bool
    disabled_by: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    load_status: str = "not_loaded"
    load_error: str | None = None


@dataclass(frozen=True)
class CommandFinalizerConfig:
    """Validated trusted config for ``builtin@command``."""

    command: tuple[str, ...]
    cwd: str = "primary"
    timeout_seconds: float = 120.0
    submission: str = "none"
    env: tuple[str, ...] = ()


InventoryFn = Callable[..., PluginInventory]


def collect_finalizer_providers(
    *,
    inventory_fn: InventoryFn = collect_plugin_inventory,
) -> tuple[FinalizerProviderRecord, ...]:
    """Collect builtin and plugin-advertised finalizer providers.

    Plugin provider entry points are inspected as metadata only. Their code is
    imported later inside the isolated worker subprocess, and only for a
    configured selected instance.
    """

    records: list[FinalizerProviderRecord] = [
        FinalizerProviderRecord(
            provider_ref=BUILTIN_COMMIT_PROVIDER_REF,
            provider_id="commit",
            package=BUILTIN_PLUGIN_PREFIX,
            version="builtin",
            entry_point=None,
            builtin=True,
            capabilities=("commit", "execute", "verify"),
            load_status="ok",
        ),
        FinalizerProviderRecord(
            provider_ref=BUILTIN_COMMAND_PROVIDER_REF,
            provider_id="command",
            package=BUILTIN_PLUGIN_PREFIX,
            version="builtin",
            entry_point=None,
            builtin=True,
            capabilities=("execute", "verify"),
            load_status="ok",
        ),
    ]
    inventory = inventory_fn(load_resource_entry_points=False)
    for entry in inventory.entry_points:
        if entry.group != FINALIZER_ENTRY_POINT_GROUP:
            continue
        records.append(
            FinalizerProviderRecord(
                provider_ref=_canonical_provider_ref_for_entry(
                    package=entry.package, name=entry.name
                ),
                provider_id=entry.name,
                package=entry.package,
                version=entry.version,
                entry_point=entry.value,
                builtin=False,
                disabled_by=tuple(entry.disabled_by),
                capabilities=("describe", "validate", "execute", "verify"),
                load_status=entry.load_status,
                load_error=entry.load_error,
            )
        )
    return tuple(records)


def canonical_provider_ref(value: str) -> str:
    """Return the packaging-normalized provider ref.

    The distribution segment uses PEP 503 canonicalization except for the
    literal ``builtin`` prefix. Raw metadata names stay on
    :attr:`FinalizerProviderRecord.package` for display and provenance.
    """

    return canonical_plugin_qualified_id(value)


def provider_ref_key(value: str) -> str:
    """Return a lookup key for *value*, preserving syntactically invalid refs."""

    try:
        return canonical_provider_ref(value)
    except PluginQualifiedIdError:
        return value


def _canonical_provider_ref_for_entry(*, package: str, name: str) -> str:
    """Build a provider ref from raw entry-point metadata."""

    return f"{canonical_plugin_prefix(package)}@{name}"


def provider_records_by_ref(
    providers: Sequence[FinalizerProviderRecord],
) -> dict[str, FinalizerProviderRecord]:
    """Return first-provider-wins records keyed by canonical provider ref."""

    by_ref: dict[str, FinalizerProviderRecord] = {}
    for provider in providers:
        by_ref.setdefault(provider_ref_key(provider.provider_ref), provider)
    return by_ref


def diagnose_finalizer_providers(
    config: FinalizerConfig,
    *,
    plan: FinalizerPlanWire | None = None,
    selected_only: bool = False,
    inventory_fn: InventoryFn = collect_plugin_inventory,
) -> tuple[FinalizerProviderDiagnostic, ...]:
    """Diagnose provider availability and constrained builtin config."""

    providers = collect_finalizer_providers(inventory_fn=inventory_fn)
    by_ref = provider_records_by_ref(providers)
    selected = _selected_instance_ids(plan) if selected_only else None
    diagnostics: list[FinalizerProviderDiagnostic] = []

    diagnostics.extend(_duplicate_provider_ref_diagnostics(providers))
    for instance in config.instances.values():
        if selected is not None and instance.instance_id not in selected:
            continue
        diagnostics.extend(_diagnose_instance_provider(instance, by_ref, providers))
        if instance.provider_ref == BUILTIN_COMMAND_PROVIDER_REF:
            _parsed, command_diagnostics = parse_command_finalizer_config(instance)
            diagnostics.extend(command_diagnostics)

    diagnostics.extend(_required_plugin_diagnostics(config, selected))
    return tuple(diagnostics)


def parse_command_finalizer_config(
    instance: ConfiguredFinalizerInstance,
) -> tuple[CommandFinalizerConfig | None, tuple[FinalizerProviderDiagnostic, ...]]:
    """Validate and normalize a trusted ``builtin@command`` instance config."""

    config = instance.config
    diagnostics: list[FinalizerProviderDiagnostic] = []
    unknown = sorted(set(config) - _COMMAND_CONFIG_KEYS)
    for key in unknown:
        diagnostics.append(
            _command_diagnostic(
                instance,
                "unknown_command_config_key",
                f"builtin@command config key {key!r} is not supported",
                path=f"config.{key}",
            )
        )

    command = _command_argv(config.get("command"), instance, diagnostics)
    cwd = _command_cwd(config.get("cwd", "primary"), instance, diagnostics)
    timeout_seconds = _command_timeout(
        config.get("timeout", "120s"),
        instance,
        diagnostics,
    )
    submission = _command_submission(
        config.get("submission", "none"),
        instance,
        diagnostics,
    )
    env = _command_env(config.get("env", []), instance, diagnostics)

    if diagnostics:
        return None, tuple(diagnostics)
    return (
        CommandFinalizerConfig(
            command=tuple(command),
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            submission=submission,
            env=tuple(env),
        ),
        (),
    )


def diagnostic_to_json(diagnostic: FinalizerProviderDiagnostic) -> dict[str, object]:
    """Project a provider diagnostic to stable JSON."""

    payload: dict[str, object] = {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
    }
    if diagnostic.instance_id is not None:
        payload["instance_id"] = diagnostic.instance_id
    if diagnostic.provider_ref is not None:
        payload["provider_ref"] = diagnostic.provider_ref
    if diagnostic.layer is not None:
        payload["layer"] = diagnostic.layer
    if diagnostic.path is not None:
        payload["path"] = diagnostic.path
    return payload


def redact_config(value: Any) -> Any:
    """Return a stable, secret-safe view of provider-specific config."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>" if _looks_sensitive(str(key)) else redact_config(item)
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    if isinstance(value, tuple):
        return [redact_config(item) for item in value]
    return value


def fatal_provider_diagnostics(
    diagnostics: Sequence[FinalizerProviderDiagnostic],
) -> tuple[FinalizerProviderDiagnostic, ...]:
    """Return provider diagnostics that fail launch/execution."""

    return tuple(item for item in diagnostics if item.severity == "error")


def _selected_instance_ids(plan: FinalizerPlanWire | None) -> frozenset[str]:
    if plan is None:
        return frozenset()
    return frozenset(entry.instance_id for entry in plan.entries)


def _diagnose_instance_provider(
    instance: ConfiguredFinalizerInstance,
    providers_by_ref: Mapping[str, FinalizerProviderRecord],
    providers: Sequence[FinalizerProviderRecord],
) -> tuple[FinalizerProviderDiagnostic, ...]:
    provider_ref = instance.provider_ref
    try:
        plugin, provider_id = parse_plugin_qualified_id(provider_ref)
    except PluginQualifiedIdError as exc:
        return (
            FinalizerProviderDiagnostic(
                severity="error",
                code="invalid_provider_ref",
                message=str(exc),
                instance_id=instance.instance_id,
                provider_ref=provider_ref,
            ),
        )
    plugin = canonical_plugin_prefix(plugin)
    canonical_ref = f"{plugin}@{provider_id}"
    provider = providers_by_ref.get(canonical_ref)
    if provider is None:
        same_provider = [
            item
            for item in providers
            if item.provider_id == provider_id
            and canonical_plugin_prefix(item.package) != plugin
        ]
        if same_provider:
            packages = ", ".join(sorted(item.package for item in same_provider))
            return (
                FinalizerProviderDiagnostic(
                    severity="error",
                    code="provider_distribution_mismatch",
                    message=(
                        f"{provider_ref!r} was not found; provider "
                        f"{provider_id!r} is installed under package {packages}"
                    ),
                    instance_id=instance.instance_id,
                    provider_ref=provider_ref,
                ),
            )
        return (
            FinalizerProviderDiagnostic(
                severity="error",
                code="missing_provider",
                message=f"finalizer provider {provider_ref!r} is not installed",
                instance_id=instance.instance_id,
                provider_ref=provider_ref,
            ),
        )
    if provider.disabled_by:
        joined = ", ".join(provider.disabled_by)
        return (
            FinalizerProviderDiagnostic(
                severity="error",
                code="provider_disabled",
                message=f"finalizer provider {provider_ref!r} is disabled by {joined}",
                instance_id=instance.instance_id,
                provider_ref=provider_ref,
            ),
        )
    return ()


def _duplicate_provider_ref_diagnostics(
    providers: Sequence[FinalizerProviderRecord],
) -> tuple[FinalizerProviderDiagnostic, ...]:
    seen: set[str] = set()
    duplicates: list[FinalizerProviderDiagnostic] = []
    for provider in providers:
        key = provider_ref_key(provider.provider_ref)
        if key not in seen:
            seen.add(key)
            continue
        duplicates.append(
            FinalizerProviderDiagnostic(
                severity="error",
                code="duplicate_provider",
                message=f"duplicate finalizer provider {key!r}",
                provider_ref=key,
            )
        )
    return tuple(duplicates)


def _required_plugin_diagnostics(
    config: FinalizerConfig,
    selected: frozenset[str] | None,
) -> tuple[FinalizerProviderDiagnostic, ...]:
    external_prefixes = _external_prefixes(config, selected)
    if not external_prefixes:
        return ()
    try:
        merged_config = load_merged_config()
    except Exception as exc:
        return (
            FinalizerProviderDiagnostic(
                severity="error",
                code="required_plugins_unreadable",
                message=(
                    "could not load merged config for plugins.required: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ),
        )

    report = resolve_required_plugins(merged_config)
    diagnostics: list[FinalizerProviderDiagnostic] = []
    for issue in report.issues:
        issue_name = getattr(issue, "name", None)
        config_path = getattr(issue, "config_path", None)
        normalized = (
            normalize_distribution_name(issue_name)
            if isinstance(issue_name, str)
            else None
        )
        finalizer_path = isinstance(config_path, str) and config_path.startswith(
            "finalizers."
        )
        if normalized not in external_prefixes and not finalizer_path:
            continue
        diagnostics.append(
            FinalizerProviderDiagnostic(
                severity="error",
                code=f"required_plugin_{getattr(issue, 'kind', 'invalid')}",
                message=str(getattr(issue, "message", "invalid plugins.required")),
                layer="merged",
                path=config_path if isinstance(config_path, str) else None,
            )
        )
    return tuple(diagnostics)


def _external_prefixes(
    config: FinalizerConfig,
    selected: frozenset[str] | None,
) -> frozenset[str]:
    prefixes: set[str] = set()
    for instance in config.instances.values():
        if selected is not None and instance.instance_id not in selected:
            continue
        try:
            plugin, _provider_id = parse_plugin_qualified_id(instance.provider_ref)
        except PluginQualifiedIdError:
            continue
        if plugin.casefold() == BUILTIN_PLUGIN_PREFIX:
            continue
        prefixes.add(canonical_plugin_prefix(plugin))
    return frozenset(prefixes)


def _command_argv(
    value: object,
    instance: ConfiguredFinalizerInstance,
    diagnostics: list[FinalizerProviderDiagnostic],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_argv",
                "builtin@command config.command must be an argv list of strings",
                path="config.command",
            )
        )
        return ()
    argv: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item:
            argv.append(item)
            continue
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_argv",
                "builtin@command argv entries must be non-empty strings",
                path=f"config.command[{index}]",
            )
        )
    if not argv:
        diagnostics.append(
            _command_diagnostic(
                instance,
                "empty_command_argv",
                "builtin@command config.command must not be empty",
                path="config.command",
            )
        )
    return tuple(argv)


def _command_cwd(
    value: object,
    instance: ConfiguredFinalizerInstance,
    diagnostics: list[FinalizerProviderDiagnostic],
) -> str:
    if value == "primary":
        return "primary"
    diagnostics.append(
        _command_diagnostic(
            instance,
            "invalid_command_cwd",
            "builtin@command config.cwd must be 'primary'",
            path="config.cwd",
        )
    )
    return "primary"


def _command_timeout(
    value: object,
    instance: ConfiguredFinalizerInstance,
    diagnostics: list[FinalizerProviderDiagnostic],
) -> float:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return float(value)
    if isinstance(value, float) and value > 0:
        return value
    if not isinstance(value, str):
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_timeout",
                "builtin@command config.timeout must be a positive duration",
                path="config.timeout",
            )
        )
        return 120.0
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_timeout",
                "builtin@command config.timeout must be an integer followed by ms, s, m, or h",
                path="config.timeout",
            )
        )
        return 120.0
    amount, unit = match.groups()
    seconds = int(amount) * _DURATION_MULTIPLIERS[unit]
    if seconds <= 0:
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_timeout",
                "builtin@command config.timeout must be positive",
                path="config.timeout",
            )
        )
        return 120.0
    return seconds


def _command_submission(
    value: object,
    instance: ConfiguredFinalizerInstance,
    diagnostics: list[FinalizerProviderDiagnostic],
) -> str:
    if value == "none":
        return "none"
    diagnostics.append(
        _command_diagnostic(
            instance,
            "invalid_command_submission",
            "builtin@command version 1 supports only submission: none",
            path="config.submission",
        )
    )
    return "none"


def _command_env(
    value: object,
    instance: ConfiguredFinalizerInstance,
    diagnostics: list[FinalizerProviderDiagnostic],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_env",
                "builtin@command config.env must be a list of environment names",
                path="config.env",
            )
        )
        return ()
    names: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and _ENV_NAME_RE.fullmatch(item):
            names.append(item)
            continue
        diagnostics.append(
            _command_diagnostic(
                instance,
                "invalid_command_env",
                "builtin@command env entries must be valid environment names",
                path=f"config.env[{index}]",
            )
        )
    return tuple(names)


def _command_diagnostic(
    instance: ConfiguredFinalizerInstance,
    code: str,
    message: str,
    *,
    path: str,
) -> FinalizerProviderDiagnostic:
    return FinalizerProviderDiagnostic(
        severity="error",
        code=code,
        message=message,
        instance_id=instance.instance_id,
        provider_ref=instance.provider_ref,
        layer=_instance_source_layer(instance),
        path=f"finalizers.instances.{instance.instance_id}.{path}",
    )


def _instance_source_layer(instance: ConfiguredFinalizerInstance) -> str | None:
    provenance = instance.provenance.get("use")
    return None if provenance is None else provenance.layer


def _looks_sensitive(key: str) -> bool:
    lowered = key.casefold()
    return any(
        fragment in lowered
        for fragment in ("secret", "token", "password", "passwd", "credential")
    )


__all__ = [
    "BUILTIN_COMMAND_PROVIDER_REF",
    "BUILTIN_COMMIT_PROVIDER_REF",
    "BUILTIN_PROVIDER_REFS",
    "CommandFinalizerConfig",
    "FINALIZER_ENTRY_POINT_GROUP",
    "FinalizerProviderDiagnostic",
    "FinalizerProviderRecord",
    "canonical_provider_ref",
    "collect_finalizer_providers",
    "diagnose_finalizer_providers",
    "diagnostic_to_json",
    "fatal_provider_diagnostics",
    "parse_command_finalizer_config",
    "provider_records_by_ref",
    "provider_ref_key",
    "redact_config",
]
