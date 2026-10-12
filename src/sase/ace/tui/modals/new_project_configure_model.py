"""Textual-free Configure-stage models for the New Project wizard.

These helpers turn one onboarding plan document plus the editable draft into
the Project card and the SASE setup card. They import no Textual modules so
the later stage widgets can share them with tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.project_onboarding.planning import build_plan_document

SetupOverride = Literal["auto", "on", "off"]
IdentityStatus = Literal["unique", "taken", "invalid"]

_TAKEN_CODES = frozenset({"name_taken", "alias_taken"})
_BARE_GIT_WORKFLOW = "git"


@dataclass(frozen=True, slots=True)
class ConfigureDraft:
    """Editable Configure-stage values seeded from the selected source row."""

    name: str = ""
    aliases: tuple[str, ...] = ()
    setup_override: SetupOverride = "auto"
    make_current: bool = False

    def to_requested(self) -> dict[str, Any]:
        """Return the ``requested`` intent the planner consumes."""
        override = self.setup_override
        setup = override if override in ("auto", "on", "off") else "auto"
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "setup": setup,
            "make_current": self.make_current,
        }


@dataclass(frozen=True, slots=True)
class ProjectCard:
    """Render-ready Project card values."""

    name: str
    aliases: tuple[str, ...]
    key: str
    accent: str
    checkout_dir: str
    will_clone: bool
    state: str
    reenable_note: str | None

    @property
    def checkout_line(self) -> str:
        """Describe the checkout and whether applying will clone it."""
        if not self.checkout_dir:
            return "Checkout not resolved yet."
        if self.will_clone:
            return f"Will clone into {self.checkout_dir}."
        return f"Uses the existing checkout at {self.checkout_dir}."


@dataclass(frozen=True, slots=True)
class SetupCard:
    """Render-ready SASE setup card values."""

    show_checkbox: bool
    checked: bool
    reason: str
    reason_style: str
    follow_up: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class IdentityCheck:
    """Uniqueness verdict for the draft name and aliases."""

    status: IdentityStatus
    reason: str


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _steps(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = document.get("steps")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _step_detail(document: Mapping[str, Any], step_id: str) -> str:
    for step in _steps(document):
        if str(step.get("id") or "") == step_id:
            return str(step.get("detail") or "")
    return ""


def build_project_card(
    document: Mapping[str, Any],
    draft: ConfigureDraft,
) -> ProjectCard:
    """Build the Project card from *document* and the editable *draft*."""
    project = _mapping(document.get("project"))
    target = _mapping(document.get("target"))
    checkout_dir = str(target.get("checkout_dir") or "")
    will_clone = False
    for step in _steps(document):
        if str(step.get("id") or "") == "checkout":
            will_clone = (
                str(step.get("state") or "") == "pending"
                and str(step.get("operation") or "") == "create"
            )
            break
    state = str(project.get("state") or "enabled")
    reenable_note = None
    if state == "disabled":
        reenable_note = "Adding re-enables this project."
    return ProjectCard(
        name=draft.name,
        aliases=tuple(draft.aliases),
        key=str(project.get("key") or ""),
        accent=str(project.get("accent") or ""),
        checkout_dir=checkout_dir,
        will_clone=will_clone,
        state=state,
        reenable_note=reenable_note,
    )


def build_setup_card(
    document: Mapping[str, Any],
    draft: ConfigureDraft,
) -> SetupCard:
    """Build the SASE setup card from *document* and the editable *draft*."""
    setup = _mapping(document.get("setup"))
    target = _mapping(document.get("target"))
    provider = _mapping(document.get("provider"))
    code = str(setup.get("code") or "")
    reason = str(setup.get("reason") or "")
    can_push = target.get("can_push")
    sase_managed = target.get("sase_managed")
    is_bare_git = str(provider.get("workflow_type") or "") == _BARE_GIT_WORKFLOW
    if sase_managed is True or code == "already_managed":
        note = None if is_bare_git else "Sidecars connect on first launch."
        return SetupCard(
            show_checkbox=False,
            checked=False,
            reason=reason,
            reason_style="",
            follow_up=None,
            note=note,
        )
    if can_push is False:
        return SetupCard(
            show_checkbox=True,
            checked=False,
            reason=reason,
            reason_style="amber",
            follow_up="sase init -M",
            note=None,
        )
    override = draft.setup_override
    if override == "on":
        checked = True
    elif override == "off":
        checked = False
    else:
        checked = bool(setup.get("enabled"))
    note = _step_detail(document, "manage") if checked else None
    return SetupCard(
        show_checkbox=True,
        checked=checked,
        reason=reason,
        reason_style="",
        follow_up=None,
        note=note or None,
    )


def check_identity(document: Mapping[str, Any]) -> IdentityCheck:
    """Map the planner's identity blockers to a uniqueness verdict.

    ``taken`` names the project that holds the name or alias through the
    planner's own message text. Anything without an identity blocker is
    ``unique``.
    """
    blockers = document.get("blockers")
    items = list(blockers) if isinstance(blockers, list) else []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("code") or "").startswith("invalid"):
            return IdentityCheck(
                status="invalid", reason=str(item.get("message") or "")
            )
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("code") or "") in _TAKEN_CODES:
            return IdentityCheck(status="taken", reason=str(item.get("message") or ""))
    return IdentityCheck(status="unique", reason="")


def validate_draft(
    target: Mapping[str, Any],
    draft: ConfigureDraft,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Re-plan locally for *draft* against project *records* only.

    Callers pass the records facts in; no fact gathering or provider hook
    runs here. Identity blockers (``name_taken``, ``alias_taken``,
    ``invalid_*``) surface on the returned document for :func:`check_identity`.
    """
    request = {
        "mode": "add",
        "actor": "human",
        "target": dict(target),
        "requested": draft.to_requested(),
    }
    facts = {"projects": [dict(record) for record in records]}
    return build_plan_document(request, facts=facts)


def plan_configure_display(
    target: Mapping[str, Any],
    draft: ConfigureDraft,
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the Configure display plan from observed *facts*.

    Records-only :func:`validate_draft` stays the identity-only helper.
    Display planning threads Source-cache and inventory snapshots through
    the existing ``build_plan_document(..., facts=...)`` contract.
    """
    request = {
        "mode": "add",
        "actor": "human",
        "target": dict(target),
        "requested": draft.to_requested(),
    }
    return build_plan_document(request, facts=dict(facts))


__all__ = [
    "ConfigureDraft",
    "IdentityCheck",
    "IdentityStatus",
    "ProjectCard",
    "SetupCard",
    "SetupOverride",
    "build_project_card",
    "build_setup_card",
    "check_identity",
    "plan_configure_display",
    "validate_draft",
]
