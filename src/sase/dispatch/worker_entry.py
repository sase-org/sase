"""Subprocess entry point for isolated third-party dispatch providers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import importlib.metadata
import json
import sys
from typing import Any

import pluggy

from sase.dispatch.provider_hooks import (
    DISPATCH_ENTRY_POINT_GROUP,
    DispatchProviderHookSpec,
    iter_mapping_specs,
)
from sase.dispatch.provider_protocol import DISPATCH_PROVIDER_PROTOCOL_VERSION
from sase.dispatch.provider_runtime import provider_ref_key
from sase.plugins.qualified_id import PluginQualifiedIdError, parse_plugin_qualified_id
from sase.version._utils import metadata_value, normalize_distribution_name


def main(argv: Sequence[str] | None = None) -> int:
    """Load one ``sase_dispatch`` entry point and run one hook operation."""

    parser = argparse.ArgumentParser(prog="python -m sase.dispatch.worker_entry")
    parser.add_argument("--provider-ref", required=True)
    parser.add_argument("--operation", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        entry_point = _find_entry_point(args.provider_ref)
        loaded = entry_point.load()
        plugin = loaded() if isinstance(loaded, type) else loaded
        request = json.loads(sys.stdin.read() or "{}")
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        result = _run_operation(plugin, args.operation, args.provider_ref, request)
        json.dump(result, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        payload = {
            "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
            "operation": args.operation,
            "provider_ref": args.provider_ref,
            "status": "failed",
            "diagnostics": [
                {
                    "code": "worker_exception",
                    "severity": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 1


def _run_operation(
    plugin: object,
    operation: str,
    provider_ref: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    pm = pluggy.PluginManager("sase_dispatch")
    pm.add_hookspecs(DispatchProviderHookSpec)
    pm.register(plugin)
    canonical_provider_ref = provider_ref_key(provider_ref)

    if operation == "specs":
        raw_specs = pm.hook.dispatch_provider_specs()
        return _ok(
            operation,
            canonical_provider_ref,
            specs=[
                dict(item)
                for result in raw_specs
                for item in iter_mapping_specs(result)
            ],
        )
    if operation == "discover":
        raw_candidates = pm.hook.dispatch_discover(
            provider_ref=canonical_provider_ref,
            config=_mapping(request.get("config")),
            timeout_seconds=_timeout_seconds(request),
        )
        return _ok(
            operation,
            canonical_provider_ref,
            candidates=[
                dict(item)
                for result in raw_candidates
                for item in iter_mapping_specs(result)
            ],
        )
    if operation == "connection_plan":
        raw_plans = pm.hook.dispatch_connection_plan(
            provider_ref=canonical_provider_ref,
            machine=_mapping(request.get("machine")),
            config=_mapping(request.get("config")),
            timeout_seconds=_timeout_seconds(request),
        )
        plans = [
            dict(item) for result in raw_plans for item in iter_mapping_specs(result)
        ]
        payload = _ok(operation, canonical_provider_ref)
        if plans:
            payload["plan"] = plans[0]
        return payload
    raise ValueError(f"unsupported dispatch provider operation {operation!r}")


def _ok(operation: str, provider_ref: str, **extra: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": DISPATCH_PROVIDER_PROTOCOL_VERSION,
        "operation": operation,
        "provider_ref": provider_ref_key(provider_ref),
        "status": "ok",
    }
    payload.update(extra)
    return payload


def _find_entry_point(provider_ref: str) -> importlib.metadata.EntryPoint:
    try:
        package, provider_id = parse_plugin_qualified_id(provider_ref)
    except PluginQualifiedIdError as exc:
        raise ValueError(f"invalid dispatch provider ref {provider_ref!r}") from exc
    normalized_package = normalize_distribution_name(package)
    for entry_point in importlib.metadata.entry_points(
        group=DISPATCH_ENTRY_POINT_GROUP
    ):
        dist_name = _entry_point_distribution_name(entry_point)
        if dist_name is None:
            continue
        if (
            normalize_distribution_name(dist_name) == normalized_package
            and entry_point.name == provider_id
        ):
            return entry_point
    raise ValueError(f"dispatch provider {provider_ref!r} is not installed")


def _entry_point_distribution_name(
    entry_point: importlib.metadata.EntryPoint,
) -> str | None:
    dist = getattr(entry_point, "dist", None)
    name = metadata_value(getattr(dist, "metadata", None), "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    return direct_name if isinstance(direct_name, str) and direct_name else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timeout_seconds(request: Mapping[str, Any]) -> float:
    value = request.get("timeout_seconds", 5.0)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 5.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 5.0
    return parsed if parsed > 0 else 5.0


if __name__ == "__main__":
    raise SystemExit(main())
