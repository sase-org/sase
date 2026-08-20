"""Validated Python facade for the Rust snippet catalog composer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.core.rust import require_rust_binding

_CALL_STATUSES = frozenset({"resolved", "missing", "cycle"})
SnippetCallStatus = Literal["resolved", "missing", "cycle"]


@dataclass(frozen=True, slots=True)
class SnippetSourceSpan:
    """Byte span of one authored ``#[...]`` call in a raw template."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SnippetTriggerValidation:
    """Rust trigger-shape check for one explicit catalog key."""

    trigger: str
    valid: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SnippetCall:
    """One syntactically valid snippet call scanned from a raw template."""

    authored_target: str
    canonical_target: str | None
    positional_args: tuple[str, ...]
    span: SnippetSourceSpan
    status: SnippetCallStatus


@dataclass(frozen=True, slots=True)
class SnippetDiagnostic:
    """Missing-target, cycle, or invalid-trigger diagnostic from Rust."""

    code: str
    message: str
    trigger: str
    target: str | None = None
    span: SnippetSourceSpan | None = None
    cycle: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class ComposedSnippetCatalog:
    """Normalized result from the shared Rust snippet catalog composer."""

    templates: dict[str, str]
    alias_provenance: dict[str, str]
    triggers: dict[str, SnippetTriggerValidation]
    calls: dict[str, tuple[SnippetCall, ...]]
    outbound: dict[str, tuple[str, ...]]
    inbound: dict[str, tuple[str, ...]]
    diagnostics: tuple[SnippetDiagnostic, ...]


_ComposedSnippetCatalog = ComposedSnippetCatalog


def compose_snippet_catalog(
    explicit_templates: Mapping[str, str],
) -> ComposedSnippetCatalog:
    """Compose explicit snippet templates through the shared Rust contract."""
    explicit = dict(explicit_templates)
    binding = require_rust_binding("compose_snippet_catalog")
    payload: Any = binding(explicit)
    if not isinstance(payload, Mapping):
        raise TypeError(
            "compose_snippet_catalog returned a non-mapping top-level payload"
        )

    templates = _require_string_mapping(payload.get("templates"), "templates")
    alias_provenance = _require_string_mapping(
        payload.get("alias_provenance"),
        "alias_provenance",
    )
    triggers = _require_trigger_map(payload.get("triggers"))
    calls = _require_calls_map(payload.get("calls"))
    outbound = _require_string_list_mapping(payload.get("outbound"), "outbound")
    inbound = _require_string_list_mapping(payload.get("inbound"), "inbound")
    diagnostics = _require_diagnostics(payload.get("diagnostics"))

    for alias, source in alias_provenance.items():
        if alias not in templates:
            raise ValueError(
                "compose_snippet_catalog alias provenance references missing "
                f"final template {alias!r}"
            )
        if source not in explicit:
            raise ValueError(
                "compose_snippet_catalog alias provenance references missing "
                f"explicit source {source!r}"
            )

    _require_explicit_keys(triggers, explicit, "triggers")
    _require_explicit_keys(calls, explicit, "calls")
    _require_explicit_keys(outbound, explicit, "outbound")
    _require_explicit_keys(inbound, explicit, "inbound")
    for trigger, trigger_calls in calls.items():
        for call in trigger_calls:
            if (
                call.canonical_target is not None
                and call.canonical_target not in explicit
            ):
                raise ValueError(
                    "compose_snippet_catalog call canonical target "
                    f"{call.canonical_target!r} on {trigger!r} is not explicit"
                )

    return ComposedSnippetCatalog(
        templates=templates,
        alias_provenance=alias_provenance,
        triggers=triggers,
        calls=calls,
        outbound=outbound,
        inbound=inbound,
        diagnostics=diagnostics,
    )


def validate_snippet_trigger(trigger: str) -> SnippetTriggerValidation:
    """Return the Rust trigger-shape check for a single trigger string."""
    binding = require_rust_binding("validate_snippet_trigger")
    payload: Any = binding(trigger)
    return _require_trigger_validation(payload, "validate_snippet_trigger")


def _require_string_mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")

    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-string key {key!r}"
            )
        if not isinstance(item, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-string value for key {key!r}"
            )
        normalized[key] = item
    return normalized


def _require_string_list_mapping(value: Any, field: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")

    normalized: dict[str, tuple[str, ...]] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-string key {key!r}"
            )
        if not isinstance(item, Sequence) or isinstance(item, str | bytes):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-list value for key {key!r}"
            )
        names: list[str] = []
        for entry in item:
            if not isinstance(entry, str):
                raise TypeError(
                    f"compose_snippet_catalog field {field!r} contains "
                    f"non-string entry for key {key!r}"
                )
            names.append(entry)
        normalized[key] = tuple(names)
    return normalized


def _require_explicit_keys(
    value: Mapping[str, object], explicit: Mapping[str, str], field: str
) -> None:
    extra = sorted(key for key in value if key not in explicit)
    missing = sorted(key for key in explicit if key not in value)
    if extra:
        raise ValueError(
            f"compose_snippet_catalog field {field!r} contains unexpected "
            f"explicit key {extra[0]!r}"
        )
    if missing:
        raise ValueError(
            f"compose_snippet_catalog field {field!r} is missing explicit "
            f"key {missing[0]!r}"
        )


def _require_trigger_map(value: Any) -> dict[str, SnippetTriggerValidation]:
    if not isinstance(value, Mapping):
        raise TypeError("compose_snippet_catalog field 'triggers' must be a mapping")
    normalized: dict[str, SnippetTriggerValidation] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                "compose_snippet_catalog field 'triggers' contains "
                f"non-string key {key!r}"
            )
        validation = _require_trigger_validation(
            item, f"triggers[{key}]", expected_trigger=key
        )
        normalized[key] = validation
    return normalized


def _require_trigger_validation(
    value: Any,
    field: str,
    *,
    expected_trigger: str | None = None,
) -> SnippetTriggerValidation:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")
    trigger = value.get("trigger")
    if not isinstance(trigger, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} trigger must be a string"
        )
    if expected_trigger is not None and trigger != expected_trigger:
        raise ValueError(
            f"compose_snippet_catalog field {field!r} trigger {trigger!r} "
            f"does not match key {expected_trigger!r}"
        )
    valid = value.get("valid")
    if not isinstance(valid, bool):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} valid must be a boolean"
        )
    reason = value.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} reason must be a string or null"
        )
    return SnippetTriggerValidation(trigger=trigger, valid=valid, reason=reason)


def _require_calls_map(value: Any) -> dict[str, tuple[SnippetCall, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("compose_snippet_catalog field 'calls' must be a mapping")
    normalized: dict[str, tuple[SnippetCall, ...]] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                f"compose_snippet_catalog field 'calls' contains non-string key {key!r}"
            )
        if not isinstance(item, Sequence) or isinstance(item, str | bytes):
            raise TypeError(
                f"compose_snippet_catalog field 'calls[{key}]' must be a list"
            )
        normalized[key] = tuple(
            _require_call(entry, f"calls[{key}][{index}]")
            for index, entry in enumerate(item)
        )
    return normalized


def _require_call(value: Any, field: str) -> SnippetCall:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")
    authored = value.get("authored_target")
    if not isinstance(authored, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} authored_target must be a string"
        )
    canonical = value.get("canonical_target")
    if canonical is not None and not isinstance(canonical, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} canonical_target must be "
            "a string or null"
        )
    positional = value.get("positional_args")
    if not isinstance(positional, Sequence) or isinstance(positional, str | bytes):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} positional_args must be a list"
        )
    args: list[str] = []
    for entry in positional:
        if not isinstance(entry, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} positional_args "
                "contains a non-string entry"
            )
        args.append(entry)
    status = value.get("status")
    if status not in _CALL_STATUSES:
        raise ValueError(
            f"compose_snippet_catalog field {field!r} status must be one of "
            "resolved, missing, cycle"
        )
    return SnippetCall(
        authored_target=authored,
        canonical_target=canonical,
        positional_args=tuple(args),
        span=_require_span(value.get("span"), f"{field}.span"),
        status=status,
    )


def _require_span(value: Any, field: str) -> SnippetSourceSpan:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")
    start = _require_byte_offset(value.get("start"), f"{field}.start")
    end = _require_byte_offset(value.get("end"), f"{field}.end")
    if start > end:
        raise ValueError(
            f"compose_snippet_catalog field {field!r} start must be <= end"
        )
    return SnippetSourceSpan(start=start, end=end)


def _require_byte_offset(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(
            f"compose_snippet_catalog field {field!r} must be a non-negative integer"
        )
    return value


def _require_diagnostics(value: Any) -> tuple[SnippetDiagnostic, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TypeError("compose_snippet_catalog field 'diagnostics' must be a list")
    return tuple(
        _require_diagnostic(item, f"diagnostics[{index}]")
        for index, item in enumerate(value)
    )


def _require_diagnostic(value: Any, field: str) -> SnippetDiagnostic:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")
    code = value.get("code")
    message = value.get("message")
    trigger = value.get("trigger")
    if not isinstance(code, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} code must be a string"
        )
    if not isinstance(message, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} message must be a string"
        )
    if not isinstance(trigger, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} trigger must be a string"
        )
    target = value.get("target")
    if target is not None and not isinstance(target, str):
        raise TypeError(
            f"compose_snippet_catalog field {field!r} target must be a string or null"
        )
    raw_span = value.get("span")
    span = None if raw_span is None else _require_span(raw_span, f"{field}.span")
    raw_cycle = value.get("cycle")
    if raw_cycle is None:
        cycle = None
    else:
        if not isinstance(raw_cycle, Sequence) or isinstance(raw_cycle, str | bytes):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} cycle must be a list or null"
            )
        names: list[str] = []
        for entry in raw_cycle:
            if not isinstance(entry, str):
                raise TypeError(
                    f"compose_snippet_catalog field {field!r} cycle contains "
                    "a non-string entry"
                )
            names.append(entry)
        cycle = tuple(names)
    return SnippetDiagnostic(
        code=code,
        message=message,
        trigger=trigger,
        target=target,
        span=span,
        cycle=cycle,
    )


__all__ = [
    "ComposedSnippetCatalog",
    "SnippetCall",
    "SnippetDiagnostic",
    "SnippetSourceSpan",
    "SnippetTriggerValidation",
    "compose_snippet_catalog",
    "validate_snippet_trigger",
]
