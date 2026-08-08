"""Per-option input resolution and secret redaction for gate execution.

Kept out of :mod:`sase.notification_gates.model_inputs` because it needs
:class:`~sase.notification_gates.model_options.GateOption`, which would
otherwise create an import cycle (``model_options`` imports ``model_inputs``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.notification_gates.model_options import GateOption
from sase.notification_gates.model_validation import GateError, json_object


def resolve_option_inputs(
    selected: tuple[GateOption, ...],
    input_data: object | None,
    option_inputs: object | None,
) -> dict[str, Any]:
    """Resolve exactly one submitted JSON value per selected option.

    ``input_data`` (the legacy shared-value contract) and ``option_inputs``
    (the per-option contract) are mutually exclusive; supplying both would
    recreate exactly the submission ambiguity this contract removes.

    Args:
        selected: The options selected for this execution, in branch order.
        input_data: A single JSON value submitted for every selected option.
        option_inputs: A mapping of selected option id to that option's own
            submitted JSON value. A selected option with no entry resolves to
            ``{}`` and is then judged by its own schema.

    Returns:
        Mapping of option id to its resolved input value.

    Raises:
        GateError: ``conflicting_input`` when both are given;
            ``unknown_option`` when ``option_inputs`` references an id outside
            the selection.
    """
    if input_data is not None and option_inputs is not None:
        raise GateError(
            "conflicting_input",
            "option_inputs",
            "input_data and option_inputs are mutually exclusive",
        )
    if option_inputs is not None:
        submitted = json_object(option_inputs, "option_inputs")
        selected_ids = {option.id for option in selected}
        unknown = sorted(set(submitted) - selected_ids)
        if unknown:
            raise GateError(
                "unknown_option",
                "option_inputs",
                f"option is not selected: {', '.join(unknown)}",
            )
        return {option.id: submitted.get(option.id, {}) for option in selected}
    normalized_input = {} if input_data is None else input_data
    return {option.id: normalized_input for option in selected}


def redact_option_inputs(
    selected: tuple[GateOption, ...], resolved: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a response-safe copy of ``resolved`` for ``response.json``.

    Every value of a declared ``secret: true`` field is replaced by
    ``{"$redacted": true}`` (the whole array for a repeatable secret field).
    Options with a raw ``input_schema`` cannot declare secrets and pass
    through unchanged.

    Secrets reach the command's stdin unredacted; this redaction applies only
    on the way to durable audit data. The journal's stored command result is
    covered separately by :func:`redact_secrets_in_result`, which scrubs the
    same values back out of whatever the command echoed.
    """
    return {
        option.id: _redact_value(option, resolved.get(option.id, {}))
        for option in selected
    }


def _redact_value(option: GateOption, value: Any) -> Any:
    if not option.inputs or not isinstance(value, Mapping):
        return value
    secret_ids = {field.id for field in option.inputs if field.secret}
    if not secret_ids:
        return value
    redacted = dict(value)
    for field_id in secret_ids:
        if field_id in redacted:
            redacted[field_id] = {"$redacted": True}
    return redacted


def redact_secrets_in_result(option: GateOption, resolved: Any, result: Any) -> Any:
    """Return ``result`` with every submitted secret value scrubbed out.

    The journal stores a completed option's command result verbatim, and a
    command is free to echo its stdin back into its stdout -- the conformance
    matrix's own echo command does exactly that. Without this, a
    ``secret: true`` value redacted out of ``response.json`` still lands in
    ``journal.jsonl``, which is the same durable audit data.

    Only non-empty *string* secrets are scrubbed. A secret boolean or small
    integer carries no entropy but does collide with ordinary result values,
    so matching on it would redact unrelated output rather than a secret.

    Any string that *contains* a secret is replaced whole rather than spliced:
    a result field built out of the secret is contaminated in full, and
    partial scrubbing would leave its length and surroundings behind.
    """
    secrets = _submitted_secret_strings(option, resolved)
    if not secrets:
        return result
    return _scrub(result, secrets)


def _submitted_secret_strings(option: GateOption, resolved: Any) -> tuple[str, ...]:
    if not option.inputs or not isinstance(resolved, Mapping):
        return ()
    found: list[str] = []
    for gate_input_field in option.inputs:
        if not gate_input_field.secret:
            continue
        submitted = resolved.get(gate_input_field.id)
        candidates = submitted if isinstance(submitted, list) else [submitted]
        found.extend(value for value in candidates if isinstance(value, str) and value)
    return tuple(found)


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, str) and any(secret in value for secret in secrets):
        return {"$redacted": True}
    return value


__all__ = [
    "redact_option_inputs",
    "redact_secrets_in_result",
    "resolve_option_inputs",
]
