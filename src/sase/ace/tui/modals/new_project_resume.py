"""Recover a failed add or create resume into a Reviewable draft.

I/O stays in :func:`load_resume_context`. Recovery never executes a stored
command or copies proc transport or result flags into a new submission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.ops import OperationIOError, read_operation_request
from sase.procs import get_proc
from sase.procs.runtime import proc_operation_request_path
from sase.project_onboarding.journal import lookup_journal

from .new_project_configure_model import ConfigureDraft
from .new_project_review_model import (
    options_from_argv,
    requested_from_argv,
    strip_transport_flags,
)
from .new_project_source_model import SourceRow

_MISSING_INTENT_NOTICE = (
    "Previous add choices were not recovered. Review this plan before applying."
)
_MISSING_CREATE_INTENT_NOTICE = (
    "Previous create choices were not recovered. Review this plan before applying."
)
_UNRECOVERABLE_CREATE_ERROR = (
    "The previous create choices could not be recovered, so the original "
    "intent is not being reused. Pick the repository in Source and use the "
    "explicit add action to register it as an existing repository instead."
)


@dataclass(frozen=True, slots=True)
class _ResumeContext:
    """Durable journal plus optional proc request/command evidence."""

    journal: dict[str, Any] | None
    request: dict[str, Any] | None
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CreateRecovery:
    """Recovered create intent: namespace, name, options, and project choices."""

    owner: str = ""
    raw_name: str = ""
    ref: str = ""
    identity_key: str = ""
    visibility: str = "private"
    options: dict[str, str] = field(default_factory=dict)
    summary: tuple[str, ...] = ()
    project_name: str = ""
    aliases: tuple[str, ...] = ()
    setup: str = "auto"
    make_current: bool = False


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Hydrated resume ready for Configure back-navigation and Review check."""

    identity_key: str
    ref: str
    workflow_type: str
    draft: ConfigureDraft
    target: dict[str, Any]
    notice: str
    error: str
    mode: str = "add"
    create: _CreateRecovery | None = None
    add_alternative: str = ""


def _request_for_operation(proc_id: str, operation: str) -> dict[str, Any] | None:
    """Read the typed durable request for one expected operation."""
    try:
        loaded = read_operation_request(
            proc_operation_request_path(proc_id),
            expected_operation=operation,
        )
    except (OSError, OperationIOError, ValueError):
        return None
    if loaded is not None and isinstance(loaded.payload, Mapping):
        return dict(loaded.payload)
    return None


def load_resume_context(identity_key: str) -> _ResumeContext:
    """Read the journal and, when present, the proc request sidecar."""
    journal = lookup_journal(identity_key)
    request: dict[str, Any] | None = None
    command: tuple[str, ...] = ()
    proc_id = str((journal or {}).get("proc_id") or "")
    if not proc_id:
        return _ResumeContext(journal=journal, request=None, command=())
    proc = get_proc(proc_id)
    if proc is not None:
        raw_command = proc.command or proc.argv
        command = tuple(str(item) for item in raw_command)
    journal_mode = str((journal or {}).get("mode") or "add")
    primary = "project.create" if journal_mode == "create" else "project.add"
    secondary = "project.add" if journal_mode == "create" else "project.create"
    request = _request_for_operation(proc_id, primary)
    if request is None:
        request = _request_for_operation(proc_id, secondary)
    return _ResumeContext(journal=journal, request=request, command=command)


def recover_resume_intent(
    *,
    row: SourceRow,
    workflow_type: str,
    context: _ResumeContext,
    seed_target: Mapping[str, Any],
) -> ResumePlan:
    """Validate recovered intent or fall back to a fresh checked add plan."""
    identity_key = str(
        row.data.get("identity_key") or seed_target.get("identity_key") or ""
    )
    ref = str(row.ref or seed_target.get("ref") or "")
    target = dict(seed_target)
    target["ref"] = ref or str(target.get("ref") or "")
    target["identity_key"] = identity_key or str(target.get("identity_key") or "")
    journal = context.journal
    journal_mode = str((journal or {}).get("mode") or "add")
    if journal is not None:
        if journal_mode == "create":
            return _recover_create_plan(
                row=row,
                workflow_type=workflow_type,
                context=context,
                identity_key=identity_key,
                ref=ref,
                target=target,
                seed_target=seed_target,
            )
        mismatch = _mismatch_error(journal, identity_key, workflow_type, ref)
        if mismatch:
            return ResumePlan(
                identity_key=identity_key,
                ref=ref,
                workflow_type=workflow_type,
                draft=ConfigureDraft(
                    name=str(seed_target.get("project_name_base") or "")
                ),
                target=target,
                notice="",
                error=mismatch,
            )
    draft, notice = _draft_from_context(
        context,
        fallback_name=str(seed_target.get("project_name_base") or row.display),
    )
    return ResumePlan(
        identity_key=identity_key,
        ref=ref,
        workflow_type=workflow_type,
        draft=draft,
        target=target,
        notice=notice,
        error="",
    )


def _recover_create_plan(
    *,
    row: SourceRow,
    workflow_type: str,
    context: _ResumeContext,
    identity_key: str,
    ref: str,
    target: dict[str, Any],
    seed_target: Mapping[str, Any],
) -> ResumePlan:
    """Validate a create journal and recover its complete create intent."""
    assert context.journal is not None
    mismatch = _create_mismatch_error(context.journal, identity_key, workflow_type, ref)
    if mismatch:
        return ResumePlan(
            identity_key=identity_key,
            ref=ref,
            workflow_type=workflow_type,
            draft=ConfigureDraft(name=str(seed_target.get("project_name_base") or "")),
            target=target,
            notice="",
            error=mismatch,
            mode="create",
            add_alternative=ref,
        )
    recovered = _create_from_request(context.request)
    if recovered is None and context.command:
        recovered = _create_from_command(context.command)
    if recovered is None:
        return ResumePlan(
            identity_key=identity_key,
            ref=ref,
            workflow_type=workflow_type,
            draft=ConfigureDraft(name=str(seed_target.get("project_name_base") or "")),
            target=target,
            notice="",
            error=_UNRECOVERABLE_CREATE_ERROR,
            mode="create",
            add_alternative=ref,
        )
    if (
        recovered.identity_key
        and identity_key
        and (recovered.identity_key.casefold() != identity_key.casefold())
    ):
        return ResumePlan(
            identity_key=identity_key,
            ref=ref,
            workflow_type=workflow_type,
            draft=ConfigureDraft(name=str(seed_target.get("project_name_base") or "")),
            target=target,
            notice="",
            error="This resume no longer matches the selected repository.",
            mode="create",
            add_alternative=ref,
        )
    notice = ""
    if not context.request and not context.command:
        notice = _MISSING_CREATE_INTENT_NOTICE
    draft = ConfigureDraft(
        name=recovered.project_name
        or str(seed_target.get("project_name_base") or row.display),
        aliases=recovered.aliases,
        setup_override=recovered.setup,  # type: ignore[arg-type]
        make_current=recovered.make_current,
    )
    return ResumePlan(
        identity_key=recovered.identity_key or identity_key,
        ref=recovered.ref or ref,
        workflow_type=workflow_type,
        draft=draft,
        target=target,
        notice=notice,
        error="",
        mode="create",
        create=recovered,
    )


def _create_mismatch_error(
    journal: Mapping[str, Any],
    identity_key: str,
    workflow_type: str,
    ref: str,
) -> str:
    stored_identity = str(journal.get("identity_key") or "")
    if (
        stored_identity
        and identity_key
        and stored_identity.casefold() != identity_key.casefold()
    ):
        return "This resume no longer matches the selected repository."
    stored_workflow = str(journal.get("workflow_type") or "")
    if stored_workflow and stored_workflow != workflow_type:
        return "This resume belongs to a different provider."
    stored_ref = str(journal.get("ref") or "")
    if stored_ref and ref and stored_ref != ref:
        return "This resume no longer matches the selected repository."
    return ""


def _create_from_request(request: Mapping[str, Any] | None) -> _CreateRecovery | None:
    """Recover create intent from the typed durable request."""
    if request is None:
        return None
    if str(request.get("mode") or "") not in ("", "create"):
        return None
    target = request.get("target")
    target_map = target if isinstance(target, Mapping) else {}
    requested = request.get("requested")
    requested_map = requested if isinstance(requested, Mapping) else {}
    options = request.get("options")
    options_map = options if isinstance(options, Mapping) else {}
    creation = request.get("creation")
    creation_map = creation if isinstance(creation, Mapping) else {}
    ref = str(target_map.get("ref") or "")
    identity_key = str(target_map.get("identity_key") or "")
    if not ref and not identity_key:
        return None
    visibility = (
        str(options_map.get("visibility") or "")
        or str(creation_map.get("visibility") or "")
        or "private"
    )
    summary = creation_map.get("summary")
    setup = str(requested_map.get("setup") or "auto")
    if setup not in {"auto", "on", "off"}:
        setup = "auto"
    aliases = tuple(
        str(item) for item in list(requested_map.get("aliases") or []) if item
    )
    return _CreateRecovery(
        owner=str(target_map.get("owner") or ""),
        raw_name=ref,
        ref=ref,
        identity_key=identity_key,
        visibility=visibility,
        options={str(key): str(value) for key, value in options_map.items()},
        summary=tuple(
            str(item) for item in (list(summary) if isinstance(summary, list) else [])
        ),
        project_name=str(requested_map.get("name") or ""),
        aliases=aliases,
        setup=setup,
        make_current=bool(requested_map.get("make_current")),
    )


def _create_from_command(command: tuple[str, ...]) -> _CreateRecovery | None:
    """Reconstruct create intent from recorded argv without executing it.

    Transport and result flags are stripped structurally; option values that
    merely equal a flag spelling stay data.
    """
    tokens = [str(item) for item in command]
    try:
        project_index = tokens.index("project")
    except ValueError:
        return None
    if (
        project_index + 1 >= len(tokens)
        or tokens[project_index + 1] != "create"
        or project_index + 2 >= len(tokens)
    ):
        return None
    ref = tokens[project_index + 2]
    if not ref or ref.startswith("-"):
        return None
    stripped = strip_transport_flags(tokens)
    requested = requested_from_argv(stripped)
    options = options_from_argv(stripped)
    visibility = str(options.get("visibility") or "private")
    setup = str(requested.get("setup") or "auto")
    if setup not in {"auto", "on", "off"}:
        setup = "auto"
    owner, separator, _name = ref.partition("/")
    return _CreateRecovery(
        owner=owner if separator else "",
        raw_name=ref,
        ref=ref,
        identity_key="",
        visibility=visibility,
        options=options,
        summary=(),
        project_name=str(requested.get("name") or ""),
        aliases=tuple(str(item) for item in list(requested.get("aliases") or [])),
        setup=setup,
        make_current=bool(requested.get("make_current")),
    )


def _mismatch_error(
    journal: Mapping[str, Any],
    identity_key: str,
    workflow_type: str,
    ref: str,
) -> str:
    mode = str(journal.get("mode") or "add")
    if mode != "add":
        return "This resume is not an add of an existing repository."
    stored_identity = str(journal.get("identity_key") or "")
    if (
        stored_identity
        and identity_key
        and stored_identity.casefold() != identity_key.casefold()
    ):
        return "This resume no longer matches the selected repository."
    stored_workflow = str(journal.get("workflow_type") or "")
    if stored_workflow and stored_workflow != workflow_type:
        return "This resume belongs to a different provider."
    stored_ref = str(journal.get("ref") or "")
    if stored_ref and ref and stored_ref != ref:
        return "This resume no longer matches the selected repository."
    return ""


def _draft_from_context(
    context: _ResumeContext,
    *,
    fallback_name: str,
) -> tuple[ConfigureDraft, str]:
    requested = _requested_from_request(context.request)
    if requested is None and context.command:
        requested = requested_from_argv(context.command)
    if requested is None:
        return ConfigureDraft(name=fallback_name), _MISSING_INTENT_NOTICE
    setup = str(requested.get("setup") or "auto")
    if setup not in {"auto", "on", "off"}:
        setup = "auto"
    aliases = tuple(str(item) for item in list(requested.get("aliases") or []) if item)
    name = str(requested.get("name") or fallback_name)
    return (
        ConfigureDraft(
            name=name,
            aliases=aliases,
            setup_override=setup,  # type: ignore[arg-type]
            make_current=bool(requested.get("make_current")),
        ),
        "",
    )


def _requested_from_request(request: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if request is None:
        return None
    raw = request.get("requested")
    if isinstance(raw, Mapping) and (
        raw.get("name")
        or raw.get("aliases")
        or raw.get("setup")
        or "make_current" in raw
    ):
        return dict(raw)
    return None


__all__ = [
    "ResumePlan",
    "load_resume_context",
    "recover_resume_intent",
]
