"""Pure create-draft helpers for the New Project wizard.

Owner and visibility defaults, name normalization, probe classification,
checkout observation, and plan assembly run without Textual. Provider
``parse_repo_ref`` is the only workspace-provider call on this path;
``describe_repo_creation`` and probes stay in the flow mixins.
"""

from __future__ import annotations

from collections.abc import Container, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase import workspace_provider
from sase.core.project_onboarding_facade import evaluate_repo_creation_form
from sase.project_onboarding.discovery import (
    identity_for_origin,
    read_git_origin_url,
    resolve_git_dir,
)
from sase.project_onboarding.planning import build_plan_document
from sase.workspace_provider._hookspec import RepoCreationForm

from ._new_project_create_shared import BARE_GIT_WORKFLOW
from .new_project_configure_facts import (
    matching_project_record,
    remote_facts_from_probe,
)
from .new_project_configure_model import ConfigureDraft
from .new_project_create_types import (
    FIRST_USE_VISIBILITY,
    CreateAvailabilityInfo,
    CreateIdentity,
)


def default_create_owner(
    owners: Sequence[str],
    *,
    account: str = "",
    last_owner: str = "",
    current_project_owner: str = "",
    workflow_type: str = "",
    unavailable: Container[str] = (),
) -> str:
    """Pick the create namespace owner from defaults.

    Namespace owners are deduplicated with ``account`` appended (bare git
    never invents an account and supports an empty namespace). Preference is
    the still-valid last-used owner, then the current project's owner for
    that provider, then the account, then the first available namespace.
    """
    ordered = [name for name in dict.fromkeys(owners) if name]
    if workflow_type != BARE_GIT_WORKFLOW and account and account not in ordered:
        ordered.append(account)
    available = [name for name in ordered if name not in unavailable]
    if workflow_type != BARE_GIT_WORKFLOW:
        candidates = (last_owner, current_project_owner, account)
    else:
        candidates = (last_owner, current_project_owner, "")
    for candidate in candidates:
        if candidate and candidate in available:
            return candidate
    return available[0] if available else ""


def supported_create_visibilities(form: RepoCreationForm | None) -> tuple[str, ...]:
    """Return the wizard-level visibilities the provider form offers.

    A provider ``visibility`` choice field declares the supported values.
    Without one, creation offers private and public.
    """
    if form is not None:
        for field in form.fields:
            if field.name == "visibility" and field.kind == "choice" and field.choices:
                values = tuple(choice.value for choice in field.choices if choice.value)
                if values:
                    return values
    return ("private", "public")


def default_create_visibility(
    *,
    owner: str,
    supported: Sequence[str],
    last_visibility: Mapping[str, str],
    unavailable: Container[str] = (),
) -> str:
    """Pick the creation visibility for *owner*.

    First use defaults to Private; otherwise the last successful choice for
    that owner wins when it is still supported and enabled.
    """
    _ = owner
    options = [value for value in supported if value and value not in unavailable]
    if not options:
        return FIRST_USE_VISIBILITY
    last = last_visibility.get(owner, "")
    if last and last in options:
        return last
    if FIRST_USE_VISIBILITY in options:
        return FIRST_USE_VISIBILITY
    return options[0]


def normalize_create_name(
    workflow_type: str, owner: str, raw_name: str
) -> CreateIdentity:
    """Normalize the typed repository name without I/O.

    This is pure ``parse_repo_ref``: no subprocess, no network, no disk
    reads. The provider's canonical identity, checkout path, key/name bases,
    and web URL are preserved verbatim.
    """
    raw = raw_name.strip()
    if not raw:
        return CreateIdentity(valid=False, error="Enter a repository name.")
    if workflow_type == BARE_GIT_WORKFLOW or not owner or "/" in raw:
        text = raw
    else:
        text = f"{owner}/{raw}"
    try:
        parsed = workspace_provider.parse_repo_ref(workflow_type, text)
    except Exception:
        parsed = None
    if parsed is None:
        return CreateIdentity(
            valid=False, error=f"Name {raw!r} is not valid for this provider."
        )
    canonical = parsed.ref or text
    return CreateIdentity(
        valid=True,
        canonical_ref=canonical,
        identity_key=parsed.identity_key,
        display=parsed.display or canonical,
        host=parsed.host,
        owner=parsed.owner,
        name=parsed.name,
        checkout_dir=parsed.checkout_dir,
        project_key_base=parsed.project_key_base,
        project_name_base=parsed.project_name_base,
        web_url=parsed.web_url,
        normalized_from=parsed.normalized_from or (text if canonical != text else ""),
    )


def classify_create_probe(probe: Any | None) -> CreateAvailabilityInfo:
    """Map a provider probe to a create availability verdict.

    ``not_found`` is the only available state; ``found`` is taken and offers
    the explicit add-instead action. Unknown results and errors never become
    available.
    """
    if probe is None:
        return CreateAvailabilityInfo(
            status="unavailable",
            reason="The provider did not return a repository check.",
        )
    status = str(getattr(probe, "status", "") or "unavailable")
    if status == "not_found":
        return CreateAvailabilityInfo(status="available", reason="Name is available.")
    if status == "found":
        return CreateAvailabilityInfo(
            status="taken",
            reason="A repository with this name already exists.",
        )
    message = str(getattr(probe, "message", "") or "")
    error_kind = str(getattr(probe, "error_kind", "") or "")
    detail = message or f"Repository check is unavailable ({error_kind or 'unknown'})."
    return CreateAvailabilityInfo(status="unavailable", reason=detail)


def create_identity_verdict(document: Mapping[str, Any]) -> tuple[bool, str]:
    """Map plan identity blockers to a Review verdict.

    ``(True, "")`` means the draft name and aliases are unique; otherwise the
    reason names the holder through the planner's own message text.
    """
    blockers = document.get("blockers")
    items = list(blockers) if isinstance(blockers, list) else []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code") or "")
        if code.startswith("invalid"):
            return False, str(item.get("message") or "")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("code") or "") in {"name_taken", "alias_taken"}:
            return False, str(item.get("message") or "")
    return True, ""


def probe_result_current(
    *,
    generation: int,
    expected_generation: int,
    mode: str,
    expected_mode: str,
    owner: str,
    expected_owner: str,
    identity_key: str,
    expected_identity_key: str,
) -> bool:
    """Discard stale owner/probe completions that lost a generation race."""
    return (
        generation == expected_generation
        and mode == expected_mode
        and owner == expected_owner
        and identity_key == expected_identity_key
    )


def observe_create_checkout(
    checkout_dir: str, *, identity_key: str, workflow_type: str
) -> dict[str, Any]:
    """Observe one checkout path with pure filesystem reads.

    No subprocess runs here: existence, emptiness, git-dir resolution, and
    origin comparison are all file reads. Matching checkouts follow planner
    policy downstream; occupied unrelated paths report ``mismatch``/``not_git``
    so the planner blocks instead of removing or resetting anything.
    """
    facts: dict[str, Any] = {
        "state": "absent",
        "origin_url": "",
        "config_dirty": False,
        "on_default_branch": None,
    }
    if not checkout_dir.strip():
        return facts
    path = Path(checkout_dir).expanduser()
    try:
        exists = path.exists()
    except OSError:
        return facts
    if not exists:
        return facts
    if path.is_file():
        facts["state"] = "not_git"
        return facts
    try:
        is_empty = not any(path.iterdir())
    except OSError:
        return facts
    if is_empty:
        facts["state"] = "empty_dir"
        return facts
    if resolve_git_dir(path) is None:
        facts["state"] = "not_git"
        return facts
    origin = read_git_origin_url(str(path))
    facts["origin_url"] = origin
    wanted = identity_key.casefold()
    found = ""
    if origin:
        try:
            parsed = workspace_provider.parse_repo_ref(workflow_type, origin)
        except Exception:
            parsed = None
        if parsed is not None and parsed.identity_key:
            found = parsed.identity_key.casefold()
        else:
            found = identity_for_origin(origin).casefold()
    facts["state"] = "matching" if wanted and found == wanted else "mismatch"
    return facts


def assemble_create_facts(
    *,
    records: Sequence[Mapping[str, Any]],
    probe: Any | None,
    identity_key: str,
    checkout: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build create planner facts from observed state only.

    Mirrors the add-path adapter but takes an explicitly observed checkout
    instead of a Source row classification.
    """
    facts: dict[str, Any] = {
        "projects": [
            {
                "key": str(record.get("key") or ""),
                "name": str(record.get("name") or ""),
                "aliases": list(record.get("aliases") or []),
                "state": str(record.get("state") or "enabled"),
            }
            for record in records
        ]
    }
    remote = remote_facts_from_probe(probe)
    if remote is not None:
        facts["remote"] = remote
    matching = matching_project_record(records, identity_key)
    if matching is not None:
        facts["record"] = {
            "key": str(matching.get("key") or ""),
            "name": str(matching.get("name") or ""),
            "aliases": list(matching.get("aliases") or []),
            "state": str(matching.get("state") or "enabled"),
        }
    if checkout is not None:
        facts["checkout"] = dict(checkout)
    return facts


def lenient_effective_options(
    form: RepoCreationForm | None, values: Mapping[str, str]
) -> dict[str, str]:
    """Evaluate provider values leniently and return canonical options.

    Pure Rust evaluation; safe to run directly on the pump. Unavailable
    control values are omitted by the core result, never by a second Python
    constraint engine.
    """
    if form is None:
        return {}
    try:
        evaluation = evaluate_repo_creation_form(
            asdict(form),
            {str(key): str(value) for key, value in dict(values).items()},
            "lenient",
        )
    except Exception:
        return {}
    effective = evaluation.get("effective_options")
    if not isinstance(effective, Mapping):
        return {}
    return {str(key): str(value) for key, value in effective.items()}


def build_create_plan_request(
    *,
    identity: CreateIdentity,
    workflow_type: str,
    provider_display: str = "",
    storage_policy: str = "",
    project: ConfigureDraft,
    visibility: str,
    summary: Sequence[str] = (),
    effective_options: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the complete mode=create plan request from draft state.

    Bare-git path options are reflected in the target checkout instead of
    silently displaying unrelated default paths.
    """
    effective = {
        str(key): str(value) for key, value in dict(effective_options or {}).items()
    }
    target: dict[str, Any] = {
        "workflow_type": workflow_type,
        "provider_display": provider_display,
        "identity_key": identity.identity_key,
        "ref": identity.canonical_ref,
        "display": identity.display or identity.canonical_ref,
        "host": identity.host,
        "owner": identity.owner,
        "name": identity.name,
        "web_url": identity.web_url,
        "checkout_dir": identity.checkout_dir,
        "project_key_base": identity.project_key_base,
        "project_name_base": identity.project_name_base,
        "storage_policy": storage_policy,
    }
    checkout_override = effective.get("checkout_dir", "").strip()
    if checkout_override:
        target["checkout_dir"] = checkout_override
    return {
        "mode": "create",
        "actor": "human",
        "target": target,
        "requested": project.to_requested(),
        "creation": {
            "visibility": visibility,
            "summary": [str(item) for item in summary],
        },
        "options": effective,
    }


def plan_create_display(
    *,
    identity: CreateIdentity,
    workflow_type: str,
    provider_display: str = "",
    storage_policy: str = "",
    project: ConfigureDraft,
    visibility: str,
    summary: Sequence[str] = (),
    effective_options: Mapping[str, str] | None = None,
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the create Configure display plan from explicitly observed facts."""
    request = build_create_plan_request(
        identity=identity,
        workflow_type=workflow_type,
        provider_display=provider_display,
        storage_policy=storage_policy,
        project=project,
        visibility=visibility,
        summary=summary,
        effective_options=effective_options,
    )
    return build_plan_document(request, facts=dict(facts))


def add_instead_seed(
    *,
    identity: CreateIdentity,
    workflow_type: str,
    provider_display: str = "",
    storage_policy: str = "",
) -> dict[str, Any]:
    """Seed an existing-repo Configure target from a taken create identity.

    Only the explicit add-instead action calls this; typing never converts a
    taken remote into an add.
    """
    return {
        "workflow_type": workflow_type,
        "provider_display": provider_display,
        "storage_policy": storage_policy,
        "ref": identity.canonical_ref,
        "identity_key": identity.identity_key,
        "display": identity.display or identity.canonical_ref,
        "host": identity.host,
        "owner": identity.owner,
        "name": identity.name,
        "web_url": identity.web_url,
        "checkout_dir": identity.checkout_dir,
        "project_key_base": identity.project_key_base,
        "project_name_base": identity.project_name_base,
    }


def create_review_request(
    *,
    identity: CreateIdentity,
    workflow_type: str,
    provider_display: str = "",
    storage_policy: str = "",
    project: ConfigureDraft,
    visibility: str,
    summary: Sequence[str] = (),
    effective_options: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Preserve the complete create intent for Review and durable apply.

    Mode, human UI intent, canonical target, project ``requested`` values,
    provider ``options``, and creation visibility/summary travel together
    through Back, Review, durable operation storage, and retry.
    """
    return build_create_plan_request(
        identity=identity,
        workflow_type=workflow_type,
        provider_display=provider_display,
        storage_policy=storage_policy,
        project=project,
        visibility=visibility,
        summary=summary,
        effective_options=effective_options,
    )


__all__ = [
    "add_instead_seed",
    "assemble_create_facts",
    "build_create_plan_request",
    "classify_create_probe",
    "create_identity_verdict",
    "create_review_request",
    "default_create_owner",
    "default_create_visibility",
    "lenient_effective_options",
    "normalize_create_name",
    "observe_create_checkout",
    "plan_create_display",
    "probe_result_current",
    "supported_create_visibilities",
]
