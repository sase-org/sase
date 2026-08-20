"""Subprocess entry point for isolated external finalizer providers."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from collections.abc import Sequence

from sase.finalizers.providers import FINALIZER_ENTRY_POINT_GROUP
from sase.finalizers.sdk import dispatch_provider_request


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
        payload = {
            "schema_version": 1,
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


def _find_entry_point(provider_ref: str) -> importlib.metadata.EntryPoint:
    package, separator, provider_id = provider_ref.partition("@")
    if not package or separator != "@" or not provider_id:
        raise ValueError(f"invalid provider ref {provider_ref!r}")
    for entry_point in importlib.metadata.entry_points(
        group=FINALIZER_ENTRY_POINT_GROUP
    ):
        dist = getattr(entry_point, "dist", None)
        metadata = getattr(dist, "metadata", None)
        dist_name = None
        if metadata is not None:
            getter = getattr(metadata, "get", None)
            if callable(getter):
                dist_name = getter("Name")
        if not dist_name:
            dist_name = getattr(dist, "name", None)
        if dist_name == package and entry_point.name == provider_id:
            return entry_point
    raise ValueError(f"finalizer provider {provider_ref!r} is not installed")


if __name__ == "__main__":
    raise SystemExit(main())
