"""Small SDK helpers for external ``sase_finalizers`` providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import argparse
import inspect
import json
import sys
from typing import Any, Literal, Protocol, cast


class FinalizerProvider(Protocol):
    """Object protocol accepted by the worker dispatcher."""

    def describe(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def validate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def verify(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ProviderShapeError(ValueError):
    """Raised when a provider entry point has an unsupported or ambiguous shape."""


def dispatch_provider_request(
    provider: object,
    request: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Dispatch a JSON request to a provider entry-point object.

    The entry point is classified before any provider code runs and must match
    exactly one of these shapes:

    * a method-bearing object with a callable named after the operation
    * a zero-argument factory, including a class whose ``__init__`` takes no
      required arguments, that returns a method-bearing object
    * a callable that accepts the request mapping

    Method-bearing objects win over ``__call__``. Ambiguous shapes, including
    optional positional parameters and ``*args``, are rejected with
    :class:`ProviderShapeError` and are never invoked. ``TypeError`` raised by
    provider code is reported unchanged; it is not a factory signal.
    """

    operation = request.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError("finalizer request requires operation")
    call = _bind_provider_operation(provider, operation)
    return _mapping_result(call(request))


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


def _bind_provider_operation(
    provider: object,
    operation: str,
) -> Callable[[Mapping[str, Any]], object]:
    method = _operation_method(provider, operation)
    if method is not None:
        return method
    if inspect.isclass(provider) or callable(provider):
        shape = _callable_shape(provider)
        if inspect.isclass(provider) or shape == "factory":
            if shape != "factory":
                raise ProviderShapeError(
                    "class provider entry points must be zero-argument factories "
                    f"that return an object implementing {operation!r}"
                )
            instance = cast("Callable[[], object]", provider)()
            bound = _operation_method(instance, operation)
            if bound is None:
                raise ValueError(f"provider does not implement operation {operation!r}")
            return bound
        if shape == "request":
            return cast("Callable[[Mapping[str, Any]], object]", provider)
        raise ProviderShapeError(
            "provider entry point is ambiguous; expose a method-bearing object, "
            "a zero-argument factory that returns one, or a callable that "
            "accepts the request mapping"
        )
    raise ValueError(f"provider does not implement operation {operation!r}")


def _operation_method(
    target: object, operation: str
) -> Callable[[Mapping[str, Any]], object] | None:
    if inspect.isclass(target):
        return None
    method = getattr(target, operation, None)
    if not callable(method):
        return None
    return cast("Callable[[Mapping[str, Any]], object]", method)


def _callable_shape(fn: object) -> Literal["factory", "request", "ambiguous"]:
    try:
        signature = inspect.signature(cast("Callable[..., Any]", fn))
    except (TypeError, ValueError):
        return "ambiguous"
    required_positional = 0
    optional_positional = False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return "ambiguous"
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            if parameter.default is parameter.empty:
                return "ambiguous"
            continue
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if parameter.default is parameter.empty:
            required_positional += 1
        else:
            optional_positional = True
    if optional_positional:
        return "ambiguous"
    if required_positional == 0:
        return "factory"
    if required_positional == 1:
        return "request"
    return "ambiguous"


def _mapping_result(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("provider operation must return a JSON object mapping")
    return value


__all__ = [
    "FinalizerProvider",
    "ProviderShapeError",
    "dispatch_provider_request",
    "sdk_worker_main",
]
