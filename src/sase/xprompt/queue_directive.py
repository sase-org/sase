"""Thin Python adapter for the shared Rust `%queue` / `%q` contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any

from sase.core.rust import require_rust_binding


def collect_queue_fields(
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and merge queue occurrences through the Rust contract."""
    flags = launch_feature_flag_keys()
    payload = _collect_queue_fields_raw(occurrences, flags)
    if _has_legacy_capacity_keyword_error(payload):
        payload = _collect_queue_fields_raw(
            _legacy_capacity_occurrences(occurrences),
            flags,
        )
    return _normalize_queue_payload(payload)


def _collect_queue_fields_raw(
    occurrences: Sequence[Mapping[str, Any]],
    enabled_feature_flags: Sequence[str],
) -> dict[str, Any]:
    binding = require_rust_binding("collect_queue_fields")
    try:
        payload = binding(list(occurrences), list(enabled_feature_flags))
    except TypeError:
        payload = binding(list(occurrences))
    if not isinstance(payload, dict):
        return {"fields": None, "errors": []}
    return dict(payload)


def _has_legacy_capacity_keyword_error(payload: Mapping[str, Any]) -> bool:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(error, Mapping)
        and error.get("code") == "unknown-queue-keyword"
        and "capacity" in str(error.get("message") or "")
        for error in errors
    )


def _legacy_capacity_occurrences(
    occurrences: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Translate public capacity args for older Rust wheels that named runners."""
    translated: list[dict[str, Any]] = []
    for occurrence in occurrences:
        item = dict(occurrence)
        args: list[Any] = []
        for arg in item.get("args") or []:
            if isinstance(arg, Mapping):
                arg_item = dict(arg)
                if arg_item.get("name") == "capacity":
                    arg_item["name"] = "runners"
                args.append(arg_item)
            else:
                args.append(arg)
        item["args"] = args
        translated.append(item)
    return translated


def _normalize_queue_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    fields = normalized.get("fields")
    if isinstance(fields, Mapping):
        field_items = dict(fields)
        if "capacity" not in field_items and "queue_capacity" in field_items:
            field_items["capacity"] = field_items.pop("queue_capacity")
        if "capacity" not in field_items and "runners" in field_items:
            field_items["capacity"] = field_items.pop("runners")
        normalized["fields"] = field_items
    errors = normalized.get("errors")
    if isinstance(errors, list):
        normalized["errors"] = [_normalize_queue_error(error) for error in errors]
    return normalized


def _normalize_queue_error(error: Any) -> Any:
    if not isinstance(error, Mapping):
        return error
    item = dict(error)
    message = item.get("message")
    if isinstance(message, str):
        item["message"] = (
            message.replace("%queue runners", "%queue capacity")
            .replace("%queue queue_capacity", "%queue capacity")
            .replace("runners=", "capacity=")
            .replace("queue_capacity=", "capacity=")
        )
    return item


def format_queue_directive(
    *,
    capacity: int | None = None,
    priority: int | None = None,
    weight: float | None = None,
) -> str | None:
    """Return canonical `%queue(...)`, omitting absent fields."""
    payload: dict[str, int | float] = {}
    if capacity is not None:
        payload["capacity"] = capacity
    if priority is not None:
        payload["priority"] = priority
    if weight is not None:
        payload["weight"] = weight
    format_binding = require_rust_binding("format_queue_directive")
    try:
        formatted = format_binding(payload)
    except ValueError as exc:
        if "unknown field `capacity`" not in str(exc):
            raise
        legacy_payload = dict(payload)
        if "capacity" in legacy_payload:
            legacy_payload["queue_capacity"] = legacy_payload.pop("capacity")
        try:
            formatted = format_binding(legacy_payload)
        except ValueError as legacy_exc:
            if "unknown field `queue_capacity`" not in str(legacy_exc):
                raise
            if "queue_capacity" in legacy_payload:
                legacy_payload["runners"] = legacy_payload.pop("queue_capacity")
            formatted = format_binding(legacy_payload)
        if not formatted:
            return None
        return (
            str(formatted)
            .replace("queue_capacity=", "capacity=")
            .replace("runners=", "capacity=")
        )
    return str(formatted) if formatted else None


def validate_queue_capacity(value: object) -> int:
    """Validate a capacity budget through the Rust queue contract.

    Rejects booleans and invalid numeric input without coercing them to a
    valid budget. Callers treat omission separately; ``None`` is not a
    capacity value.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(
            "%queue(capacity=...) requires a positive integer; "
            "boolean values are rejected."
        )
    if isinstance(value, int):
        if value < 0:
            raise ValueError("%queue(capacity=...) requires a positive integer.")
        raw = str(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("%queue(capacity=...) requires a positive integer.")
    else:
        raise ValueError(
            "%queue(capacity=...) requires a positive integer; "
            "fractional, boolean, and nonnumeric values are rejected."
        )
    source = f"%q:{raw}"
    payload = collect_queue_fields(
        [
            {
                "source": source,
                "source_span": [0, len(source)],
                "args": [{"value": raw}],
                "has_plus_suffix": False,
            }
        ]
    )
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, Mapping):
            message = str(first.get("message") or "Invalid %queue directive.")
        else:
            message = "Invalid %queue directive."
        raise ValueError(message)
    fields = payload.get("fields")
    if not isinstance(fields, Mapping):
        raise ValueError("Invalid %queue directive.")
    capacity = fields.get(
        "capacity",
        fields.get("queue_capacity", fields.get("runners")),
    )
    if capacity is None:
        raise ValueError("%queue(capacity=...) requires a positive integer.")
    return int(capacity)


def resolve_authored_queue_capacity(
    data: Mapping[str, Any],
) -> tuple[int | None, bool]:
    """Return canonical capacity and explicitness from mixed spellings.

    Canonical ``queue_capacity`` wins when both spellings are present.
    Omission, explicit false, and explicit zero stay distinguishable.
    """
    if "queue_capacity" in data:
        raw = data.get("queue_capacity")
        explicit = bool(data.get("queue_capacity_explicit"))
    elif "wait_runners" in data:
        raw = data.get("wait_runners")
        explicit = bool(data.get("wait_runners_explicit"))
    else:
        return None, bool(
            data.get("queue_capacity_explicit") or data.get("wait_runners_explicit")
        )
    if type(raw) is int and raw >= 0:
        return raw, explicit
    return None, explicit


def reauthor_capacity_for_prefix(
    capacity: int | None,
    *,
    explicit: bool,
    weight: float | None = None,
    budget_enabled: bool | None = None,
) -> int | None:
    """Return a capacity safe to put through the new-authored parser.

    Persisted explicit zero with the budget flag on is an exact effective-weight
    drain, not a value the On parser accepts. Implicit zero is "no authored
    budget" and is omitted rather than reauthored as ``capacity=0``.
    """
    if capacity is None or not explicit:
        return None
    if budget_enabled is None:
        budget_enabled = "queue_capacity_budget" in launch_feature_flag_keys()
    effective_weight = 1.0 if weight is None else float(weight)
    try:
        binding = getattr(
            import_module("sase_core_rs"),
            "normalize_persisted_queue_capacity",
            None,
        )
    except ImportError:
        binding = None
    if callable(binding):
        payload = binding(capacity, explicit, effective_weight, 1.0, budget_enabled)
        if isinstance(payload, dict) and "reauthor_capacity" in payload:
            value = payload.get("reauthor_capacity")
            return int(value) if type(value) is int else None
    if budget_enabled and capacity == 0:
        return None
    return capacity


def launch_feature_flag_keys() -> list[str]:
    """Return currently enabled launch/editor flags for Rust entry points."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags
    from sase.xprompt.code_value import typed_launch_units_enabled

    flags: list[str] = []
    snapshot = current_flags()
    if snapshot.enabled(FeatureFlag.agent_holds):
        flags.append(str(FeatureFlag.agent_holds))
    if snapshot.enabled(FeatureFlag.queue_capacity_budget):
        flags.append(str(FeatureFlag.queue_capacity_budget))
    if typed_launch_units_enabled():
        flags.append(str(FeatureFlag.typed_launch_units))
    return flags
