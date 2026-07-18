"""Registered typed projections and validation for notification gates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.notification_gates.models import (
    GateError,
    GateOption,
    GateSpec,
    validate_icon,
)


@dataclass(frozen=True)
class GateAdapter:
    """The stable typed transport and legacy-file shape for one gate kind."""

    kind: str
    action: str
    pending_action_kind: str
    sender: str
    request_filename: str
    response_filename: str
    legacy_directory_key: str
    auto_policy: str
    neutral_only: bool = False

    def resolve_auto_selection(
        self, spec: GateSpec, argument: str | None
    ) -> tuple[str, ...]:
        """Interpret the common opaque auto argument for this kind."""
        by_id = {option.id: option for option in spec.options}
        if self.auto_policy == "forbidden":
            raise GateError(
                "auto_not_supported",
                "auto",
                f"automatic resolution is not supported for {self.kind} gates",
            )
        if self.auto_policy == "first":
            if argument not in (None, "", "first"):
                raise GateError(
                    "invalid_auto_argument",
                    "auto.argument",
                    f"unsupported {self.kind} auto argument: {argument}",
                )
            return _default_branch_selection(spec.branches[0], by_id)

        allowed = {
            "plan": {None, "", "plan", "tale"},
            "epic_plan": {None, "", "epic", "epic_plan"},
        }[self.kind]
        if argument not in allowed:
            raise GateError(
                "invalid_auto_argument",
                "auto.argument",
                f"unsupported {self.kind} auto argument: {argument}",
            )
        preferred = ("approve",) if self.kind == "plan" else ("approve", "epic")
        for option_id in preferred:
            branch = next(
                (branch for branch in spec.branches if option_id in branch),
                None,
            )
            if branch is not None:
                defaults = set(_default_branch_selection(branch, by_id))
                defaults.add(option_id)
                return tuple(member for member in branch if member in defaults)
        raise GateError(
            "invalid_auto_selection",
            "options",
            f"{self.kind} auto resolution requires an approval option",
        )

    def apply_side_effects(
        self, *, bundle_path: Path, response: Mapping[str, Any]
    ) -> None:
        """Apply adapter-declared host effects after terminal persistence."""
        if self.kind not in {"plan", "epic_plan"}:
            return
        from sase.notification_gates.durability import read_json_object
        from sase.plan_approval_actions import run_plan_side_effects
        from sase.plan_gate import (
            plan_context_from_envelope,
            translate_plan_gate_response,
        )

        envelope = read_json_object(bundle_path / "request.json")
        selected = response.get("selected_option_ids")
        option_results = response.get("option_results")
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(option_id, str) for option_id in selected)
            or not isinstance(option_results, list)
        ):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "plan response is missing its selected options or results",
            )
        selected_ids = tuple(selected)
        plan_action = (
            "epic"
            if self.kind == "epic_plan" and selected_ids == ("approve",)
            else "commit"
            if selected_ids == ("commit",)
            else selected_ids[0]
        )
        first_result = next(
            (
                entry.get("result")
                for entry in option_results
                if isinstance(entry, Mapping) and entry.get("id") == selected_ids[0]
            ),
            None,
        )
        if not isinstance(first_result, dict):
            raise GateError(
                "invalid_response",
                str(bundle_path / "response.json"),
                "plan response is missing the primary option result",
            )
        result = first_result
        context = plan_context_from_envelope(bundle_path, envelope)
        translated = translate_plan_gate_response(bundle_path, response)
        result.update(translated)
        run_plan_side_effects(
            context,
            plan_action,
            bundle_path / "response.json",
            result,
            response_container=response if isinstance(response, dict) else None,
            source=str(response.get("source") or "plan_response"),
        )
        if plan_action == "epic" and result.get("epic_launch_owner") == "host":
            raw_input = response.get("input")
            mode = (
                raw_input.get("epic_launch_mode")
                if isinstance(raw_input, dict)
                else None
            )
            if mode in {"detached", "foreground"}:
                from sase.plan_approval_actions import (
                    durable_plan_file_for_context,
                    prepare_epic_launch,
                )

                launch_plan = durable_plan_file_for_context(context) or (
                    bundle_path / "plan.md"
                )

                launched = prepare_epic_launch(
                    context,
                    launch_plan,
                    mode=mode,
                    response_dir=bundle_path,
                )
                if not launched:
                    raise GateError(
                        "epic_launch_failed",
                        str(launch_plan),
                        "host claimed the epic launch but could not start it",
                    )

    def validate_edited_resource(self, *, path: Path) -> None:
        """Validate an editable target before advancing its review revision."""
        if self.kind not in {"plan", "epic_plan"}:
            return
        from sase.plan_approval_actions import require_plan_approval_validation

        require_plan_approval_validation(
            path,
            "epic" if self.kind == "epic_plan" else "tale",
        )

    def regenerate_previews(self, *, bundle_path: Path) -> None:
        """Regenerate adapter-owned previews after an edit."""
        del bundle_path

    def automatic_input(self, spec: GateSpec) -> dict[str, Any]:
        """Return adapter-owned input for a common automatic resolution."""
        if self.kind == "question":
            from sase.user_question_actions import automatic_question_response

            try:
                return automatic_question_response(spec.payload)
            except Exception as exc:
                if isinstance(exc, GateError):
                    raise
                code = getattr(exc, "code", "invalid_auto_input")
                target = getattr(exc, "target", "auto")
                raise GateError(str(code), str(target), str(exc)) from exc
        if self.kind == "epic_plan":
            return {"epic_launch_mode": "detached"}
        return {}


def _default_branch_selection(
    branch: tuple[str, ...], by_id: Mapping[str, GateOption]
) -> tuple[str, ...]:
    selected = tuple(
        option_id for option_id in branch if by_id[option_id].default_selected
    )
    return selected or (branch[0],)


_ADAPTERS = (
    GateAdapter(
        kind="plan",
        action="PlanApproval",
        pending_action_kind="plan_approval",
        sender="plan",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="epic_plan",
        action="EpicApproval",
        pending_action_kind="epic_approval",
        sender="epic",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_policy="approval",
    ),
    GateAdapter(
        kind="question",
        action="UserQuestion",
        pending_action_kind="user_question",
        sender="question",
        request_filename="question_request.json",
        response_filename="question_response.json",
        legacy_directory_key="response_dir",
        auto_policy="first",
    ),
    GateAdapter(
        kind="launch",
        action="LaunchApproval",
        pending_action_kind="launch_approval",
        sender="launch",
        request_filename="launch_request.json",
        response_filename="launch_response.json",
        legacy_directory_key="response_dir",
        auto_policy="forbidden",
    ),
    GateAdapter(
        kind="hitl",
        action="HITL",
        pending_action_kind="hitl",
        sender="hitl",
        request_filename="hitl_request.json",
        response_filename="hitl_response.json",
        legacy_directory_key="artifacts_dir",
        auto_policy="forbidden",
    ),
    GateAdapter(
        kind="custom",
        action="CustomGate",
        pending_action_kind="custom_gate",
        sender="custom",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        auto_policy="forbidden",
        neutral_only=True,
    ),
)

_BY_KIND = {adapter.kind: adapter for adapter in _ADAPTERS}
_BY_ACTION = {adapter.action: adapter for adapter in _ADAPTERS}
_KIND_ALIASES = {
    "plan_approval": "plan",
    "epic": "epic_plan",
    "epic_approval": "epic_plan",
    "user_question": "question",
    "launch_approval": "launch",
}

PRIVILEGED_GATE_ACTIONS = frozenset(_BY_ACTION)


def adapter_for_kind(kind: str) -> GateAdapter:
    """Return the registered adapter for *kind*."""
    canonical = _KIND_ALIASES.get(kind, kind)
    try:
        return _BY_KIND[canonical]
    except KeyError as exc:
        raise GateError(
            "unknown_gate_kind", "kind", f"unregistered gate kind: {kind}"
        ) from exc


def adapter_for_action(action: str | None) -> GateAdapter | None:
    """Return the registered adapter projected by a notification action."""
    if action is None:
        return None
    return _BY_ACTION.get(action)


def registered_gate_kinds() -> tuple[str, ...]:
    """Return canonical registered kind identifiers."""
    return tuple(adapter.kind for adapter in _ADAPTERS)


def validate_gate_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Validate cross-field ownership and adapter invariants."""
    resource_paths = [resource.path for resource in spec.resources]
    _reject_duplicates(resource_paths, "resources", "resource path")
    reserved_roots = {
        ".creation.json",
        ".creation_result.json",
        ".response.lock",
        "cancellation.json",
        "request.json",
        "response.json",
    }
    for path in resource_paths:
        if path.split("/", 1)[0] in reserved_roots:
            raise GateError(
                "reserved_resource_path",
                path,
                f"resource path is reserved by the gate service: {path}",
            )
    resources = {resource.path: resource for resource in spec.resources}

    option_ids = [option.id for option in spec.options]
    _reject_duplicates(option_ids, "options", "option id")
    operation_ids = [operation.id for operation in spec.operations]
    _reject_duplicates(operation_ids, "operations", "operation id")
    overlap = set(option_ids) & set(operation_ids)
    if overlap:
        raise GateError(
            "duplicate_identifier",
            "operations",
            f"option and operation ids overlap: {', '.join(sorted(overlap))}",
        )

    for option in spec.options:
        command_path = option.command.argv[0]
        resource = resources.get(command_path)
        if resource is None or resource.role != "command" or not resource.executable:
            raise GateError(
                "unowned_command",
                f"options.{option.id}.command",
                f"command must reference an executable command resource: {command_path}",
            )
    for operation in spec.operations:
        resource = resources.get(operation.target)
        if resource is None or resource.role != "editable":
            raise GateError(
                "unowned_edit_target",
                f"operations.{operation.id}.target",
                f"edit target must reference an editable resource: {operation.target}",
            )

    presentation = spec.presentation
    declared_action = presentation.get("action")
    if declared_action is not None and declared_action != adapter.action:
        raise GateError(
            "action_kind_mismatch",
            "presentation.action",
            f"{adapter.kind} gates project as {adapter.action}",
        )
    sender = presentation.get("sender", adapter.sender)
    if not isinstance(sender, str) or not sender.strip():
        raise GateError(
            "invalid_presentation",
            "presentation.sender",
            "notification sender must be a non-empty string",
        )
    validate_icon(presentation.get("icon"), "presentation.icon")
    _validate_string_or_list(presentation.get("notes", []), "presentation.notes")
    _validate_string_or_list(presentation.get("tags", []), "presentation.tags")
    files = _validate_string_or_list(
        presentation.get("files", []), "presentation.files"
    )
    for path in files:
        if path not in resources:
            raise GateError(
                "unowned_attachment",
                "presentation.files",
                f"notification attachment is not a bundle resource: {path}",
            )
    preview = presentation.get("preview")
    if preview is not None:
        if not isinstance(preview, str) or preview not in resources:
            raise GateError(
                "unowned_preview",
                "presentation.preview",
                "preview must reference a bundle resource",
            )
        if resources[preview].role != "preview":
            raise GateError(
                "invalid_preview",
                "presentation.preview",
                "preview must reference a preview resource",
            )
    action_data = presentation.get("action_data", {})
    if not isinstance(action_data, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in action_data.items()
    ):
        raise GateError(
            "invalid_presentation",
            "presentation.action_data",
            "action_data must be an object of string values",
        )
    protected = {
        "bundle_path",
        "request_id",
        "request_kind",
        "request_path",
        "response_path",
        adapter.legacy_directory_key,
    }
    overwritten = protected & set(action_data)
    if overwritten:
        raise GateError(
            "reserved_action_data",
            "presentation.action_data",
            f"reserved action_data key(s): {', '.join(sorted(overwritten))}",
        )

    silent = presentation.get("silent", False)
    if not isinstance(silent, bool):
        raise GateError(
            "invalid_presentation",
            "presentation.silent",
            "silent must be a boolean",
        )
    try:
        json.dumps(spec.payload, allow_nan=False)
        json.dumps(spec.producer, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GateError(
            "invalid_request",
            "payload",
            "payload and producer must contain JSON values",
        ) from exc
    if adapter.kind == "launch":
        _validate_launch_spec(spec)
    if adapter.kind == "question":
        _validate_question_spec(spec)
    if adapter.kind in {"plan", "epic_plan"}:
        _validate_plan_spec(spec, adapter)
    if spec.auto.enabled:
        adapter.resolve_auto_selection(spec, spec.auto.argument)
        adapter.automatic_input(spec)


def _validate_plan_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Keep plan gates on their tier-specific trusted command contract."""
    from sase.plan_gate import (
        PLAN_EDIT_OPERATION_ID,
        PLAN_RESOURCE_PATH,
        PlanGateTier,
        plan_gate_command_script,
        plan_gate_option_ids,
        plan_gate_query,
    )

    tier = "epic" if adapter.kind == "epic_plan" else "tale"
    if spec.payload.get("authored_tier") != tier:
        raise GateError(
            "plan_tier_mismatch",
            "payload.authored_tier",
            f"{adapter.kind} gates require authored tier {tier}",
        )
    if spec.payload.get("plan_resource") != PLAN_RESOURCE_PATH:
        raise GateError(
            "invalid_plan_payload",
            "payload.plan_resource",
            "plan gate payload must reference the adapter-owned plan resource",
        )

    typed_tier = cast(PlanGateTier, tier)
    expected_query = plan_gate_query(typed_tier)
    expected_branches = (
        (("approve",), ("reject",), ("feedback",))
        if tier == "epic"
        else (("approve", "commit"), ("reject",), ("feedback",))
    )
    if spec.query != expected_query or spec.branches != expected_branches:
        raise GateError(
            "invalid_plan_query",
            "query",
            f"{tier} plan gates require query: {expected_query}",
        )
    expected_options = plan_gate_option_ids(typed_tier)
    actual_commands = {option.id: option.command.argv[0] for option in spec.options}
    expected_commands = {
        option_id: f"commands/{option_id}" for option_id in expected_options
    }
    if actual_commands != expected_commands:
        raise GateError(
            "invalid_plan_options",
            "options",
            f"{tier} plan gate options do not match the registered adapter",
        )
    if tier == "tale" and (
        len(spec.groups) != 1
        or spec.groups[0].options != ("approve", "commit")
        or spec.groups[0].label != "Approve"
        or spec.groups[0].icon != "✅"
    ):
        raise GateError(
            "invalid_plan_group",
            "groups",
            "tale plan gates require the configured Approve submit group",
        )
    if tier == "epic" and spec.groups:
        raise GateError(
            "invalid_plan_group", "groups", "epic plan gates do not define groups"
        )
    if len(spec.operations) != 1 or (
        spec.operations[0].id,
        spec.operations[0].kind,
        spec.operations[0].target,
    ) != (PLAN_EDIT_OPERATION_ID, "edit_file", PLAN_RESOURCE_PATH):
        raise GateError(
            "invalid_plan_operation",
            "operations",
            "plan gates require the registered edit_plan operation",
        )

    resources = {resource.path: resource for resource in spec.resources}
    plan_resource = resources.get(PLAN_RESOURCE_PATH)
    if plan_resource is None or plan_resource.role != "editable":
        raise GateError(
            "invalid_plan_resource",
            PLAN_RESOURCE_PATH,
            "plan gates require one editable plan.md resource",
        )
    for option_id, path in expected_commands.items():
        resource = resources.get(path)
        if resource is None or resource.role != "command":
            raise GateError(
                "invalid_plan_command", path, "plan command resource is missing"
            )
        try:
            content = (
                resource.content
                if resource.content is not None
                else resource.source.read_text(encoding="utf-8")
                if resource.source is not None
                else None
            )
        except OSError as exc:
            raise GateError(
                "invalid_plan_command", path, f"cannot read plan command: {exc}"
            ) from exc
        if content != plan_gate_command_script(option_id):
            raise GateError(
                "invalid_plan_command",
                path,
                "plan command does not match the registered adapter",
            )


def _validate_launch_spec(spec: GateSpec) -> None:
    """Keep privileged launch gates on the registered command contract."""
    expected_query = "approve OR reject OR feedback"
    expected_branches = (("approve",), ("reject",), ("feedback",))
    if spec.query != expected_query or spec.branches != expected_branches:
        raise GateError(
            "invalid_launch_query",
            "query",
            f"launch gates require query: {expected_query}",
        )
    expected_commands = {
        "approve": "commands/approve",
        "reject": "commands/reject",
        "feedback": "commands/feedback",
    }
    actual_commands = {option.id: option.command.argv[0] for option in spec.options}
    if actual_commands != expected_commands:
        raise GateError(
            "invalid_launch_options",
            "options",
            "launch gates require approve, reject, and feedback options",
        )

    from sase.agent.launch_request import launch_gate_command_script

    resources = {resource.path: resource for resource in spec.resources}
    for option_id, path in expected_commands.items():
        resource = resources[path]
        try:
            content = (
                resource.content
                if resource.content is not None
                else resource.source.read_text(encoding="utf-8")
                if resource.source is not None
                else None
            )
        except OSError as exc:
            raise GateError(
                "invalid_launch_command", path, f"cannot read launch command: {exc}"
            ) from exc
        if content != launch_gate_command_script(option_id):
            raise GateError(
                "invalid_launch_command",
                path,
                "launch command does not match the registered adapter",
            )

    dispatch = spec.payload.get("dispatch")
    if not isinstance(dispatch, Mapping):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch",
            "launch payload requires a dispatch object",
        )
    if (
        not isinstance(dispatch.get("prompt"), str)
        or not str(dispatch.get("prompt")).strip()
    ):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch.prompt",
            "launch payload requires a prompt",
        )
    if not isinstance(dispatch.get("cwd"), str) or not dispatch.get("cwd"):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch.cwd",
            "launch payload requires a cwd",
        )


def _validate_question_spec(spec: GateSpec) -> None:
    """Keep UserQuestion gates on the registered complete-form contract."""
    from sase.user_question_actions import (
        QUESTION_COMMAND_PATH,
        QUESTION_CONTINUATION_MODE,
        QUESTION_OPTION_ID,
        UserQuestionActionError,
        question_gate_command_script,
        question_response_schema,
        validate_user_questions,
    )

    if spec.continuation_mode != QUESTION_CONTINUATION_MODE:
        raise GateError(
            "invalid_question_continuation",
            "continuation_mode",
            f"question gates require {QUESTION_CONTINUATION_MODE}",
        )
    try:
        questions = validate_user_questions(spec.payload.get("questions"))
    except UserQuestionActionError as exc:
        raise GateError(exc.code, exc.target, str(exc)) from exc
    session_id = spec.payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise GateError(
            "invalid_question_payload",
            "payload.session_id",
            "question session id is required",
        )
    if spec.request_id is not None and session_id != spec.request_id:
        raise GateError(
            "invalid_question_payload",
            "payload.session_id",
            "question session id must match request id",
        )
    if (
        spec.query != QUESTION_OPTION_ID
        or len(spec.options) != 1
        or spec.branches != ((QUESTION_OPTION_ID,),)
    ):
        raise GateError(
            "invalid_question_options",
            "options",
            "question gates require one singleton submit branch",
        )
    option = spec.options[0]
    if option.id != QUESTION_OPTION_ID or option.command.argv != (
        QUESTION_COMMAND_PATH,
    ):
        raise GateError(
            "invalid_question_options",
            "options",
            "question gates require the registered submit option",
        )
    expected_schema = question_response_schema(questions)
    if (
        option.input_schema != expected_schema
        or option.result_schema != expected_schema
    ):
        raise GateError(
            "invalid_question_schema",
            "options.submit",
            "question submit schemas must match the adapter input form",
        )
    resources = {resource.path: resource for resource in spec.resources}
    if set(resources) != {QUESTION_COMMAND_PATH}:
        raise GateError(
            "invalid_question_resources",
            "resources",
            "question gates require only the registered submit command",
        )
    command = resources[QUESTION_COMMAND_PATH]
    try:
        content = (
            command.content
            if command.content is not None
            else command.source.read_text(encoding="utf-8")
            if command.source is not None
            else None
        )
    except OSError as exc:
        raise GateError(
            "invalid_question_command",
            QUESTION_COMMAND_PATH,
            f"cannot read question command: {exc}",
        ) from exc
    if content != question_gate_command_script():
        raise GateError(
            "invalid_question_command",
            QUESTION_COMMAND_PATH,
            "question command does not match the registered adapter",
        )


def _reject_duplicates(values: list[str], target: str, label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise GateError(
            "duplicate_identifier",
            target,
            f"duplicate {label}(s): {', '.join(sorted(duplicates))}",
        )


def _validate_string_or_list(value: object, target: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise GateError(
        "invalid_presentation", target, f"{target} must be a string or string array"
    )


__all__ = [
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "adapter_for_action",
    "adapter_for_kind",
    "registered_gate_kinds",
    "validate_gate_spec",
]
