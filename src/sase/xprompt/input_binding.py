"""Shared positional, named, and default binding for xprompt inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import UNSET, InputArg, XPromptValidationError


class InputBindingError(ValueError):
    """Raised when invocation arguments do not satisfy an input contract."""


@dataclass(frozen=True)
class _BoundInputs:
    """Converted positional values and their bound template context."""

    positional: list[Any]
    values: dict[str, Any]
    explicit_values: dict[str, Any]


def validate_repeatable_input_order(inputs: list[InputArg]) -> None:
    """Require a repeatable user-facing input to be the final positional input."""
    visible = [input_arg for input_arg in inputs if not input_arg.is_step_input]
    repeatable = [input_arg for input_arg in visible if input_arg.repeatable]
    if not repeatable:
        return
    if len(repeatable) > 1 or repeatable[0] is not visible[-1]:
        raise XPromptValidationError(
            "A repeatable input must be the final user-facing positional input"
        )


def input_for_position(inputs: list[InputArg], position: int) -> InputArg | None:
    """Return the input that owns *position*, honoring a repeatable tail."""
    for index, input_arg in enumerate(inputs):
        if input_arg.repeatable and position >= index:
            return input_arg
        if position == index:
            return input_arg
    return None


def bind_input_args(
    inputs: list[InputArg],
    positional_args: list[Any],
    named_args: dict[str, Any],
) -> _BoundInputs:
    """Bind one invocation using the shared scalar/repeatable contract.

    Explicit named values retain the historical precedence over positional
    values. Unknown named values are preserved for runtime-injected context.
    A repeatable input always receives a list when explicitly supplied.
    """
    if not inputs:
        return _BoundInputs(
            positional=list(positional_args),
            values=dict(named_args),
            explicit_values=dict(named_args),
        )

    validate_repeatable_input_order(inputs)
    converted_positional: list[Any] = []
    explicit: dict[str, Any] = {}
    repeated_values: dict[str, list[Any]] = {}

    for position, raw_value in enumerate(positional_args):
        input_arg = input_for_position(inputs, position)
        if input_arg is None:
            raise InputBindingError(
                _surplus_positional_message(
                    inputs,
                    positional_args,
                    position,
                    landed_on=None,
                )
            )
        if raw_value == "null":
            if input_arg.repeatable and len(positional_args) > position + 1:
                raise InputBindingError(
                    f"Argument '{input_arg.name}' cannot combine null with other values"
                )
            converted_positional.append(raw_value)
            continue
        try:
            converted = _convert_value(input_arg, raw_value)
        except InputBindingError as exc:
            surplus = _surplus_positional_prefix(
                inputs,
                positional_args,
                position,
                landed_on=input_arg.name,
            )
            if surplus is not None:
                raise InputBindingError(f"{surplus}: {exc}") from exc
            raise
        converted_positional.append(converted)
        if input_arg.repeatable:
            repeated_values.setdefault(input_arg.name, []).append(converted)
            explicit[input_arg.name] = repeated_values[input_arg.name]
        else:
            explicit[input_arg.name] = converted

    by_name = {input_arg.name: input_arg for input_arg in inputs}
    for name, raw_value in named_args.items():
        input_arg = by_name.get(name)
        if input_arg is None:
            explicit[name] = raw_value
            continue
        if raw_value == "null":
            explicit.pop(name, None)
            continue
        if input_arg.repeatable:
            raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
            explicit[name] = [
                _convert_value(input_arg, element) for element in raw_values
            ]
        else:
            explicit[name] = _convert_value(input_arg, raw_value)

    values = dict(explicit)
    for input_arg in inputs:
        if input_arg.name not in values and input_arg.default is not UNSET:
            values[input_arg.name] = input_arg.default

    return _BoundInputs(
        positional=converted_positional,
        values=values,
        explicit_values=explicit,
    )


def _counted(n: int, singular: str) -> str:
    if n == 1:
        return f"1 {singular}"
    return f"{n} {singular}s"


def _surplus_positional_prefix(
    inputs: list[InputArg],
    positional_args: list[Any],
    position: int,
    *,
    landed_on: str | None,
) -> str | None:
    """Describe an overflowing positional, or None when the failure is not surplus."""
    if any(input_arg.repeatable for input_arg in inputs):
        return None
    declared = len(inputs)
    received = len(positional_args)
    if landed_on is not None and (received <= declared or position == 0):
        return None
    prefix = (
        f"received {_counted(received, 'positional argument')} but declares "
        f"{_counted(declared, 'input')}; surplus positional {position + 1}"
    )
    if landed_on is None:
        return f"{prefix} has no declaration"
    return f"{prefix} bound to '{landed_on}'"


def _surplus_positional_message(
    inputs: list[InputArg],
    positional_args: list[Any],
    position: int,
    *,
    landed_on: str | None,
) -> str:
    surplus = _surplus_positional_prefix(
        inputs,
        positional_args,
        position,
        landed_on=landed_on,
    )
    if surplus is not None:
        return surplus
    return f"Too many positional arguments: input {position + 1} has no declaration"


def _convert_value(input_arg: InputArg, raw_value: Any) -> Any:
    try:
        return input_arg.validate_and_convert(str(raw_value))
    except XPromptValidationError as exc:
        raise InputBindingError(str(exc)) from exc


__all__ = [
    "InputBindingError",
    "bind_input_args",
    "input_for_position",
    "validate_repeatable_input_order",
]
