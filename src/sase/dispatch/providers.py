"""Dispatch provider discovery hooks."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import importlib.metadata
import json
import os
import sys
from typing import Any

import pluggy

from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    STDOUT_CAP_BYTES,
    run_bounded_subprocess,
)
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_prefix,
    canonical_plugin_qualified_id,
)
from sase.version._utils import metadata_value

from .config import load_dispatch_config, provider_config
from .models import (
    DispatchConfig,
    DispatchProviderSpec,
    DiscoveryCandidate,
    MachineDiagnostic,
    MachineRecord,
)
from .provider_protocol import DISPATCH_PROVIDER_PROTOCOL_VERSION

DISPATCH_ENTRY_POINT_GROUP = "sase_dispatch"
_BUILTIN_PROVIDER_REFS = frozenset({"builtin@https", "builtin@tailnet"})
_PROVIDER_OPERATION_TIMEOUT_SECONDS = 30.0
_BASE_PROVIDER_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
)
_PROVIDER_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "provider_ref",
        "status",
        "diagnostics",
        "specs",
        "candidates",
        "plan",
    }
)

hookspec = pluggy.HookspecMarker("sase_dispatch")
hookimpl = pluggy.HookimplMarker("sase_dispatch")


class DispatchProviderHookSpec:
    """Hook specifications for remote dispatch providers."""

    @hookspec
    def dispatch_provider_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return remote dispatch provider specs."""
        ...

    @hookspec
    def dispatch_discover(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return explicit remote machine discovery candidates."""
        ...

    @hookspec
    def dispatch_connection_plan(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        machine: Mapping[str, Any],
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any] | None:
        """Return a serializable fleet connection plan for one machine."""
        ...


# symvision: pyproject.toml
class BuiltinDispatchProviders:
    """Built-in providers that require explicit configuration to do work."""

    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": "builtin@https",
                "display_name": "HTTPS Fleet Gateway",
                "supports_discovery": False,
                "builtin": True,
            },
            {
                "ref": "builtin@tailnet",
                "display_name": "Tailnet Fleet Gateway",
                "supports_discovery": True,
                "builtin": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[Mapping[str, Any], ...]:
        del config, timeout_seconds
        if provider_ref == "builtin@tailnet":
            return ()
        return ()


@dataclass(frozen=True)
class _DispatchProviderInventory:
    """Provider specs and non-fatal discovery diagnostics."""

    specs: tuple[DispatchProviderSpec, ...]
    diagnostics: tuple[MachineDiagnostic, ...] = ()

    def by_ref(self) -> dict[str, DispatchProviderSpec]:
        return {spec.ref: spec for spec in self.specs}


@dataclass(frozen=True)
class _DispatchProviderRecord:
    """Metadata-only dispatch provider record."""

    provider_ref: str
    provider_id: str
    package: str
    version: str
    entry_point: str | None
    builtin: bool
    disabled_by: tuple[str, ...] = ()


class _DispatchProviderExecutionError(RuntimeError):
    """Raised when an isolated dispatch provider operation fails."""


_DispatchProviderOperationRunner = Callable[
    [_DispatchProviderRecord, str, Mapping[str, Any], float],
    Mapping[str, Any],
]


def collect_dispatch_providers(
    *,
    entry_points_fn: Any = importlib.metadata.entry_points,
) -> _DispatchProviderInventory:
    """Collect builtin and plugin dispatch providers without network IO."""
    specs: list[DispatchProviderSpec] = []
    diagnostics: list[MachineDiagnostic] = []

    _collect_plugin_specs(
        BuiltinDispatchProviders(),
        package="sase",
        version=_distribution_version("sase"),
        specs=specs,
        diagnostics=diagnostics,
    )

    disabled_by = _disabled_env_for_group()
    if disabled_by:
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_plugins_disabled",
                severity="info",
                message=(
                    "third-party dispatch providers disabled by "
                    + ", ".join(disabled_by)
                ),
            )
        )
    for ep in _entry_points(entry_points_fn):
        if _is_builtin_entry_point(ep) or disabled_by:
            continue
        record = _record_from_entry_point(ep, disabled_by=())
        if record is None:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_ref_invalid",
                    severity="error",
                    message=(
                        "dispatch provider entry point "
                        f"{getattr(ep, 'name', '<unknown>')} has an invalid "
                        "<plugin>@<id> reference"
                    ),
                )
            )
            continue
        specs.append(
            DispatchProviderSpec(
                ref=record.provider_ref,
                display_name=record.provider_id,
                supports_discovery=True,
                package=record.package,
                version=record.version,
                builtin=False,
            )
        )

    deduped: dict[str, DispatchProviderSpec] = {}
    for spec in specs:
        key = provider_ref_key(spec.ref)
        if key not in deduped:
            deduped[key] = spec
        else:
            diagnostics.append(
                MachineDiagnostic(
                    code="dispatch_provider_duplicate",
                    severity="warning",
                    message=f"duplicate dispatch provider ref ignored: {spec.ref}",
                )
            )
    return _DispatchProviderInventory(
        specs=tuple(deduped[key] for key in sorted(deduped)),
        diagnostics=tuple(diagnostics),
    )


def discover_dispatch_candidates(
    *,
    config: DispatchConfig | None = None,
    provider_refs: Sequence[str] = (),
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: _DispatchProviderOperationRunner | None = None,
) -> tuple[DiscoveryCandidate, ...]:
    """Run explicit provider discovery for enabled providers only."""
    resolved_config = load_dispatch_config() if config is None else config
    selected_refs = (
        tuple(provider_refs) or resolved_config.discovery_enabled_provider_refs
    )
    if not selected_refs:
        return ()

    candidates: list[DiscoveryCandidate] = []
    for provider, provider_ref in _iter_providers_for_refs(
        selected_refs,
        entry_points_fn=entry_points_fn,
    ):
        if not resolved_config.provider_enabled(provider_ref):
            continue
        provider_timeout = timeout_seconds or resolved_config.request_timeout_seconds
        provider_settings = provider_config(resolved_config, provider_ref)
        if provider.builtin:
            payloads = _safe_discover(
                BuiltinDispatchProviders(),
                provider_ref=provider_ref,
                config=provider_settings,
                timeout_seconds=provider_timeout,
            )
        else:
            payloads = _safe_discover_external(
                provider,
                config=provider_settings,
                timeout_seconds=provider_timeout,
                operation_runner=operation_runner or _run_dispatch_provider_operation,
            )
        for payload in payloads:
            candidate = _candidate_from_payload(provider_ref, payload)
            if candidate is not None:
                candidates.append(candidate)
    return tuple(sorted(_dedupe_candidates(candidates), key=lambda item: item.key))


def connection_plan_for_machine(
    machine: MachineRecord,
    *,
    config: DispatchConfig | None = None,
    timeout_seconds: float | None = None,
    entry_points_fn: Any = importlib.metadata.entry_points,
    operation_runner: _DispatchProviderOperationRunner | None = None,
) -> Mapping[str, Any]:
    """Return the provider-authored connection plan for *machine*.

    Builtin gateway-style providers derive their plan from the machine record.
    Third-party providers are imported only inside the isolated helper
    subprocess, and only for the selected machine's provider.
    """

    if machine.provider_ref in _BUILTIN_PROVIDER_REFS:
        return machine.to_connection_plan()

    resolved_config = load_dispatch_config() if config is None else config
    provider = _provider_record_by_ref(
        machine.provider_ref,
        entry_points_fn=entry_points_fn,
    )
    if provider is None:
        raise _DispatchProviderExecutionError(
            f"dispatch provider {machine.provider_ref!r} is not installed"
        )
    provider_timeout = timeout_seconds or resolved_config.request_timeout_seconds
    request = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": "connection_plan",
        "provider_ref": provider.provider_ref,
        "machine": _machine_payload(machine),
        "config": dict(provider_config(resolved_config, machine.provider_ref)),
        "timeout_seconds": provider_timeout,
    }
    result = (operation_runner or _run_dispatch_provider_operation)(
        provider,
        "connection_plan",
        request,
        provider_timeout,
    )
    _validate_provider_result(provider, "connection_plan", result)
    if result.get("status") != "ok":
        raise _DispatchProviderExecutionError(
            _provider_error_message(result, "connection plan failed")
        )
    plan = result.get("plan")
    if isinstance(plan, Mapping):
        return dict(plan)
    return machine.to_connection_plan()


def _run_dispatch_provider_operation(
    provider: _DispatchProviderRecord,
    operation: str,
    request: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Run one external dispatch provider operation in a bounded subprocess."""

    argv = [
        sys.executable,
        "-m",
        "sase.dispatch.worker_entry",
        "--provider-ref",
        provider.provider_ref,
        "--operation",
        operation,
    ]
    try:
        payload = json.dumps(dict(request), sort_keys=True).encode("utf-8")
    except Exception as exc:
        raise _DispatchProviderExecutionError(
            f"dispatch provider request is not JSON-serializable: {exc}"
        ) from exc
    if len(payload) > STDOUT_CAP_BYTES:
        raise _DispatchProviderExecutionError("dispatch provider request exceeded cap")
    timeout = min(
        timeout_seconds,
        _PROVIDER_OPERATION_TIMEOUT_SECONDS,
        HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    )
    try:
        completed = run_bounded_subprocess(
            argv,
            cwd=os.getcwd(),
            env=_sanitized_provider_env(request.get("config")),
            input_bytes=payload,
            timeout=timeout,
        )
    except Exception as exc:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} could not start: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if completed.timed_out:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} timed out after {timeout:g}s"
        )
    if completed.stdout_truncated or completed.stderr_truncated:
        raise _DispatchProviderExecutionError(
            "dispatch provider operation exceeded output cap"
        )
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except Exception as exc:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} emitted malformed JSON: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} must return a JSON object"
        )
    if completed.returncode != 0 and result.get("status") != "failed":
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} exited with "
            f"{completed.returncode}"
        )
    return result


def _collect_plugin_specs(
    plugin: object,
    *,
    package: str,
    version: str,
    specs: list[DispatchProviderSpec],
    diagnostics: list[MachineDiagnostic],
) -> None:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(DispatchProviderHookSpec)
    try:
        pm.register(plugin)
    except Exception as exc:  # noqa: BLE001 - provider diagnostics only.
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_provider_registration_failed",
                severity="error",
                message=f"dispatch provider registration failed: {type(exc).__name__}",
            )
        )
        return

    try:
        raw_specs = pm.hook.dispatch_provider_specs()
    except Exception as exc:  # noqa: BLE001 - provider diagnostics only.
        diagnostics.append(
            MachineDiagnostic(
                code="dispatch_provider_specs_failed",
                severity="error",
                message=f"dispatch provider spec hook failed: {type(exc).__name__}",
            )
        )
        return
    for raw in raw_specs:
        for payload in iter_mapping_specs(raw):
            spec = _spec_from_payload(payload, package=package, version=version)
            if spec is None:
                diagnostics.append(
                    MachineDiagnostic(
                        code="dispatch_provider_spec_invalid",
                        severity="error",
                        message="dispatch provider spec was missing a ref",
                    )
                )
                continue
            specs.append(spec)


def _iter_providers_for_refs(
    provider_refs: Sequence[str],
    *,
    entry_points_fn: Any,
) -> Iterable[tuple[_DispatchProviderRecord, str]]:
    refs = tuple(dict.fromkeys(provider_refs))
    builtin_records = {
        ref: _DispatchProviderRecord(
            provider_ref=ref,
            provider_id=ref.partition("@")[2],
            package="sase",
            version=_distribution_version("sase"),
            entry_point=None,
            builtin=True,
        )
        for ref in _BUILTIN_PROVIDER_REFS
    }
    for ref in refs:
        if ref in builtin_records:
            yield builtin_records[ref], ref
    if _disabled_env_for_group():
        return
    records = _third_party_records(entry_points_fn)
    by_ref = {provider_ref_key(record.provider_ref): record for record in records}
    for ref in refs:
        if ref in _BUILTIN_PROVIDER_REFS:
            continue
        record = by_ref.get(provider_ref_key(ref))
        if record is not None:
            yield record, ref


def _provider_record_by_ref(
    provider_ref: str,
    *,
    entry_points_fn: Any,
) -> _DispatchProviderRecord | None:
    key = provider_ref_key(provider_ref)
    for record in _third_party_records(entry_points_fn):
        if provider_ref_key(record.provider_ref) == key:
            return record
    return None


def _third_party_records(entry_points_fn: Any) -> tuple[_DispatchProviderRecord, ...]:
    records: list[_DispatchProviderRecord] = []
    for ep in _entry_points(entry_points_fn):
        if _is_builtin_entry_point(ep):
            continue
        record = _record_from_entry_point(ep, disabled_by=())
        if record is not None:
            records.append(record)
    return tuple(records)


def _safe_discover(
    plugin: object,
    *,
    provider_ref: str,
    config: Mapping[str, Any],
    timeout_seconds: float,
) -> tuple[Mapping[str, Any], ...]:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(DispatchProviderHookSpec)
    try:
        pm.register(plugin)
        results = pm.hook.dispatch_discover(
            provider_ref=provider_ref,
            config=config,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return ()
    payloads: list[Mapping[str, Any]] = []
    for result in results:
        payloads.extend(iter_mapping_specs(result))
    return tuple(payloads)


def _safe_discover_external(
    provider: _DispatchProviderRecord,
    *,
    config: Mapping[str, Any],
    timeout_seconds: float,
    operation_runner: _DispatchProviderOperationRunner,
) -> tuple[Mapping[str, Any], ...]:
    request = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": "discover",
        "provider_ref": provider.provider_ref,
        "config": dict(config),
        "timeout_seconds": timeout_seconds,
    }
    try:
        result = operation_runner(provider, "discover", request, timeout_seconds)
        _validate_provider_result(provider, "discover", result)
    except _DispatchProviderExecutionError:
        return ()
    if result.get("status") != "ok":
        return ()
    raw_candidates = result.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates, (str, bytes, bytearray)
    ):
        return ()
    return tuple(item for item in raw_candidates if isinstance(item, Mapping))


def _record_from_entry_point(
    ep: Any,
    *,
    disabled_by: tuple[str, ...],
) -> _DispatchProviderRecord | None:
    package = _entry_point_package(ep)
    provider_id = str(getattr(ep, "name", "") or "")
    try:
        provider_ref = _canonical_provider_ref_for_entry(
            package=package,
            name=provider_id,
        )
    except PluginQualifiedIdError:
        return None
    return _DispatchProviderRecord(
        provider_ref=provider_ref,
        provider_id=provider_id,
        package=package,
        version=_entry_point_version(ep),
        entry_point=_entry_point_value(ep),
        builtin=False,
        disabled_by=disabled_by,
    )


def _validate_provider_result(
    provider: _DispatchProviderRecord,
    operation: str,
    result: Mapping[str, Any],
) -> None:
    unknown = sorted(set(result) - _PROVIDER_RESULT_KEYS)
    if unknown:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned unknown field(s): "
            + ", ".join(unknown)
        )
    if result.get("schema_version") != DISPATCH_PROVIDER_PROTOCOL_VERSION:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned unsupported schema "
            f"{result.get('schema_version')!r}"
        )
    if result.get("operation") != operation:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned operation "
            f"{result.get('operation')!r}"
        )
    result_provider_ref = result.get("provider_ref")
    if not isinstance(result_provider_ref, str) or provider_ref_key(
        result_provider_ref
    ) != provider_ref_key(provider.provider_ref):
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned provider "
            f"{result.get('provider_ref')!r}"
        )
    status = result.get("status")
    if status not in {"ok", "failed"}:
        raise _DispatchProviderExecutionError(
            f"dispatch provider operation {operation!r} returned status {status!r}"
        )


def _provider_error_message(result: Mapping[str, Any], fallback: str) -> str:
    raw = result.get("diagnostics")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return fallback
    messages = [
        str(item.get("message"))
        for item in raw
        if isinstance(item, Mapping) and isinstance(item.get("message"), str)
    ]
    return messages[0] if messages else fallback


def _machine_payload(machine: MachineRecord) -> dict[str, object]:
    return {
        "alias": machine.alias,
        "provider_ref": machine.provider_ref,
        "endpoint": machine.endpoint,
        "credential_ref": machine.credential_ref,
        "pinned_installation_id": machine.pinned_installation_id,
        "connection_kind": machine.connection_kind,
        "tls": machine.tls.to_plan(),
        "quarantined": machine.quarantined,
        "quarantine_reason": machine.quarantine_reason,
    }


def _sanitized_provider_env(config: object) -> dict[str, str]:
    allowed = set(_BASE_PROVIDER_ENV_KEYS)
    if isinstance(config, Mapping):
        env_names = config.get("env")
        if isinstance(env_names, Sequence) and not isinstance(
            env_names, (str, bytes, bytearray)
        ):
            allowed.update(item for item in env_names if isinstance(item, str))
    env = {key: os.environ[key] for key in sorted(allowed) if key in os.environ}
    env["SASE_DISPATCH_PROVIDER_SUBPROCESS"] = "1"
    return env


def _spec_from_payload(
    payload: Mapping[str, Any],
    *,
    package: str,
    version: str,
) -> DispatchProviderSpec | None:
    ref = payload.get("ref")
    if not isinstance(ref, str) or not ref:
        return None
    display_name = payload.get("display_name")
    return DispatchProviderSpec(
        ref=ref,
        display_name=display_name if isinstance(display_name, str) else ref,
        supports_discovery=bool(payload.get("supports_discovery", False)),
        package=package,
        version=version,
        builtin=bool(payload.get("builtin", False)),
    )


def _candidate_from_payload(
    provider_ref: str,
    payload: Mapping[str, Any],
) -> DiscoveryCandidate | None:
    endpoint = payload.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return None
    display_name = payload.get("display_name")
    machine_selector = payload.get("machine_selector")
    installation_pin = payload.get("installation_pin")
    detail = payload.get("detail")
    return DiscoveryCandidate(
        provider_ref=provider_ref,
        endpoint=endpoint,
        display_name=display_name if isinstance(display_name, str) else "",
        machine_selector=machine_selector if isinstance(machine_selector, str) else "",
        installation_pin=installation_pin if isinstance(installation_pin, str) else "",
        detail=detail if isinstance(detail, str) else "",
    )


def _dedupe_candidates(
    candidates: Sequence[DiscoveryCandidate],
) -> tuple[DiscoveryCandidate, ...]:
    seen: dict[str, DiscoveryCandidate] = {}
    for candidate in candidates:
        seen.setdefault(candidate.key, candidate)
    return tuple(seen.values())


def iter_mapping_specs(value: object) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _entry_points(entry_points_fn: Any) -> tuple[Any, ...]:
    eps = entry_points_fn(group=DISPATCH_ENTRY_POINT_GROUP)
    return tuple(eps)


def _disabled_env_for_group() -> tuple[str, ...]:
    disabled: list[str] = []
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        disabled.append("SASE_DISABLE_PLUGINS")
    suffix = DISPATCH_ENTRY_POINT_GROUP.removeprefix("sase_").upper()
    env_key = f"SASE_DISABLE_PLUGIN_{suffix}"
    if os.environ.get(env_key):
        disabled.append(env_key)
    return tuple(disabled)


def _is_builtin_entry_point(ep: Any) -> bool:
    # The sase package registers its builtin providers both in code (above)
    # and as an entry point for plugin-inventory visibility; skip the entry
    # point so the providers are not collected twice.
    return (
        _entry_point_package(ep).lower() == "sase"
        and str(getattr(ep, "name", "")) == "builtin"
    )


def _entry_point_package(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = metadata_value(metadata, "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return ""


def _entry_point_version(ep: Any) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    return str(version) if version else ""


def _entry_point_value(ep: Any) -> str | None:
    value = getattr(ep, "value", None)
    return value if isinstance(value, str) and value else None


def _canonical_provider_ref_for_entry(*, package: str, name: str) -> str:
    return canonical_plugin_qualified_id(f"{canonical_plugin_prefix(package)}@{name}")


def provider_ref_key(value: str) -> str:
    """Return a canonical lookup key for syntactically valid provider refs."""

    try:
        return canonical_plugin_qualified_id(value)
    except PluginQualifiedIdError:
        return value


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


__all__ = [
    "DISPATCH_ENTRY_POINT_GROUP",
    "DispatchProviderHookSpec",
    "collect_dispatch_providers",
    "connection_plan_for_machine",
    "discover_dispatch_candidates",
    "hookimpl",
    "hookspec",
    "iter_mapping_specs",
    "provider_ref_key",
]
