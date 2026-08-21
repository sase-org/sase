"""Subprocess entry point for isolated external finalizer providers."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from collections.abc import Sequence

from sase.finalizers.providers import (
    FINALIZER_ENTRY_POINT_GROUP,
    canonical_provider_ref,
)
from sase.finalizers.sdk import ProviderShapeError, dispatch_provider_request
from sase.plugins.qualified_id import PluginQualifiedIdError
from sase.version._utils import metadata_value, normalize_distribution_name


def main(argv: Sequence[str] | None = None) -> int:
    """Load one ``sase_finalizers`` entry point and dispatch one request."""

    parser = argparse.ArgumentParser(prog="python -m sase.finalizers.worker_entry")
    parser.add_argument("--provider-ref", required=True)
    parser.add_argument("--operation", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        entry_point = _find_entry_point(args.provider_ref)
        provider = entry_point.load()
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        request.setdefault("operation", args.operation)
        result = dispatch_provider_request(provider, request)
        json.dump(dict(result), sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        code = (
            "provider_shape"
            if isinstance(exc, ProviderShapeError)
            else "worker_exception"
        )
        payload = {
            "schema_version": 1,
            "operation": args.operation,
            "provider_ref": args.provider_ref,
            "status": "failed",
            "diagnostics": [
                {
                    "code": code,
                    "severity": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 1


def _find_entry_point(provider_ref: str) -> importlib.metadata.EntryPoint:
    try:
        canonical = canonical_provider_ref(provider_ref)
    except PluginQualifiedIdError as exc:
        raise ValueError(f"invalid provider ref {provider_ref!r}") from exc
    package, _separator, provider_id = canonical.partition("@")
    for entry_point in importlib.metadata.entry_points(
        group=FINALIZER_ENTRY_POINT_GROUP
    ):
        dist_name = _entry_point_distribution_name(entry_point)
        if dist_name is None:
            continue
        if (
            normalize_distribution_name(dist_name) == package
            and entry_point.name == provider_id
        ):
            return entry_point
    raise ValueError(f"finalizer provider {provider_ref!r} is not installed")


def _entry_point_distribution_name(
    entry_point: importlib.metadata.EntryPoint,
) -> str | None:
    dist = getattr(entry_point, "dist", None)
    name = metadata_value(getattr(dist, "metadata", None), "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    return direct_name if isinstance(direct_name, str) and direct_name else None


if __name__ == "__main__":
    raise SystemExit(main())
