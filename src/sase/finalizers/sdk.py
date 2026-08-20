"""Small SDK helpers for external ``sase_finalizers`` providers."""

from __future__ import annotations

from collections.abc import Mapping
import argparse
import json
import sys
from typing import Any, Protocol


class FinalizerProvider(Protocol):
    """Object protocol accepted by the worker dispatcher."""

    def describe(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def validate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def verify(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


def dispatch_provider_request(
    provider: object,
    request: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Dispatch a JSON request to a provider entry-point object.

    Plugin authors may expose either an object with methods named after the
    finalizer operations, a callable that accepts the full request mapping, or
    a factory that returns a method-bearing object when called with no
    arguments.
    """

    operation = request.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError("finalizer request requires operation")

    target = provider
    method = getattr(target, operation, None)
    if method is None and callable(target):
        try:
            result = target(request)
        except TypeError:
            target = target()
        else:
            return _mapping_result(result)
        method = getattr(target, operation, None)
    if not callable(method):
        raise ValueError(f"provider does not implement operation {operation!r}")
    return _mapping_result(method(request))


def sdk_worker_main(
    provider: object,
    *,
    argv: list[str] | None = None,
) -> int:
    """Run a provider object as a JSON stdin/stdout worker."""

    parser = argparse.ArgumentParser(prog="sase-finalizer-provider")
    parser.add_argument("--operation", required=True)
    args = parser.parse_args(argv)
    try:
        request = json.loads(sys.stdin.read())
        if not isinstance(request, Mapping):
            raise ValueError("request must be a JSON object")
        enriched_request = dict(request)
        enriched_request.setdefault("operation", args.operation)
        result = dispatch_provider_request(provider, enriched_request)
        json.dump(dict(result), sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "operation": args.operation,
            "status": "failed",
            "diagnostics": [
                {
                    "code": "provider_exception",
                    "severity": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 1


def _mapping_result(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("provider operation must return a JSON object mapping")
    return value


__all__ = [
    "FinalizerProvider",
    "dispatch_provider_request",
    "sdk_worker_main",
]
