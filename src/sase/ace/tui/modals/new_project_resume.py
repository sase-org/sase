"""Recover a failed add-existing resume into a Reviewable draft.

I/O stays in :func:`load_resume_context`. Recovery never executes a stored
command or copies proc transport or result flags into a new submission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.ops import OperationIOError, read_operation_request
from sase.procs import get_proc
from sase.procs.runtime import proc_operation_request_path
from sase.project_onboarding.journal import lookup_journal

from .new_project_configure_model import ConfigureDraft
from .new_project_review_model import requested_from_argv
from .new_project_source_model import SourceRow

_MISSING_INTENT_NOTICE = (
    "Previous add choices were not recovered. Review this plan before applying."
)


@dataclass(frozen=True, slots=True)
class ResumeContext:
    """Durable journal plus optional proc request/command evidence."""

    journal: dict[str, Any] | None
    request: dict[str, Any] | None
    command: tuple[str, ...]


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


def load_resume_context(identity_key: str) -> ResumeContext:
    """Read the journal and, when present, the proc request sidecar."""
    journal = lookup_journal(identity_key)
    request: dict[str, Any] | None = None
    command: tuple[str, ...] = ()
    proc_id = str((journal or {}).get("proc_id") or "")
    if not proc_id:
        return ResumeContext(journal=journal, request=None, command=())
    proc = get_proc(proc_id)
    if proc is not None:
        raw_command = proc.command or proc.argv
        command = tuple(str(item) for item in raw_command)
    try:
        loaded = read_operation_request(
            proc_operation_request_path(proc_id),
            expected_operation="project.add",
        )
    except (OSError, OperationIOError, ValueError):
        loaded = None
    if loaded is not None and isinstance(loaded.payload, Mapping):
        request = dict(loaded.payload)
    return ResumeContext(journal=journal, request=request, command=command)


def recover_resume_intent(
    *,
    row: SourceRow,
    workflow_type: str,
    context: ResumeContext,
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
    if journal is not None:
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
    context: ResumeContext,
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
    "ResumeContext",
    "ResumePlan",
    "load_resume_context",
    "recover_resume_intent",
]
