"""Option, group, and query structure models for notification gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.notification_gates.model_inputs import (
    GateInputField,
    compile_gate_input_schema,
    parse_gate_input_fields,
)
from sase.notification_gates.model_validation import (
    GateError,
    GateFeedbackMode,
    check_json_schema,
    json_object,
    reject_unknown_fields,
    string_list,
    validate_icon,
    validate_label,
    validate_option_identifier,
    validate_relative_path,
)
from sase.notification_gates.query import GateQueryError, parse_gate_query


@dataclass(frozen=True)
class GateCommand:
    """A shell-free command descriptor."""

    argv: tuple[str, ...]

    @classmethod
    def from_value(cls, value: object, target: str) -> GateCommand:
        if isinstance(value, list):
            argv = string_list(value, target)
        else:
            data = json_object(value, target)
            unknown = set(data) - {"argv"}
            if unknown:
                raise GateError(
                    "invalid_request",
                    target,
                    f"unsupported command field(s): {', '.join(sorted(unknown))}",
                )
            argv = string_list(data.get("argv"), f"{target}.argv")
        if not argv or not argv[0]:
            raise GateError("invalid_command", target, "command argv must not be empty")
        validate_relative_path(argv[0], f"{target}.argv[0]")
        if any("\x00" in argument for argument in argv):
            raise GateError(
                "invalid_command", target, "command arguments cannot contain NUL"
            )
        return cls(argv=argv)

    def to_dict(self) -> dict[str, Any]:
        return {"argv": list(self.argv)}


@dataclass(frozen=True)
class GateOption:
    """One command-bearing control referenced exactly once by a gate query.

    ``input_schema`` is the single enforcement layer: the executor validates
    the submitted value against it and it is what a reader that knows nothing
    about ``inputs`` sees. ``inputs`` is the authoring layer — a closed,
    declarative vocabulary that compiles into ``input_schema`` at creation.
    The two are mutually exclusive; declaring both requires the raw
    ``input_schema`` to exactly equal the schema compiled from ``inputs``, so
    an envelope produced by this class re-parses through the same code path
    without tripping the conflict check.
    """

    id: str
    label: str
    command: GateCommand
    input_schema: dict[str, Any] = field(default_factory=dict)
    result_schema: dict[str, Any] = field(default_factory=dict)
    icon: str | None = None
    default_selected: bool = True
    feedback: GateFeedbackMode = "disabled"
    inputs: tuple[GateInputField, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        value: object,
        index: int,
        *,
        default_feedback: GateFeedbackMode = "disabled",
    ) -> GateOption:
        target = f"options[{index}]"
        data = json_object(value, target)
        reject_unknown_fields(
            data,
            {
                "id",
                "label",
                "command",
                "input_schema",
                "inputs",
                "result_schema",
                "icon",
                "default_selected",
                "feedback",
            },
            target,
        )
        option_id = validate_option_identifier(data.get("id"), f"{target}.id")
        label = validate_label(data.get("label"), f"{target}.label")
        default_selected = data.get("default_selected", True)
        if not isinstance(default_selected, bool):
            raise GateError(
                "invalid_request",
                f"{target}.default_selected",
                "default_selected must be a boolean",
            )
        feedback = data.get("feedback", default_feedback)
        if feedback not in {"disabled", "optional", "required"}:
            raise GateError(
                "invalid_request",
                f"{target}.feedback",
                "feedback must be disabled, optional, or required",
            )
        inputs = parse_gate_input_fields(data.get("inputs"), target)
        raw_input_schema = data.get("input_schema")
        provided_input_schema: dict[str, Any] | None = None
        if raw_input_schema is not None:
            provided_input_schema = json_object(
                raw_input_schema, f"{target}.input_schema"
            )
            check_json_schema(provided_input_schema, f"{target}.input_schema")
        if inputs:
            compiled_input_schema = compile_gate_input_schema(
                inputs, feedback_mode=feedback
            )
            if (
                provided_input_schema is not None
                and provided_input_schema != compiled_input_schema
            ):
                raise GateError(
                    "conflicting_input_declaration",
                    f"{target}.input_schema",
                    "input_schema must equal the schema compiled from 'inputs'",
                )
            input_schema = compiled_input_schema
        else:
            input_schema = (
                {} if provided_input_schema is None else provided_input_schema
            )
        result_schema = json_object(
            data.get("result_schema", {}), f"{target}.result_schema"
        )
        check_json_schema(result_schema, f"{target}.result_schema")
        return cls(
            id=option_id,
            label=label,
            command=GateCommand.from_value(data.get("command"), f"{target}.command"),
            input_schema=input_schema,
            result_schema=result_schema,
            icon=validate_icon(data.get("icon"), f"{target}.icon"),
            default_selected=default_selected,
            feedback=feedback,
            inputs=inputs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command.to_dict(),
            "input_schema": self.input_schema,
            "inputs": [gate_input_field.to_dict() for gate_input_field in self.inputs],
            "result_schema": self.result_schema,
            "icon": self.icon,
            "default_selected": self.default_selected,
            "feedback": self.feedback,
        }


@dataclass(frozen=True)
class GateGroup:
    """Display metadata for one AND branch's submit control."""

    options: tuple[str, ...]
    label: str | None = None
    icon: str | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> GateGroup:
        target = f"groups[{index}]"
        data = json_object(value, target)
        reject_unknown_fields(data, {"options", "label", "icon"}, target)
        raw_options = data.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise GateError(
                "invalid_group",
                f"{target}.options",
                "group options must be a non-empty array of option ids",
            )
        options = tuple(
            validate_option_identifier(option_id, f"{target}.options[{option_index}]")
            for option_index, option_id in enumerate(raw_options)
        )
        if len(set(options)) != len(options):
            raise GateError(
                "invalid_group",
                f"{target}.options",
                "group option ids must be unique",
            )
        raw_label = data.get("label")
        label = (
            None if raw_label is None else validate_label(raw_label, f"{target}.label")
        )
        return cls(
            options=options,
            label=label,
            icon=validate_icon(data.get("icon"), f"{target}.icon"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "options": list(self.options),
            "label": self.label,
            "icon": self.icon,
        }


def normalize_gate_structure(
    query_value: object,
    options_value: object,
    groups_value: object,
    *,
    default_feedback: GateFeedbackMode = "disabled",
) -> tuple[
    str, tuple[GateOption, ...], tuple[GateGroup, ...], tuple[tuple[str, ...], ...]
]:
    """Validate and normalize the query/options/groups cross-reference contract."""
    try:
        parsed = parse_gate_query(query_value)
    except GateQueryError as exc:
        raise GateError("invalid_query", "query", str(exc)) from exc

    if not isinstance(options_value, list) or not options_value:
        raise GateError(
            "invalid_request", "options", "at least one gate option is required"
        )
    options = tuple(
        GateOption.from_mapping(
            option,
            index,
            default_feedback=default_feedback,
        )
        for index, option in enumerate(options_value)
    )
    option_ids = [option.id for option in options]
    duplicates = sorted(
        option_id for option_id in set(option_ids) if option_ids.count(option_id) > 1
    )
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            "options",
            f"duplicate option id(s): {', '.join(duplicates)}",
        )
    queried_ids = {option_id for branch in parsed.branches for option_id in branch}
    declared_ids = set(option_ids)
    unknown = sorted(queried_ids - declared_ids)
    missing = sorted(declared_ids - queried_ids)
    if unknown:
        raise GateError(
            "unknown_option",
            "query",
            f"query references undeclared option(s): {', '.join(unknown)}",
        )
    if missing:
        raise GateError(
            "unreferenced_option",
            "options",
            f"option(s) are not referenced by the query: {', '.join(missing)}",
        )

    if groups_value is None:
        groups_value = []
    if not isinstance(groups_value, list):
        raise GateError("invalid_request", "groups", "groups must be an array")
    configs = tuple(
        GateGroup.from_mapping(group, index) for index, group in enumerate(groups_value)
    )
    and_branches = tuple(branch for branch in parsed.branches if len(branch) > 1)
    branch_by_members = {frozenset(branch): branch for branch in and_branches}
    configs_by_members: dict[frozenset[str], GateGroup] = {}
    for index, config in enumerate(configs):
        members = frozenset(config.options)
        branch = branch_by_members.get(members)
        if branch is None:
            raise GateError(
                "invalid_group",
                f"groups[{index}].options",
                "configured group does not match an AND branch in the query",
            )
        if members in configs_by_members:
            raise GateError(
                "invalid_group",
                f"groups[{index}].options",
                "an AND branch may be configured only once",
            )
        configs_by_members[members] = config

    by_id = {option.id: option for option in options}
    groups: list[GateGroup] = []
    for branch in and_branches:
        group_config = configs_by_members.get(frozenset(branch))
        first = by_id[branch[0]]
        groups.append(
            GateGroup(
                options=branch,
                label=(
                    group_config.label
                    if group_config is not None and group_config.label is not None
                    else first.label
                ),
                icon=(
                    group_config.icon
                    if group_config is not None and group_config.icon is not None
                    else first.icon
                ),
            )
        )
    return parsed.query, options, tuple(groups), parsed.branches


def normalize_primary_branch(
    value: object,
    branches: tuple[tuple[str, ...], ...],
    *,
    target: str = "primary_branch",
) -> tuple[str, ...]:
    """Validate the complete canonical branch used as a gate's primary action."""
    if not isinstance(value, list) or not value:
        raise GateError(
            "invalid_primary_branch",
            target,
            f"{target} must be a non-empty array of option ids",
        )
    primary = tuple(
        validate_option_identifier(option_id, f"{target}[{index}]")
        for index, option_id in enumerate(value)
    )
    if len(set(primary)) != len(primary):
        raise GateError(
            "invalid_primary_branch",
            target,
            f"{target} option ids must be unique",
        )
    matching = [branch for branch in branches if set(branch) == set(primary)]
    if len(matching) != 1:
        raise GateError(
            "invalid_primary_branch",
            target,
            f"{target} must exactly match one complete query branch",
        )
    canonical = matching[0]
    if primary != canonical:
        raise GateError(
            "invalid_primary_branch",
            target,
            f"{target} option ids must follow canonical query order",
        )
    return canonical
