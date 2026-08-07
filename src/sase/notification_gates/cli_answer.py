"""``sase gate answer`` -- answer a durable gate headlessly.

This is the headless peer of the ACE gate modals: it collects a selection, the
reviewer's note, and one typed input value per selected option, then calls the
same :func:`~sase.notification_gates.executor.execute_gate_selection` every
other surface calls. The feedback-to-input rule, schema enforcement, retry
resolution, and secret redaction all live there, so answering from a script and
answering from the TUI cannot drift.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal, NoReturn

from rich.console import Console
from rich.text import Text

from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.cli_support import (
    EXIT_ERROR,
    EXIT_OK,
    GateCliError,
    JsonArgumentReader,
    ResolvedGateCliBundle,
    emit_json,
    report_gate_error,
    resolve_gate_cli_bundle,
    split_assignment,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.models import GateError
from sase.xprompt.models import InputType

_TRUE_WORDS = frozenset({"1", "on", "true", "yes", "y"})
_FALSE_WORDS = frozenset({"0", "off", "false", "no", "n"})


def handle_gate_answer(args: argparse.Namespace) -> NoReturn:
    """Answer one gate and emit its stable terminal projection."""
    try:
        payload = _answer(args)
    except GateCliError as exc:
        print(f"sase gate answer: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
    except GateError as exc:
        sys.exit(report_gate_error("answer", exc))
    except OSError as exc:
        print(f"sase gate answer: cannot answer gate: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_human_summary(payload)
    sys.exit(EXIT_OK)


def _answer(args: argparse.Namespace) -> dict[str, Any]:
    """Resolve every argument against the bundle and run the executor."""
    bundle = resolve_gate_cli_bundle(str(args.kind), str(args.id))
    gate = GateBranchData.from_envelope(
        bundle.envelope, default_feedback=bundle.adapter.default_feedback
    )
    selected = _resolve_selection(gate.options, getattr(args, "option", None) or [])
    reader = JsonArgumentReader()
    input_data = _shared_input(args, reader)
    option_inputs = _per_option_inputs(args, selected, reader)
    if input_data is not None and option_inputs is not None:
        raise GateCliError(
            "--input submits one shared value and --set/--option-input submit "
            "per-option values; use one or the other"
        )

    execution = execute_gate_selection(
        bundle.root,
        [option.id for option in selected],
        input_data,
        feedback=getattr(args, "feedback", None),
        source="cli",
        retry=_retry_choice(args),
        option_inputs=option_inputs,
    )
    return _answered_payload(bundle, execution.response, execution.already_completed)


def _resolve_selection(
    options: Sequence[GateOption], requested: Sequence[str]
) -> tuple[GateOption, ...]:
    """Map requested option ids onto declared options, in requested order."""
    if not requested:
        raise GateCliError("--option is required at least once")
    by_id = {option.id: option for option in options}
    unknown = [option_id for option_id in requested if option_id not in by_id]
    if unknown:
        known = ", ".join(sorted(by_id))
        raise GateCliError(
            f"gate declares no option(s): {', '.join(unknown)}; declared: {known}"
        )
    duplicates = sorted({value for value in requested if requested.count(value) > 1})
    if duplicates:
        raise GateCliError(f"--option repeated: {', '.join(duplicates)}")
    return tuple(by_id[option_id] for option_id in requested)


def _shared_input(
    args: argparse.Namespace, reader: JsonArgumentReader
) -> object | None:
    raw = getattr(args, "input", None)
    if raw is None:
        return None
    return reader.read(str(raw), target="--input")


def _retry_choice(args: argparse.Namespace) -> Literal["resume", "restart"] | None:
    if bool(getattr(args, "resume", False)):
        return "resume"
    if bool(getattr(args, "restart", False)):
        return "restart"
    return None


def _per_option_inputs(
    args: argparse.Namespace,
    selected: tuple[GateOption, ...],
    reader: JsonArgumentReader,
) -> dict[str, Any] | None:
    """Build the per-option submission from ``--option-input`` and ``--set``."""
    whole_values = _whole_option_values(args, selected, reader)
    field_values = _field_option_values(args, selected)
    overlap = sorted(set(whole_values) & set(field_values))
    if overlap:
        raise GateCliError(
            "--option-input already submits the whole value for option(s) "
            f"{', '.join(overlap)}; --set cannot also target them"
        )
    if not whole_values and not field_values:
        return None
    return {**whole_values, **field_values}


def _whole_option_values(
    args: argparse.Namespace,
    selected: tuple[GateOption, ...],
    reader: JsonArgumentReader,
) -> dict[str, Any]:
    selected_ids = {option.id for option in selected}
    values: dict[str, Any] = {}
    for raw in getattr(args, "option_input", None) or []:
        option_id, source = split_assignment(str(raw), target="--option-input")
        if option_id not in selected_ids:
            raise GateCliError(
                f"--option-input targets an unselected option: {option_id}"
            )
        if option_id in values:
            raise GateCliError(f"--option-input repeated for option: {option_id}")
        values[option_id] = reader.read(source, target=f"--option-input {option_id}")
    return values


def _field_option_values(
    args: argparse.Namespace, selected: tuple[GateOption, ...]
) -> dict[str, dict[str, Any]]:
    """Broadcast every ``--set`` key to each selected option that accepts it.

    A key no selected option accepts is a usage error rather than a schema
    failure at submission time: the reviewer learns which keys exist while
    they can still fix the command line.
    """
    raw_values: dict[str, dict[str, list[str]]] = {}
    for raw in getattr(args, "set", None) or []:
        key, value = split_assignment(str(raw), target="--set")
        accepting = [option for option in selected if _option_accepts_key(option, key)]
        if not accepting:
            raise GateCliError(
                f"--set {key}: no selected option accepts that input; "
                f"accepted: {_accepted_keys(selected)}"
            )
        for option in accepting:
            raw_values.setdefault(option.id, {}).setdefault(key, []).append(value)

    values: dict[str, dict[str, Any]] = {}
    for option in selected:
        for key, entries in raw_values.get(option.id, {}).items():
            values.setdefault(option.id, {})[key] = _coerce_field_value(
                _declared_field(option, key), entries, key=key, option_id=option.id
            )
    return values


def _option_accepts_key(option: GateOption, key: str) -> bool:
    """Whether ``key`` can appear in this option's submitted input value."""
    properties = option.input_schema.get("properties")
    if isinstance(properties, Mapping) and key in properties:
        return True
    return option.input_schema.get("additionalProperties") is not False


def _accepted_keys(selected: Sequence[GateOption]) -> str:
    keys: set[str] = set()
    open_options: list[str] = []
    for option in selected:
        properties = option.input_schema.get("properties")
        if isinstance(properties, Mapping):
            keys.update(str(key) for key in properties)
        if option.input_schema.get("additionalProperties") is not False:
            open_options.append(option.id)
    rendered = ", ".join(sorted(keys)) if keys else "(none declared)"
    if open_options:
        rendered += f"; any key for option(s) {', '.join(sorted(open_options))}"
    return rendered


def _declared_field(option: GateOption, key: str) -> GateInputField | None:
    for field in option.inputs:
        if field.id == key:
            return field
    return None


def _coerce_field_value(
    field: GateInputField | None,
    entries: list[str],
    *,
    key: str,
    option_id: str,
) -> Any:
    """Type one ``--set`` value by its declared field, or keep it a string."""
    target = f"--set {key} (option {option_id})"
    if field is not None and field.repeatable:
        return [_coerce_scalar(field, entry, target=target) for entry in entries]
    if len(entries) > 1:
        raise GateCliError(f"{target}: repeated, but the field is not repeatable")
    return _coerce_scalar(field, entries[0], target=target)


def _coerce_scalar(field: GateInputField | None, raw: str, *, target: str) -> Any:
    if field is None:
        return raw
    if field.type is InputType.BOOL:
        lowered = raw.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise GateCliError(f"{target}: expected a boolean, got {raw!r}")
    if field.type is InputType.INT:
        try:
            return int(raw.strip())
        except ValueError as exc:
            raise GateCliError(f"{target}: expected an integer, got {raw!r}") from exc
    if field.type is InputType.FLOAT:
        try:
            return float(raw.strip())
        except ValueError as exc:
            raise GateCliError(f"{target}: expected a number, got {raw!r}") from exc
    if field.type is InputType.ENUM:
        allowed = [choice.value for choice in field.choices]
        if raw not in allowed:
            raise GateCliError(
                f"{target}: expected one of {', '.join(allowed)}, got {raw!r}"
            )
    return raw


def _answered_payload(
    bundle: ResolvedGateCliBundle,
    response: Mapping[str, Any],
    already_completed: bool,
) -> dict[str, Any]:
    return {
        "already_answered": already_completed,
        "feedback": response.get("feedback"),
        "kind": bundle.kind,
        "option_inputs": response.get("option_inputs", {}),
        "option_results": response.get("option_results", []),
        "request_id": bundle.request_id,
        "response_path": str(bundle.response_path),
        "selected_option_ids": list(response.get("selected_option_ids", [])),
        "status": "answered",
    }


def _print_human_summary(payload: Mapping[str, Any]) -> None:
    summary = Text()
    summary.append("✓", style="bold green")
    summary.append(f" Gate {payload['kind']}/{payload['request_id']} ")
    summary.append(
        "was already answered" if payload["already_answered"] else "answered",
        style="bold green",
    )
    selected = payload["selected_option_ids"]
    if isinstance(selected, list) and selected:
        summary.append(" · options ", style="dim")
        summary.append(", ".join(str(value) for value in selected), style="bold")
    console = Console()
    console.print(summary, soft_wrap=True)

    option_inputs = payload["option_inputs"]
    if isinstance(option_inputs, Mapping):
        for option_id, value in sorted(option_inputs.items()):
            if not value:
                continue
            line = Text("  input ", style="dim")
            line.append(str(option_id), style="bold")
            line.append(": ", style="dim")
            line.append(_render_input(value))
            console.print(line, soft_wrap=True)

    feedback = payload["feedback"]
    if feedback is not None:
        line = Text("  feedback: ", style="dim")
        line.append(str(feedback))
        console.print(line, soft_wrap=True)
    response = Text("Response path: ", style="dim")
    response.append(str(payload["response_path"]))
    console.print(response, soft_wrap=True)


def _render_input(value: object) -> str:
    if not isinstance(value, Mapping):
        return repr(value)
    parts = []
    for key, entry in sorted(value.items()):
        if isinstance(entry, Mapping) and entry.get("$redacted") is True:
            parts.append(f"{key}=••• (redacted)")
        else:
            parts.append(f"{key}={entry!r}")
    return ", ".join(parts)


__all__ = ["handle_gate_answer"]
