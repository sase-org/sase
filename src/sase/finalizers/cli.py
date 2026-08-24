"""Presentation helpers for the ``sase final`` command group."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.core.finalizer_facade import resolve_finalizer_plan
from sase.core.finalizer_wire import FinalizerPlanWire
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerConfigDiagnostic,
    load_finalizer_config,
)
from sase.finalizers.providers import (
    FinalizerProviderDiagnostic,
    collect_finalizer_providers,
    diagnose_finalizer_providers,
    diagnostic_to_json,
    provider_records_by_ref,
    provider_ref_key,
    redact_config,
)


FINALIZER_CLI_JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FinalizerInstanceView:
    """Rendered view of one configured finalizer instance."""

    instance_id: str
    provider_ref: str
    selected: bool
    default: bool
    required: bool
    after: tuple[str, ...]
    max_attempts: int
    refusal: str
    source_layer: str
    health: str
    diagnostics: tuple[dict[str, object], ...]


ConfigFn = Callable[[], FinalizerConfig]


def handle_final_list(
    *,
    format_name: str,
    console: Console | None = None,
    config_fn: ConfigFn = load_finalizer_config,
) -> int:
    """Render effective finalizer instances and provider provenance."""

    view = build_finalizer_inventory(config_fn=config_fn)
    if format_name == "json":
        print(json.dumps(view, indent=2, sort_keys=True))
        return 0
    output = console or Console()
    _render_list_pretty(view, output)
    return 0


def handle_final_show(
    instance_id: str,
    *,
    format_name: str,
    console: Console | None = None,
    config_fn: ConfigFn = load_finalizer_config,
) -> int:
    """Render one finalizer instance and provider contract."""

    view = build_finalizer_inventory(config_fn=config_fn)
    instances = {
        str(instance["instance_id"]): instance for instance in view["instances"]
    }
    instance = instances.get(instance_id)
    if instance is None:
        _print_error(console, f"finalizer instance {instance_id!r} is not configured")
        return 1
    payload = {
        "schema_version": FINALIZER_CLI_JSON_SCHEMA_VERSION,
        "instance": instance,
        "provider": _provider_for_instance(view, instance),
    }
    if format_name == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    output = console or Console()
    _render_show_pretty(payload, output)
    return 0


def handle_final_doctor(
    *,
    format_name: str,
    console: Console | None = None,
    config_fn: ConfigFn = load_finalizer_config,
) -> int:
    """Render finalizer configuration and provider diagnostics."""

    view = build_finalizer_inventory(config_fn=config_fn)
    diagnostics = list(view["diagnostics"])
    payload = {
        "schema_version": FINALIZER_CLI_JSON_SCHEMA_VERSION,
        "ok": not any(item.get("severity") == "error" for item in diagnostics),
        "diagnostics": diagnostics,
    }
    if format_name == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
    output = console or Console()
    if payload["ok"]:
        output.print("[green]Finalizers: ok[/green]")
        return 0
    table = Table(title="Finalizer Diagnostics", header_style="bold", show_lines=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Code", no_wrap=True)
    table.add_column("Location", overflow="fold")
    table.add_column("Message", ratio=2, overflow="fold")
    for item in diagnostics:
        table.add_row(
            str(item.get("severity", "")),
            str(item.get("code", "")),
            _diagnostic_location(item),
            str(item.get("message", "")),
        )
    output.print(table)
    return 1


def build_finalizer_inventory(
    *,
    config_fn: ConfigFn = load_finalizer_config,
) -> dict[str, Any]:
    """Build the stable data model shared by finalizer CLI commands."""

    config = config_fn()
    plan, plan_diagnostic = _resolve_default_plan(config)
    providers = collect_finalizer_providers()
    provider_diagnostics = diagnose_finalizer_providers(config, plan=plan)
    diagnostics = [_config_diagnostic_to_json(item) for item in config.diagnostics] + [
        diagnostic_to_json(item) for item in provider_diagnostics
    ]
    if plan_diagnostic is not None:
        diagnostics.append(diagnostic_to_json(plan_diagnostic))
    selected = (
        frozenset(entry.instance_id for entry in plan.entries)
        if plan is not None
        else frozenset()
    )
    provider_map = provider_records_by_ref(providers)
    configured_refs = {
        provider_ref_key(instance.provider_ref)
        for instance in config.instances.values()
    }
    return {
        "schema_version": FINALIZER_CLI_JSON_SCHEMA_VERSION,
        "defaults": list(config.defaults),
        "required": list(config.required),
        "selected": sorted(selected),
        "instances": [
            asdict(
                _instance_view(
                    instance,
                    config=config,
                    selected=selected,
                    diagnostics=provider_diagnostics,
                )
            )
            | {"config": redact_config(dict(instance.config))}
            for instance in sorted(
                config.instances.values(),
                key=lambda item: item.instance_id,
            )
        ],
        "providers": [
            {
                "provider_ref": provider.provider_ref,
                "provider_id": provider.provider_id,
                "package": provider.package,
                "version": provider.version,
                "builtin": provider.builtin,
                "entry_point": provider.entry_point,
                "disabled_by": list(provider.disabled_by),
                "capabilities": list(provider.capabilities),
                "load_status": provider.load_status,
                "load_error": provider.load_error,
                "configured": provider_ref_key(provider.provider_ref)
                in configured_refs,
            }
            for provider in providers
        ],
        "diagnostics": diagnostics,
        "provider_count": len(provider_map),
    }


def _resolve_default_plan(
    config: FinalizerConfig,
) -> tuple[FinalizerPlanWire | None, FinalizerProviderDiagnostic | None]:
    fatal = config.fatal_diagnostics()
    if fatal:
        return None, None
    try:
        return resolve_finalizer_plan(config.to_plan_input([])), None
    except Exception as exc:
        return (
            None,
            FinalizerProviderDiagnostic(
                severity="error",
                code="plan_resolution_failed",
                message=f"could not resolve finalizer defaults: {exc}",
            ),
        )


def _instance_view(
    instance: ConfiguredFinalizerInstance,
    *,
    config: FinalizerConfig,
    selected: frozenset[str],
    diagnostics: Sequence[FinalizerProviderDiagnostic],
) -> FinalizerInstanceView:
    instance_diagnostics = tuple(
        diagnostic_to_json(item)
        for item in diagnostics
        if item.instance_id == instance.instance_id
        or (
            item.provider_ref is not None
            and provider_ref_key(item.provider_ref)
            == provider_ref_key(instance.provider_ref)
        )
    )
    health = (
        "error"
        if any(item.get("severity") == "error" for item in instance_diagnostics)
        else "ok"
    )
    return FinalizerInstanceView(
        instance_id=instance.instance_id,
        provider_ref=instance.provider_ref,
        selected=instance.instance_id in selected,
        default=instance.instance_id in config.defaults,
        required=instance.instance_id in config.required,
        after=tuple(instance.after),
        max_attempts=instance.max_attempts,
        refusal=instance.refusal,
        source_layer=_source_layer(instance),
        health=health,
        diagnostics=instance_diagnostics,
    )


def _source_layer(instance: ConfiguredFinalizerInstance) -> str:
    provenance = instance.provenance.get("use")
    return "unknown" if provenance is None else provenance.layer


def _config_diagnostic_to_json(
    diagnostic: FinalizerConfigDiagnostic,
) -> dict[str, object]:
    return {
        "severity": diagnostic.severity,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "layer": diagnostic.layer,
        "path": diagnostic.path,
    }


def _render_list_pretty(view: Mapping[str, Any], console: Console) -> None:
    instances = view["instances"]
    if not instances:
        console.print("[dim]No finalizer instances configured.[/dim]")
        return
    table = Table(title="Finalizers", header_style="bold", show_lines=True)
    table.add_column("Instance", min_width=12, overflow="fold")
    table.add_column("State", no_wrap=True)
    table.add_column("Provider", min_width=16, overflow="fold")
    table.add_column("Source", min_width=10, overflow="fold")
    table.add_column("After", overflow="fold")
    table.add_column("Health", no_wrap=True)
    for item in instances:
        table.add_row(
            Text(str(item["instance_id"]), style="bold cyan"),
            _state_text(item),
            str(item["provider_ref"]),
            str(item["source_layer"]),
            ", ".join(item["after"]) if item["after"] else "-",
            str(item["health"]),
        )
    console.print(table)
    unconfigured = [
        provider
        for provider in view["providers"]
        if not provider["configured"] and not provider["builtin"]
    ]
    if unconfigured:
        names = ", ".join(str(provider["provider_ref"]) for provider in unconfigured)
        console.print(f"[dim]Available plugin providers not configured: {names}[/dim]")


def _render_show_pretty(payload: Mapping[str, Any], console: Console) -> None:
    instance = payload["instance"]
    provider = payload["provider"]
    table = Table(title=f"Finalizer {instance['instance_id']}", show_header=False)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value", overflow="fold")
    table.add_row("provider", str(instance["provider_ref"]))
    table.add_row("selected", str(instance["selected"]).lower())
    table.add_row("default", str(instance["default"]).lower())
    table.add_row("required", str(instance["required"]).lower())
    table.add_row("after", ", ".join(instance["after"]) if instance["after"] else "-")
    table.add_row("source", str(instance["source_layer"]))
    table.add_row("health", str(instance["health"]))
    table.add_row("refusal", _refusal_text(str(instance["refusal"])))
    table.add_row("config", json.dumps(instance["config"], sort_keys=True))
    if provider is not None:
        table.add_row("provider package", str(provider["package"]))
        table.add_row("provider version", str(provider["version"]))
        table.add_row("entry point", str(provider["entry_point"] or "-"))
    console.print(table)


def _refusal_text(refusal: str) -> str:
    return f"[yellow]{refusal}[/yellow]" if refusal == "defer" else refusal


def _state_text(item: Mapping[str, Any]) -> str:
    labels: list[str] = []
    if item["selected"]:
        labels.append("selected")
    if item["default"]:
        labels.append("default")
    if item["required"]:
        labels.append("required")
    return ", ".join(labels) if labels else "-"


def _provider_for_instance(
    view: Mapping[str, Any],
    instance: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    instance_ref = instance["provider_ref"]
    if not isinstance(instance_ref, str):
        return None
    instance_key = provider_ref_key(instance_ref)
    for provider in view["providers"]:
        provider_ref = provider["provider_ref"]
        if (
            isinstance(provider_ref, str)
            and provider_ref_key(provider_ref) == instance_key
        ):
            return provider
    return None


def _diagnostic_location(item: Mapping[str, object]) -> str:
    for key in ("path", "instance_id", "provider_ref", "layer"):
        value = item.get(key)
        if value:
            return str(value)
    return "-"


def _print_error(console: Console | None, message: str) -> None:
    output = console or Console(stderr=True)
    output.print(f"[red]{message}[/red]")


__all__ = [
    "FINALIZER_CLI_JSON_SCHEMA_VERSION",
    "build_finalizer_inventory",
    "handle_final_doctor",
    "handle_final_list",
    "handle_final_show",
]
