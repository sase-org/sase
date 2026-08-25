"""Canonical artifact references for ACE entry targets."""

from __future__ import annotations

from sase.artifact_ref_models import ArtifactRefContext
from sase.artifact_ref_operations import (
    canonicalize_artifact_ref,
    parse_artifact_ref,
)
from sase.sdd.plan_refs import PLAN_REFERENCE_KIND, PLAN_REFERENCE_PREFIX
from sase.sidecar_ref_config import sidecar_role_ref_kind


def reference_for_entry_target(
    subtab: str,
    target: tuple[str, ...],
    *,
    context: ArtifactRefContext | None = None,
    row: object | None = None,
) -> str | None:
    """Render the canonical reference represented by one ACE artifact row."""

    expected = (
        subtab.removeprefix("ref:")
        if subtab.startswith("ref:")
        else {
            "stitches": "commit",
            "commits": "commit",
            "commit": "commit",
            "chats": "chat",
            "chat": "chat",
            "bugs": "bug",
            "bug": "bug",
            "beads": "bead",
            "bead": "bead",
            "plans": "plan",
            "plan": "plan",
            "files": "file",
            "file": "file",
            "agents": "agent",
            "agent": "agent",
        }.get(subtab)
    )
    if expected is None or not target or target[0] != expected:
        return None
    try:
        if expected == "file" and len(target) == 2:
            return parse_artifact_ref(f"file:{target[1]}").rendered
        if expected == "agent" and len(target) == 2:
            entry = getattr(row, "entry", None)
            name = getattr(entry, "canonical_global_name", None) or target[1]
            return parse_artifact_ref(f"agent:{name}").rendered
        if context is None:
            return None
        if expected == "commit" and len(target) == 3:
            return parse_artifact_ref(f"commit:{target[1]}@{target[2]}").rendered
        if expected == "chat" and len(target) == 2:
            reference = canonicalize_artifact_ref(
                target[1],
                context=context,
            )
            return (
                reference
                if reference is not None and reference.startswith("chat:")
                else None
            )
        if expected == "bug" and len(target) == 3:
            project = _project_display_name(target[1], context)
            return parse_artifact_ref(f"bug:{project}#{int(target[2])}").rendered
        if expected == "bead" and len(target) == 4:
            issue = getattr(row, "issue", None)
            issue_id = getattr(issue, "id", None)
            if not isinstance(issue_id, str) or not issue_id:
                return None
            return parse_artifact_ref(f"bead:{issue_id}").rendered
        if expected == "plan" and len(target) == 4:
            return _reference_for_plan_row(target[2], row, context)
        if subtab.startswith("ref:") and len(target) == 4:
            return _reference_for_document_row(expected, target[2], row)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _reference_for_document_row(
    ref_kind: str,
    row_kind: str,
    row: object | None,
) -> str | None:
    if row is None or row_kind != "archive":
        return None
    archive = getattr(row, "archive", None)
    plan = getattr(archive, "plan", None)
    relpath = getattr(plan, "relpath", None)
    if not isinstance(relpath, str) or not relpath:
        return None
    kind = getattr(row, "ref_kind", None)
    if not isinstance(kind, str) or not kind:
        kind = ref_kind
    return parse_artifact_ref(f"{kind}:{relpath}").rendered


def _reference_for_plan_row(
    row_kind: str,
    row: object | None,
    context: ArtifactRefContext,
) -> str | None:
    if row is None:
        return None
    if row_kind in {"epic", "phase", "task"}:
        issue = getattr(row, "issue", None)
        issue_id = getattr(issue, "id", None)
        if not isinstance(issue_id, str) or not issue_id:
            return None
        return parse_artifact_ref(f"bead:{issue_id}").rendered
    if row_kind == "proposal":
        proposal = getattr(row, "proposal", None)
        plan_path = getattr(proposal, "plan_path", None)
        if not isinstance(plan_path, str) or not plan_path:
            return None
        reference = canonicalize_artifact_ref(plan_path, context=context)
        return (
            reference
            if reference is not None and reference.startswith(PLAN_REFERENCE_PREFIX)
            else None
        )
    if row_kind == "active":
        active = getattr(row, "active", None)
        document = getattr(active, "document", None)
        plan_path = getattr(document, "path", None)
        if not isinstance(plan_path, str) or not plan_path:
            return None
        reference = canonicalize_artifact_ref(plan_path, context=context)
        return (
            reference
            if reference is not None and reference.startswith(PLAN_REFERENCE_PREFIX)
            else None
        )
    if row_kind == "archive":
        archive = getattr(row, "archive", None)
        match = getattr(row, "match", None)
        if match is not None:
            archive = match
        plan = getattr(archive, "plan", None)
        relpath = getattr(plan, "relpath", None)
        role = getattr(row, "archive_role", None) or getattr(row, "role", None)
        if not isinstance(role, str) or not role:
            plan_kind = getattr(plan, "kind", None)
            role = (
                plan_kind
                if isinstance(plan_kind, str)
                and plan_kind not in {"tale", "epic", "prompt", "local"}
                else PLAN_REFERENCE_KIND
            )
        if not isinstance(relpath, str) or not relpath:
            return None
        return parse_artifact_ref(f"{sidecar_role_ref_kind(role)}:{relpath}").rendered
    return None


def design_reference_for_plan_row(row: object | None) -> str | None:
    """Return the owning bead's design reference for a plan document row."""

    bead_link = getattr(row, "bead_link", None)
    design = getattr(bead_link, "reference", None)
    if not isinstance(design, str) or not design:
        # Preserve compatibility for callers holding a Beads-era row model.
        issue = getattr(row, "issue", None)
        design = getattr(issue, "design", None)
    if not isinstance(design, str) or not design:
        return None
    try:
        parsed = parse_artifact_ref(design)
    except ValueError:
        return None
    return parsed.rendered if parsed.kind == PLAN_REFERENCE_KIND else None


def reference_for_agent_name(name: str) -> str | None:
    """Render one Agents-tab agent name with durable global provenance."""

    if not name:
        return None
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_lookup_candidates,
        globalize_owned_agent_name,
    )

    identity = AgentIdentitySnapshot.current()
    candidates = current_owner_agent_name_lookup_candidates(name, identity)
    global_name = globalize_owned_agent_name(name, identity)
    durable_name = global_name if global_name in candidates else name
    try:
        return parse_artifact_ref(f"agent:{durable_name}").rendered
    except ValueError:
        return None


def _project_display_name(
    project_ref: str,
    context: ArtifactRefContext,
) -> str:
    folded = project_ref.casefold()
    for project in context.projects:
        if (
            project.name.casefold() == folded
            or project.key.casefold() == folded
            or any(alias.casefold() == folded for alias in project.aliases)
        ):
            return project.name
    return project_ref


__all__ = [
    "design_reference_for_plan_row",
    "reference_for_agent_name",
    "reference_for_entry_target",
]
