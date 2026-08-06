"""Validation contracts for built-in notification gate kinds."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sase.notification_gates.adapters import GateAdapter
from sase.notification_gates.models import GateError, GateSpec


def validate_plan_spec(spec: GateSpec, adapter: GateAdapter) -> None:
    """Keep plan gates on their tier-specific trusted command contract."""
    from sase.plan_gate import (
        PLAN_EDIT_OPERATION_ID,
        PLAN_RESOURCE_PATH,
        TALE_PLAN_SUBMIT_GROUP,
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
    if tier == "tale":
        if len(spec.groups) != 1:
            raise GateError(
                "invalid_plan_group",
                "groups",
                "tale plan gates require exactly one configured submit group",
            )
        actual_group = spec.groups[0]
        if actual_group.options != TALE_PLAN_SUBMIT_GROUP.options:
            raise GateError(
                "invalid_plan_group",
                "groups[0].options",
                "tale plan submit group must contain the canonical options: "
                + ", ".join(TALE_PLAN_SUBMIT_GROUP.options),
            )
        if actual_group.label != TALE_PLAN_SUBMIT_GROUP.label:
            raise GateError(
                "invalid_plan_group",
                "groups[0].label",
                "tale plan submit group label must be "
                f"{TALE_PLAN_SUBMIT_GROUP.label!r}",
            )
        if actual_group.icon != TALE_PLAN_SUBMIT_GROUP.icon:
            raise GateError(
                "invalid_plan_group",
                "groups[0].icon",
                f"tale plan submit group icon must be {TALE_PLAN_SUBMIT_GROUP.icon!r}",
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


def validate_launch_spec(spec: GateSpec) -> None:
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


def validate_question_spec(spec: GateSpec) -> None:
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


def validate_task_triage_spec(spec: GateSpec) -> None:
    """Keep TaskTriage gates on their human-only trusted task contract."""
    from sase.bead.task_gate import (
        TASK_TRIAGE_COMMAND_PATHS,
        TASK_TRIAGE_CONTINUATION_MODE,
        TASK_TRIAGE_OPTION_IDS,
        TASK_TRIAGE_PREVIEW_PATH,
        TASK_TRIAGE_QUERY,
        TaskTriageAction,
        render_task_triage_preview,
        task_triage_presentation_note,
        task_triage_gate_command_script,
        task_triage_result_schema,
    )
    from sase.bead.model import (
        CloseRecord,
        PhaseSize,
        ReopenCause,
        Resolution,
        TaskPlusOneEvidence,
    )
    from sase.core.paths import is_valid_sase_project_name

    if spec.continuation_mode != TASK_TRIAGE_CONTINUATION_MODE:
        raise GateError(
            "invalid_task_triage_continuation",
            "continuation_mode",
            f"task triage gates require {TASK_TRIAGE_CONTINUATION_MODE}",
        )
    if spec.query != TASK_TRIAGE_QUERY or spec.branches != (
        ("launch",),
        ("close",),
    ):
        raise GateError(
            "invalid_task_triage_query",
            "query",
            f"task triage gates require query: {TASK_TRIAGE_QUERY}",
        )
    if spec.groups or spec.operations:
        raise GateError(
            "invalid_task_triage_structure",
            "groups",
            "task triage gates do not define groups or operations",
        )

    payload = spec.payload
    expected_payload_fields = {
        "bead_id",
        "project",
        "title",
        "created_at",
        "size",
        "refs",
        "plus_one_count",
        "plus_one_evidence",
        "close_history",
    }
    if set(payload) != expected_payload_fields:
        raise GateError(
            "invalid_task_triage_payload",
            "payload",
            "task triage payload does not match the structured presentation contract",
        )
    for field in ("bead_id", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.{field}",
                f"task triage payload requires {field}",
            )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.project",
            "task triage payload requires a canonical SASE project key",
        )
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.created_at",
            "task triage payload created_at must be a string",
        )
    size = payload.get("size")
    if size is not None and (
        not isinstance(size, str) or size not in {item.value for item in PhaseSize}
    ):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.size",
            "task triage payload size must be null or a valid task size",
        )
    refs = payload.get("refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.refs",
            "task triage payload refs must be a string list",
        )
    raw_evidence = payload.get("plus_one_evidence")
    if not isinstance(raw_evidence, list):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.plus_one_evidence",
            "task triage +1 evidence must be a list",
        )
    evidence: list[TaskPlusOneEvidence] = []
    reporters: set[str] = set()
    for index, raw_item in enumerate(raw_evidence):
        if not isinstance(raw_item, Mapping) or set(raw_item) != {
            "timestamp",
            "reporter",
            "note",
            "refs",
        }:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                "task triage +1 evidence entry is malformed",
            )
        item_refs = raw_item.get("refs")
        if not isinstance(item_refs, list) or any(
            not isinstance(ref, str) for ref in item_refs
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}.refs",
                "task triage +1 evidence refs must be a string list",
            )
        if any(
            not isinstance(raw_item.get(field), str)
            for field in ("timestamp", "reporter", "note")
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                "task triage +1 evidence text fields must be strings",
            )
        item = TaskPlusOneEvidence(
            timestamp=cast(str, raw_item["timestamp"]),
            reporter=cast(str, raw_item["reporter"]),
            note=cast(str, raw_item["note"]),
            refs=tuple(item_refs),
        )
        try:
            item.validate()
        except ValueError as exc:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}",
                str(exc),
            ) from exc
        if item.reporter in reporters:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.plus_one_evidence.{index}.reporter",
                "task triage +1 evidence reporters must be unique",
            )
        reporters.add(item.reporter)
        evidence.append(item)
    count = payload.get("plus_one_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(evidence):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.plus_one_count",
            "task triage +1 count must equal its evidence entries",
        )

    raw_close_history = payload.get("close_history")
    if not isinstance(raw_close_history, list):
        raise GateError(
            "invalid_task_triage_payload",
            "payload.close_history",
            "task triage close history must be a list",
        )
    resolution_values = {item.value for item in Resolution}
    reopen_cause_values = {item.value for item in ReopenCause}
    close_history: list[CloseRecord] = []
    for index, raw_record in enumerate(raw_close_history):
        if not isinstance(raw_record, Mapping) or set(raw_record) != {
            "closed_at",
            "close_reason",
            "resolution",
            "reopened_at",
            "reopened_via",
            "reopened_by",
        }:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history entry is malformed",
            )
        raw_resolution = raw_record.get("resolution")
        if raw_resolution is not None and raw_resolution not in resolution_values:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}.resolution",
                "task triage close history resolution is invalid",
            )
        raw_reopened_via = raw_record.get("reopened_via")
        if raw_reopened_via not in reopen_cause_values:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}.reopened_via",
                "task triage close history reopened_via is invalid",
            )
        raw_close_reason = raw_record.get("close_reason")
        raw_reopened_by = raw_record.get("reopened_by")
        if (raw_close_reason is not None and not isinstance(raw_close_reason, str)) or (
            raw_reopened_by is not None and not isinstance(raw_reopened_by, str)
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history text fields must be strings or null",
            )
        if any(
            not isinstance(raw_record.get(field), str)
            for field in ("closed_at", "reopened_at")
        ):
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                "task triage close history timestamps must be strings",
            )
        record = CloseRecord(
            closed_at=cast(str, raw_record["closed_at"]),
            reopened_at=cast(str, raw_record["reopened_at"]),
            reopened_via=ReopenCause(raw_reopened_via),
            close_reason=cast(str | None, raw_close_reason),
            resolution=Resolution(raw_resolution) if raw_resolution else None,
            reopened_by=cast(str | None, raw_reopened_by),
        )
        try:
            record.validate()
        except ValueError as exc:
            raise GateError(
                "invalid_task_triage_payload",
                f"payload.close_history.{index}",
                str(exc),
            ) from exc
        close_history.append(record)

    if tuple(option.id for option in spec.options) != TASK_TRIAGE_OPTION_IDS:
        raise GateError(
            "invalid_task_triage_options",
            "options",
            "task triage gates require launch and close options",
        )
    expected_feedback = {"launch": "optional", "close": "required"}
    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    for option in spec.options:
        typed_option_id = cast(TaskTriageAction, option.id)
        expected_command = TASK_TRIAGE_COMMAND_PATHS[typed_option_id]
        if (
            option.command.argv != (expected_command,)
            or option.input_schema != empty_input_schema
            or option.result_schema != task_triage_result_schema(typed_option_id)
            or option.feedback != expected_feedback[option.id]
        ):
            raise GateError(
                "invalid_task_triage_options",
                f"options.{option.id}",
                "task triage option does not match the registered adapter",
            )

    resources = {resource.path: resource for resource in spec.resources}
    expected_paths = {
        *TASK_TRIAGE_COMMAND_PATHS.values(),
        TASK_TRIAGE_PREVIEW_PATH,
    }
    if set(resources) != expected_paths:
        raise GateError(
            "invalid_task_triage_resources",
            "resources",
            "task triage gates require only their preview and command resources",
        )
    preview = resources[TASK_TRIAGE_PREVIEW_PATH]
    if preview.role != "preview" or preview.executable:
        raise GateError(
            "invalid_task_triage_preview",
            TASK_TRIAGE_PREVIEW_PATH,
            "task triage preview resource is invalid",
        )
    try:
        preview_content = (
            preview.content
            if preview.content is not None
            else preview.source.read_text(encoding="utf-8")
            if preview.source is not None
            else None
        )
    except OSError as exc:
        raise GateError(
            "invalid_task_triage_preview",
            TASK_TRIAGE_PREVIEW_PATH,
            f"cannot read task triage preview: {exc}",
        ) from exc
    for option_id, path in TASK_TRIAGE_COMMAND_PATHS.items():
        command = resources[path]
        if command.role != "command" or not command.executable:
            raise GateError(
                "invalid_task_triage_command",
                path,
                "task triage command resource is invalid",
            )
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
                "invalid_task_triage_command",
                path,
                f"cannot read task triage command: {exc}",
            ) from exc
        if content != task_triage_gate_command_script(option_id):
            raise GateError(
                "invalid_task_triage_command",
                path,
                "task triage command does not match the registered adapter",
            )

    expected_note = task_triage_presentation_note(
        cast(str, payload["bead_id"]),
        cast(str, payload["title"]),
        count,
        created_at=created_at,
        reopen_count=len(close_history),
    )
    presentation = spec.presentation
    origin_agent = presentation.get("origin_agent")
    if (
        presentation.get("sender") != "bead"
        or presentation.get("icon") != "✦"
        or presentation.get("notes") != [expected_note]
        or presentation.get("tags") != ["bead", "task"]
        or presentation.get("panel") != "beads"
        or (origin_agent is not None and not isinstance(origin_agent, str))
        or (isinstance(origin_agent, str) and not origin_agent)
        or presentation.get("files") != [TASK_TRIAGE_PREVIEW_PATH]
        or presentation.get("preview") != TASK_TRIAGE_PREVIEW_PATH
    ):
        raise GateError(
            "invalid_task_triage_presentation",
            "presentation",
            "task triage presentation does not match the registered adapter",
        )
    description_marker = "__TASK_TRIAGE_DESCRIPTION__"
    notes_marker = "__TASK_TRIAGE_NOTES__"
    template = render_task_triage_preview(
        bead_id=cast(str, payload["bead_id"]),
        title=cast(str, payload["title"]),
        description=description_marker,
        notes=notes_marker,
        created_by=cast(str, origin_agent or ""),
        created_at=created_at,
        size=cast(str | None, size),
        refs=cast(list[str], refs),
        plus_one_evidence=evidence,
        close_history=close_history,
    )
    preview_prefix, marker, template_tail = template.partition(description_marker)
    description_notes_separator, marker_two, preview_suffix = template_tail.partition(
        notes_marker
    )
    preview_body = ""
    if (
        marker
        and marker_two
        and isinstance(preview_content, str)
        and preview_content.startswith(preview_prefix)
        and preview_content.endswith(preview_suffix)
    ):
        body_end = len(preview_content) - len(preview_suffix)
        preview_body = preview_content[len(preview_prefix) : body_end]
    description, separator, notes = preview_body.partition(description_notes_separator)
    expected_preview = (
        render_task_triage_preview(
            bead_id=cast(str, payload["bead_id"]),
            title=cast(str, payload["title"]),
            description=description,
            notes=notes,
            created_by=cast(str, origin_agent or ""),
            created_at=created_at,
            size=cast(str | None, size),
            refs=cast(list[str], refs),
            plus_one_evidence=evidence,
            close_history=close_history,
        )
        if separator
        else None
    )
    if preview_content != expected_preview:
        raise GateError(
            "invalid_task_triage_preview",
            TASK_TRIAGE_PREVIEW_PATH,
            "task triage preview does not match the registered adapter",
        )
