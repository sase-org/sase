"""Create draft and Configure stage for new repositories.

This module implements the ``create-configure`` phase: the frozen create draft,
owner and visibility defaults, pure name normalization, debounced off-thread
availability and checkout checks, Rust identity previews, and the explicit
add-instead transition.

The stage is reachable from test harnesses only. No production Source
affordance selects create Configure yet; the ``recovery-entry`` phase adds the
pinned Create row. The normal add wizard keeps working unchanged.

Threading rules: pure Rust evaluation runs directly on the pump. Provider
``describe_repo_creation`` calls, probes, checkout observations, and
plan-envelope I/O run off-thread in the flow mixin. Typing never starts a
subprocess or provider network call synchronously.
"""

from __future__ import annotations

import asyncio
from collections.abc import Container, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from dataclasses import field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message

from sase import workspace_provider
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.core.project_onboarding_facade import evaluate_repo_creation_form

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase

    from .new_project_source_model import SourceRow
    from .new_project_state import NewProjectStateMachine
    from sase.project_onboarding import Preferences
else:
    _MixinBase = object
from sase.project_onboarding.discovery import (
    identity_for_origin,
    read_git_origin_url,
    resolve_git_dir,
)
from sase.project_onboarding.planning import build_plan_document
from sase.workspace_provider._hookspec import RepoCreationForm

from .new_project_configure_facts import (
    matching_project_record,
    remote_facts_from_probe,
)
from .new_project_configure_model import ConfigureDraft

_CREATE_TASKS = "_new_project_create_tasks"
AVAILABILITY_DEBOUNCE_SECONDS = 0.3
FIRST_USE_VISIBILITY = "private"
_BARE_GIT_WORKFLOW = "git"

CreateAvailability = Literal["checking", "available", "taken", "unavailable"]
CreateFormStatus = Literal["loading", "ready", "unavailable"]


@dataclass(frozen=True, slots=True)
class CreateAvailabilityInfo:
    """Remote-name verdict for the canonical create target."""

    status: CreateAvailability
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CreateIdentity:
    """Pure ``parse_repo_ref`` normalization of the typed create target."""

    valid: bool
    error: str = ""
    canonical_ref: str = ""
    identity_key: str = ""
    display: str = ""
    host: str = ""
    owner: str = ""
    name: str = ""
    checkout_dir: str = ""
    project_key_base: str = ""
    project_name_base: str = ""
    web_url: str = ""
    normalized_from: str = ""

    @property
    def normalized_label(self) -> str:
        """Render ``raw → canonical`` when normalization changed the text."""
        if not self.valid or not self.normalized_from:
            return ""
        return f"{self.normalized_from} → {self.canonical_ref}"


@dataclass(frozen=True, slots=True)
class CreateDraft:
    """Editable create-Configure values for one namespace owner.

    Provider form README and other option defaults stay owned by the provider
    form widget; this draft only carries the raw value map across navigation.
    SASE setup stays ``auto`` so the core create-auto recommendation applies.
    """

    owner: str = ""
    raw_name: str = ""
    visibility: str = FIRST_USE_VISIBILITY
    provider_values: dict[str, str] = dc_field(default_factory=dict)
    project: ConfigureDraft = dc_field(default_factory=ConfigureDraft)
    project_name_edited: bool = False


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
    if workflow_type != _BARE_GIT_WORKFLOW and account and account not in ordered:
        ordered.append(account)
    available = [name for name in ordered if name not in unavailable]
    if workflow_type != _BARE_GIT_WORKFLOW:
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
    if workflow_type == _BARE_GIT_WORKFLOW or not owner or "/" in raw:
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


async def _describe_form_off_thread(
    workflow_type: str, namespace: str
) -> RepoCreationForm | None:
    """Fetch one provider creation form outside the Textual pump."""
    return await asyncio.to_thread(
        workspace_provider.describe_repo_creation, workflow_type, namespace
    )


class NewProjectCreateConfigure(VerticalScroll):
    """Configure stage for creating a new provider repository.

    The owner button cycles namespaces, the name field normalizes on every
    edit, and the provider form supplies creation options. Project cards are
    shared with the add path through the same model helpers.
    """

    class DraftChanged(Message):
        """The editable create draft changed and needs a debounced refresh."""

        def __init__(self, draft: CreateDraft) -> None:
            super().__init__()
            self.draft = draft

    class AvailabilityRequested(Message):
        """The debounce timer expired; the parent should schedule a check."""

    class OwnerSelected(Message):
        """The user switched the create namespace owner."""

        def __init__(self, owner: str) -> None:
            super().__init__()
            self.owner = owner

    class ReviewRequested(Message):
        """The user asked to continue to Review with the create intent."""

    class BackRequested(Message):
        """The user asked to return to Source."""

    class AddInsteadRequested(Message):
        """The user chose to add the taken canonical ref instead."""

        def __init__(self, identity: CreateIdentity) -> None:
            super().__init__()
            self.identity = identity

    BINDINGS = [
        ("b", "back", "Back"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workflow_type = ""
        self._owners: tuple[str, ...] = ()
        self._supported_visibilities: tuple[str, ...] = ("private", "public")
        self._draft = CreateDraft()
        self._identity = CreateIdentity(valid=False, error="Enter a repository name.")
        self._availability = CreateAvailabilityInfo(status="checking")
        self._form: RepoCreationForm | None = None
        self._form_status: CreateFormStatus = "loading"
        self._form_message = ""
        self._form_remedy: tuple[str, ...] = ()
        self._form_widget_for: RepoCreationForm | None = None
        self._document: dict[str, Any] = {}
        self._identity_check_valid = False
        self._identity_check_reason = "Building the local plan…"
        self._confirmable = False
        self._check_timer: Any | None = None
        self._check_due = False
        self._ignore_input_values: dict[str, str] = {}
        self._ignore_checkbox_values: dict[str, bool] = {}

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical as _Vertical
        from textual.containers import Horizontal as _Horizontal
        from textual.widgets import Button as _Button
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Input as _Input
        from textual.widgets import Static as _Static

        with _Vertical(id="new-project-create-target-card", classes="new-project-card"):
            yield _Static("NEW REPOSITORY", classes="new-project-card-heading")
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Owner", classes="new-project-field-label")
                yield _Button("…", id="new-project-create-owner")
            yield _Static("", id="new-project-create-capability", markup=False)
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Name", classes="new-project-field-label")
                yield _Input(
                    placeholder="Repository name",
                    id="new-project-create-name",
                )
            yield _Static("", id="new-project-create-normalized", markup=False)
            yield _Static("", id="new-project-create-availability", markup=False)
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Visibility", classes="new-project-field-label")
                yield _Button("private", id="new-project-create-visibility")
        with _Vertical(
            id="new-project-create-options-card", classes="new-project-card"
        ):
            yield _Static("OPTIONS", classes="new-project-card-heading")
            with _Vertical(id="new-project-create-form-slot"):
                yield _Static(
                    "◌ Loading provider options…",
                    id="new-project-create-form-status",
                    markup=False,
                )
        with _Vertical(
            id="new-project-create-project-card", classes="new-project-card"
        ):
            yield _Static("PROJECT", classes="new-project-card-heading")
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Name", classes="new-project-field-label")
                yield _Input(
                    placeholder="Project name",
                    id="new-project-create-project-name",
                )
            with _Horizontal(classes="new-project-configure-field"):
                yield _Static("Aliases", classes="new-project-field-label")
                yield _Input(
                    placeholder="Comma-separated aliases (optional)",
                    id="new-project-create-project-aliases",
                )
            yield _Static("", id="new-project-create-checkout", markup=False)
            yield _Static("", id="new-project-create-identity", markup=False)
            yield _Static("", id="new-project-create-enabled", markup=False)
        with _Vertical(id="new-project-create-setup-card", classes="new-project-card"):
            yield _Static("SASE SETUP", classes="new-project-card-heading")
            with _Horizontal(id="new-project-create-setup-toggle-row"):
                yield _Checkbox(
                    "Set up SASE in this repository",
                    id="new-project-create-setup",
                )
            yield _Static("", id="new-project-create-setup-reason", markup=False)
            yield _Static("", id="new-project-create-setup-note", markup=False)
            yield _Checkbox(
                "Make this the current project after creating",
                id="new-project-create-current",
            )
        with _Horizontal(id="new-project-create-actions"):
            yield _Button("‹ Source", id="new-project-create-back")
            yield _Button(
                "Add existing instead",
                id="new-project-create-add-instead",
            )
            yield _Static("", id="new-project-create-status", markup=False)
            yield _Button("Review ›", id="new-project-create-review")

    def on_unmount(self) -> None:
        """Cancel the pending availability timer with the widget."""
        self.cancel_pending()

    def cancel_pending(self) -> None:
        """Stop the debounce timer without firing it."""
        if self._check_timer is not None:
            self._check_timer.stop()
            self._check_timer = None
        self._check_due = False

    def request_check(self) -> None:
        """Schedule the standard availability debounce after a user edit."""
        self._check_due = False
        if self._check_timer is not None:
            self._check_timer.stop()
        self._check_timer = self.set_timer(
            AVAILABILITY_DEBOUNCE_SECONDS, self._check_timer_fired
        )

    def _check_timer_fired(self) -> None:
        self._check_due = True
        self.post_message(self.AvailabilityRequested())

    @property
    def draft(self) -> CreateDraft:
        """Current editable create draft."""
        return self._draft

    @property
    def identity(self) -> CreateIdentity:
        """Latest pure normalization of the typed target."""
        return self._identity

    def set_context(
        self,
        *,
        workflow_type: str,
        owners: Sequence[str],
        supported_visibilities: Sequence[str],
        draft: CreateDraft,
        identity: CreateIdentity,
        availability: CreateAvailabilityInfo,
        form: RepoCreationForm | None,
        form_status: CreateFormStatus,
        form_message: str = "",
        form_remedy: Sequence[str] = (),
        document: Mapping[str, Any] | None = None,
        identity_valid: bool = False,
        identity_reason: str = "",
        confirmable: bool = False,
    ) -> None:
        """Repaint the stage from flow-owned state, preserving focus text."""
        self._workflow_type = workflow_type
        self._owners = tuple(owners)
        self._supported_visibilities = tuple(supported_visibilities) or (
            "private",
            "public",
        )
        self._draft = draft
        self._identity = identity
        self._availability = availability
        self._form = form
        self._form_status = form_status
        self._form_message = form_message
        self._form_remedy = tuple(form_remedy)
        if document is not None:
            self._document = dict(document)
        self._identity_check_valid = identity_valid
        self._identity_check_reason = identity_reason
        self._confirmable = confirmable and identity.valid
        if self.is_mounted:
            self._sync_form()

    def mark_check_pending(self) -> None:
        """Invalidate availability immediately on any target change."""
        self._availability = CreateAvailabilityInfo(status="checking")
        self._confirmable = False
        if self.is_mounted:
            self._render_target()
            self._render_actions()

    def apply_check(
        self,
        *,
        availability: CreateAvailabilityInfo,
        document: Mapping[str, Any],
        identity_valid: bool,
        identity_reason: str,
        confirmable: bool,
    ) -> None:
        """Paint the latest off-thread availability and local plan."""
        self._availability = availability
        self._document = dict(document)
        self._identity_check_valid = identity_valid
        self._identity_check_reason = identity_reason
        self._confirmable = confirmable and self._identity.valid
        if self.is_mounted:
            self._render_target()
            self._render_project()
            self._render_setup()
            self._render_actions()

    def focus_name(self) -> None:
        """Focus the repository name editor when the stage opens."""
        from textual.widgets import Input as _Input

        self.query_one("#new-project-create-name", _Input).focus()

    def focused_input(self) -> Any | None:
        """Return the active inline editor, if any."""
        from textual.widgets import Input as _Input

        focused = self.screen.focused
        if isinstance(focused, _Input) and focused.id in {
            "new-project-create-name",
            "new-project-create-project-name",
            "new-project-create-project-aliases",
        }:
            return focused
        return None

    def blur_input(self) -> bool:
        """Blur an active text field; return whether a field was blurred."""
        focused = self.focused_input()
        if focused is None:
            return False
        focused.blur()
        return True

    def on_input_changed(self, event: Any) -> None:
        """Normalize the repository name on every edit; track project edits."""
        from textual.widgets import Input as _Input

        if not isinstance(event, _Input.Changed):
            return
        control_id = event.input.id or ""
        if control_id not in {
            "new-project-create-name",
            "new-project-create-project-name",
            "new-project-create-project-aliases",
        }:
            return
        if self._ignore_input_values.get(control_id) == event.value:
            self._ignore_input_values.pop(control_id, None)
            return
        if control_id == "new-project-create-name":
            self._rename_target(event.value)
        elif control_id == "new-project-create-project-name":
            project = replace(
                self._draft.project,
                name=event.value,
            )
            self._draft = replace(
                self._draft, project=project, project_name_edited=True
            )
            self.post_message(self.DraftChanged(self._draft))
            self.request_check()
        else:
            aliases = tuple(
                item.strip() for item in event.value.split(",") if item.strip()
            )
            project = replace(self._draft.project, aliases=aliases)
            self._draft = replace(self._draft, project=project)
            self.post_message(self.DraftChanged(self._draft))
            self.request_check()

    def _rename_target(self, raw_name: str) -> None:
        """Apply pure normalization and follow it with the project name."""
        identity = normalize_create_name(
            self._workflow_type, self._draft.owner, raw_name
        )
        draft = replace(self._draft, raw_name=raw_name)
        if not draft.project_name_edited:
            base = identity.project_name_base or identity.name
            if base and base != draft.project.name:
                draft = replace(draft, project=replace(draft.project, name=base))
        self._draft = draft
        self._identity = identity
        self.mark_check_pending()
        if self.is_mounted:
            self._render_target()
            self._sync_project_inputs()
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_checkbox_changed(self, event: Any) -> None:
        """Track setup and make-current toggles."""
        from textual.widgets import Checkbox as _Checkbox

        if not isinstance(event, _Checkbox.Changed):
            return
        checkbox_id = event.checkbox.id or ""
        if checkbox_id not in {
            "new-project-create-setup",
            "new-project-create-current",
        }:
            return
        if self._ignore_checkbox_values.get(checkbox_id) == event.value:
            self._ignore_checkbox_values.pop(checkbox_id, None)
            return
        if checkbox_id == "new-project-create-setup":
            project = replace(
                self._draft.project,
                setup_override="on" if event.value else "off",
            )
        else:
            project = replace(self._draft.project, make_current=event.value)
        self._draft = replace(self._draft, project=project)
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_repo_creation_form_widget_changed(self, event: Any) -> None:
        """Carry provider values into the draft without touching the pump."""
        from sase.ace.tui.widgets.repo_creation_form import (
            RepoCreationFormWidget as _FormWidget,
        )

        if not isinstance(event, _FormWidget.Changed):
            return
        form = self._form_widget()
        if form is None:
            return
        self._draft = replace(self._draft, provider_values=dict(form.raw_values))
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def on_button_pressed(self, event: Any) -> None:
        """Cycle owner/visibility, navigate, or trigger add-instead."""
        from textual.widgets import Button as _Button

        if not isinstance(event, _Button.Pressed):
            return
        pressed_id = event.button.id or ""
        if pressed_id == "new-project-create-back":
            self.post_message(self.BackRequested())
        elif pressed_id == "new-project-create-review":
            if self._confirmable:
                self.post_message(self.ReviewRequested())
        elif pressed_id == "new-project-create-add-instead":
            if self._availability.status == "taken":
                self.post_message(self.AddInsteadRequested(self._identity))
        elif pressed_id == "new-project-create-owner":
            self._cycle_owner()
        elif pressed_id == "new-project-create-visibility":
            self._cycle_visibility()

    def on_input_submitted(self, event: Any) -> None:
        """Offer add-instead on Enter only for taken names.

        Typing Enter in ordinary text fields never creates or applies
        anything.
        """
        from textual.widgets import Input as _Input

        if not isinstance(event, _Input.Submitted):
            return
        event.stop()
        event.prevent_default()
        if self._availability.status == "taken" and self._identity.valid:
            self.post_message(self.AddInsteadRequested(self._identity))

    def action_back(self) -> None:
        self.post_message(self.BackRequested())

    def _cycle_owner(self) -> None:
        if not self._owners:
            return
        try:
            index = self._owners.index(self._draft.owner)
        except ValueError:
            index = -1
        self.post_message(
            self.OwnerSelected(self._owners[(index + 1) % len(self._owners)])
        )

    def _cycle_visibility(self) -> None:
        options = self._supported_visibilities
        if not options:
            return
        try:
            index = options.index(self._draft.visibility)
        except ValueError:
            index = -1
        self._draft = replace(
            self._draft, visibility=options[(index + 1) % len(options)]
        )
        if self.is_mounted:
            self._sync_form()
        self.post_message(self.DraftChanged(self._draft))
        self.request_check()

    def _form_widget(self) -> Any | None:
        try:
            from sase.ace.tui.widgets.repo_creation_form import (
                RepoCreationFormWidget as _FormWidget,
            )

            return self.query_one("#new-project-create-form-slot").query_one(
                _FormWidget
            )
        except Exception:
            return None

    def _sync_form(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Input as _Input
        from textual.widgets import Static as _Static

        owner_button = self.query_one("#new-project-create-owner", _Button)
        owner_button.label = self._draft.owner or "No owners available"
        owner_button.disabled = not self._owners
        visibility_button = self.query_one("#new-project-create-visibility", _Button)
        visibility_button.label = self._draft.visibility or "private"
        self._sync_text_input("#new-project-create-name", self._draft.raw_name, _Input)
        self._sync_text_input(
            "#new-project-create-project-name",
            self._draft.project.name,
            _Input,
        )
        self._sync_text_input(
            "#new-project-create-project-aliases",
            ", ".join(self._draft.project.aliases),
            _Input,
        )
        current = self.query_one("#new-project-create-current", _Checkbox)
        if current.value != self._draft.project.make_current:
            self._ignore_checkbox_values[current.id or ""] = (
                self._draft.project.make_current
            )
            current.value = self._draft.project.make_current
        self._sync_form_slot()
        self._render_target()
        self._render_project()
        self._render_setup()
        self._render_actions()
        _ = _Static

    def _sync_text_input(self, selector: str, value: str, input_type: Any) -> None:
        control = self.query_one(selector, input_type)
        if control.value != value:
            self._ignore_input_values[control.id or ""] = value
            control.value = value

    def _sync_project_inputs(self) -> None:
        from textual.widgets import Input as _Input

        self._sync_text_input(
            "#new-project-create-project-name",
            self._draft.project.name,
            _Input,
        )

    def _sync_form_slot(self) -> None:
        from textual.widgets import Static as _Static

        slot = self.query_one("#new-project-create-form-slot")
        if self._form_status != "ready" or self._form is None:
            self._form_widget_for = None
            for child in list(slot.children):
                child.remove()
            if self._form_status == "loading":
                text = "◌ Loading provider options…"
            elif self._form_message:
                text = self._form_message
            else:
                text = "This provider does not support repository creation."
            slot.mount(_Static(text, markup=False))
            return
        if self._form_widget_for == self._form:
            widget = self._form_widget()
            if widget is not None:
                widget.set_values(dict(self._draft.provider_values))
            return
        for child in list(slot.children):
            child.remove()
        from sase.ace.tui.widgets.repo_creation_form import (
            RepoCreationFormWidget as _FormWidget,
        )

        values = dict(self._draft.provider_values) or None
        slot.mount(_FormWidget(self._form, values))
        self._form_widget_for = self._form

    def _render_target(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from .new_project_rendering import clean_source_text as _clean

        owner_button = self.query_one("#new-project-create-owner", _Button)
        owner_button.label = self._draft.owner or "No owners available"
        capability = self.query_one("#new-project-create-capability", _Static)
        if self._form is None and self._form_status == "loading":
            capability.update(Text("◌ Loading provider options…", style="dim"))
        elif self._form is None:
            capability.update(
                Text(
                    _clean(self._form_message or "Creation unavailable."),
                    style="#FF5F5F",
                )
            )
        else:
            chip = {
                True: ("Creation capability: available", "#00D7AF"),
                False: ("Creation capability: unavailable", "#FF5F5F"),
                None: ("Creation capability: unknown", "#FFAF5F"),
            }[self._form.can_create]
            text = Text(chip[0], style=chip[1])
            if self._form.message:
                text.append("\n" + _clean(self._form.message), style="dim")
            if self._form.remedy_argv:
                remedy = " ".join(_clean(item) for item in self._form.remedy_argv)
                text.append("\nRemedy: " + remedy, style="dim")
            capability.update(text)
        normalized = self.query_one("#new-project-create-normalized", _Static)
        if not self._identity.valid:
            normalized.update(Text(_clean(self._identity.error), style="#FF5F5F"))
        elif self._identity.normalized_label:
            normalized.update(
                Text(_clean(self._identity.normalized_label), style="dim")
            )
        else:
            normalized.update(Text(""))
        availability = self.query_one("#new-project-create-availability", _Static)
        styles = {
            "checking": ("◌ Checking name availability…", "dim"),
            "available": ("✓ " + self._availability.reason, "#00D7AF"),
            "taken": (
                "⚠ " + self._availability.reason + "  ⏎ Add existing instead",
                "#FFAF5F",
            ),
            "unavailable": ("? " + self._availability.reason, "#FF5F5F"),
        }
        line, style = styles[self._availability.status]
        availability.update(Text(_clean(line), style=style))

    def _render_project(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        from .new_project_configure_model import build_project_card as _card
        from .new_project_rendering import clean_source_text as _clean

        card = _card(self._document, self._draft.project)
        checkout = _Text()
        checkout.append("Source  ", style="dim")
        checkout.append(
            _clean(self._identity.display or self._identity.canonical_ref),
            style="bold",
        )
        checkout.append("\n" + _clean(card.checkout_line))
        self.query_one("#new-project-create-checkout", _Static).update(checkout)
        identity = _Text()
        if self._identity_check_valid:
            identity.append("Identity  UNIQUE", style="#00D7AF")
        else:
            identity.append("Identity  BLOCKED", style="#FFAF5F")
        if self._identity_check_reason:
            identity.append("\n" + _clean(self._identity_check_reason), style="dim")
        identity.append("\nKey  ", style="dim")
        identity.append(_clean(card.key or "pending"))
        if card.accent:
            identity.append("   ■", style=_clean(card.accent))
        self.query_one("#new-project-create-identity", _Static).update(identity)
        enabled = _Text("● enabled", style="#00D7AF")
        if card.reenable_note:
            enabled.append("   " + _clean(card.reenable_note), style="dim")
        self.query_one("#new-project-create-enabled", _Static).update(enabled)
        _ = _Button

    def _render_setup(self) -> None:
        from textual.widgets import Checkbox as _Checkbox
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        from .new_project_configure_model import build_setup_card as _setup
        from .new_project_rendering import clean_source_text as _clean

        card = _setup(self._document, self._draft.project)
        checkbox = self.query_one("#new-project-create-setup", _Checkbox)
        checkbox.display = card.show_checkbox
        checkbox.disabled = not card.show_checkbox
        if checkbox.value != card.checked:
            self._ignore_checkbox_values[checkbox.id or ""] = card.checked
            checkbox.value = card.checked
        reason = _Text(_clean(card.reason or "Setup choice follows the local plan."))
        if card.reason_style == "amber":
            reason.stylize("#FFAF5F")
        if card.follow_up:
            reason.append(
                "\nHuman follow-up: " + _clean(card.follow_up),
                style="#FFAF5F",
            )
        self.query_one("#new-project-create-setup-reason", _Static).update(reason)
        note = _clean(card.note or "")
        self.query_one("#new-project-create-setup-note", _Static).update(
            _Text(note, style="dim")
        )

    def _render_actions(self) -> None:
        from textual.widgets import Button as _Button
        from textual.widgets import Static as _Static

        from rich.text import Text as _Text

        add_instead = self.query_one("#new-project-create-add-instead", _Button)
        add_instead.display = self._availability.status == "taken"
        review = self.query_one("#new-project-create-review", _Button)
        review.disabled = not self._confirmable
        status = self.query_one("#new-project-create-status", _Static)
        if self._form_status != "ready" or self._form is None:
            status.update(_Text("Provider options unavailable.", style="dim"))
        elif not self._identity.valid:
            status.update(_Text("Enter a valid repository name.", style="dim"))
        else:
            status.update(
                _Text(
                    "Preview updates as you edit · tab moves between fields",
                    style="dim",
                )
            )


class NewProjectCreateFlowMixin(_MixinBase):
    """Seed create Configure, describe forms, and check names off-thread.

    Per-owner drafts survive navigation; defaults apply only when seeding a
    fresh owner draft. Late owner/form completions never replace the current
    owner's edits: every worker is discarded by generation, mode, owner, and
    canonical identity.
    """

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _preferences: Preferences
        _provider_by_id: dict[str, Any]
        _inputs: dict[str, Any]
        _local_plan: dict[str, Any]
        _active_target: dict[str, object]

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_stage(self, stage: str) -> None: ...
        def _prepare_configure(self, row: SourceRow, *, preserve: bool) -> None: ...

    _create_generation: int
    _create_form_generation: int
    _create_owners: tuple[str, ...]
    _create_drafts: dict[str, CreateDraft]
    _create_form: RepoCreationForm | None
    _create_form_status: CreateFormStatus
    _create_form_message: str
    _create_form_remedy: tuple[str, ...]
    _create_form_owner: str
    _create_identity: CreateIdentity
    _create_availability: CreateAvailabilityInfo
    _create_probe_cache: dict[tuple[str, str], Any]
    _create_records: list[dict[str, Any]]
    _create_plan: dict[str, Any]
    _create_plan_identity: str
    _create_review_request: dict[str, Any] | None
    _create_resume_pending_restore: bool

    def _init_create_state(self) -> None:
        """Reset create-flow state; called once from the modal constructor."""
        self._create_resume_pending_restore = False
        self._create_generation = 0
        self._create_form_generation = 0
        self._create_owners = ()
        self._create_drafts = {}
        self._create_form = None
        self._create_form_status = "loading"
        self._create_form_message = ""
        self._create_form_remedy = ()
        self._create_form_owner = ""
        self._create_identity = CreateIdentity(
            valid=False, error="Enter a repository name."
        )
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_probe_cache = {}
        self._create_records = []
        self._create_plan = {}
        self._create_plan_identity = ""
        self._create_review_request = None

    def enter_create_configure(
        self,
        *,
        workflow_type: str,
        owners: Sequence[str],
        account: str = "",
        current_project_owner: str = "",
        unavailable_owners: Container[str] = (),
        records: Sequence[Mapping[str, Any]] | None = None,
        raw_name: str = "",
    ) -> None:
        """Open create Configure from a test harness.

        Production Source affordances stay deferred; the recovery-entry phase
        adds the pinned Create row that will call this path.
        """
        self._state.workflow_type = workflow_type
        self._create_owners = tuple(dict.fromkeys(name for name in owners if name))
        if records is None:
            inputs = getattr(self, "_inputs", {}).get(workflow_type)
            records = inputs.projects if inputs is not None else []
        self._create_records = [dict(record) for record in records]
        preferences = getattr(self, "_preferences", None)
        last_owner = ""
        if preferences is not None:
            last_owner = preferences.last_owner.get(workflow_type, "")
        owner = default_create_owner(
            self._create_owners,
            account=account,
            last_owner=last_owner,
            current_project_owner=current_project_owner,
            workflow_type=workflow_type,
            unavailable=unavailable_owners,
        )
        draft = self._create_drafts.get(owner)
        if draft is None:
            draft = self._seed_create_draft(owner, raw_name=raw_name)
            self._create_drafts[owner] = draft
        identity = normalize_create_name(workflow_type, owner, draft.raw_name)
        self._create_identity = identity
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_plan = {}
        self._create_plan_identity = ""
        self._create_review_request = None
        self._state.to_create_configure(draft)
        self._create_resume_pending_restore = False
        self._show_stage("create-configure")
        self._paint_create_configure()
        self.query_one(NewProjectCreateConfigure).focus_name()
        self._describe_create_form(owner)

    def _seed_create_draft(self, owner: str, *, raw_name: str = "") -> CreateDraft:
        """Seed a fresh owner draft, applying defaults exactly once."""
        preferences = getattr(self, "_preferences", None)
        last_visibility: Mapping[str, str] = (
            preferences.last_visibility if preferences is not None else {}
        )
        supported = supported_create_visibilities(None)
        visibility = default_create_visibility(
            owner=owner, supported=supported, last_visibility=last_visibility
        )
        identity = normalize_create_name(self._state.workflow_type, owner, raw_name)
        base = identity.project_name_base or identity.name
        return CreateDraft(
            owner=owner,
            raw_name=raw_name,
            visibility=visibility,
            project=ConfigureDraft(name=base),
        )

    def _supported_visibilities(self) -> tuple[str, ...]:
        return supported_create_visibilities(self._create_form)

    def _paint_create_configure(self) -> None:
        """Repaint the create stage from flow-owned state."""
        widget = self.query_one(NewProjectCreateConfigure)
        draft = self._state.create_draft or CreateDraft()
        confirmable = self._create_confirmable(draft)
        widget.set_context(
            workflow_type=self._state.workflow_type,
            owners=self._create_owners,
            supported_visibilities=self._supported_visibilities(),
            draft=draft,
            identity=self._create_identity,
            availability=self._create_availability,
            form=self._create_form,
            form_status=self._create_form_status,
            form_message=self._create_form_message,
            form_remedy=self._create_form_remedy,
            document=self._create_plan,
            identity_valid=self._create_identity_valid(),
            identity_reason=self._create_identity_reason(),
            confirmable=confirmable,
        )

    def _create_plan_current(self) -> bool:
        return bool(self._create_plan) and (
            self._create_plan_identity == self._create_identity.identity_key
        )

    def _create_identity_valid(self) -> bool:
        if not self._create_identity.valid or not self._create_plan_current():
            return False
        verdict, _ = create_identity_verdict(self._create_plan)
        return verdict

    def _create_identity_reason(self) -> str:
        if not self._create_identity.valid:
            return self._create_identity.error
        if not self._create_plan:
            return "Building the local plan…"
        if not self._create_plan_current():
            return "Updating the local plan…"
        _, reason = create_identity_verdict(self._create_plan)
        return reason

    def _create_confirmable(self, draft: CreateDraft) -> bool:
        if self._create_form_status != "ready" or self._create_form is None:
            return False
        if self._create_availability.status != "available":
            return False
        if not self._create_identity.valid:
            return False
        if not self._create_plan_current():
            return False
        verdict, _ = create_identity_verdict(self._create_plan)
        return verdict

    def _on_create_draft_changed(self, draft: CreateDraft) -> None:
        """Store the draft edit; the widget owns the debounce timer."""
        self._state.set_create_draft(draft)
        self._create_drafts[draft.owner] = draft
        self._create_availability = CreateAvailabilityInfo(status="checking")
        widget = self.query_one(NewProjectCreateConfigure)
        widget.mark_check_pending()

    def _on_create_check_requested(self) -> None:
        widget = self.query_one(NewProjectCreateConfigure)
        if not widget._check_due:
            return
        self._schedule_create_check()

    def _on_create_owner_selected(self, owner: str) -> None:
        """Switch owners, preserving each owner's draft and edits."""
        if owner == (
            self._state.create_draft.owner if self._state.create_draft else ""
        ):
            return
        self._create_generation += 1
        draft = self._create_drafts.get(owner)
        if draft is None:
            draft = self._seed_create_draft(owner)
            self._create_drafts[owner] = draft
        self._create_identity = normalize_create_name(
            self._state.workflow_type, owner, draft.raw_name
        )
        self._create_availability = CreateAvailabilityInfo(status="checking")
        self._create_plan = {}
        self._create_plan_identity = ""
        self._state.set_create_draft(draft)
        self._paint_create_configure()
        self._describe_create_form(owner)

    def _on_create_review_requested(self) -> None:
        """Hook create Configure into the shared Review pipeline."""
        draft = self._state.create_draft
        if draft is None or not self._create_confirmable(draft):
            return
        self._create_resume_pending_restore = False
        workflow_type = self._state.workflow_type
        metadata = getattr(self, "_provider_by_id", {}).get(workflow_type)
        self._create_review_request = create_review_request(
            identity=self._create_identity,
            workflow_type=workflow_type,
            provider_display=str(getattr(metadata, "display_name", "") or ""),
            storage_policy=str(getattr(metadata, "sdd_storage_policy", "") or ""),
            project=draft.project,
            visibility=draft.visibility,
            effective_options=lenient_effective_options(
                self._create_form, draft.provider_values
            ),
        )
        plan = dict(self._create_plan)
        if not plan:
            return
        self._local_plan = plan
        self._active_target = dict(self._create_review_request.get("target") or {})
        self._state.to_review()
        self._show_stage("review")
        review = self.query_one("#new-project-review-stage")
        start_check = getattr(review, "start_check", None)
        if callable(start_check):
            start_check(plan)
        back = review.query_one("#new-project-review-back")
        focus = getattr(back, "focus", None)
        if callable(focus):
            focus()

    def create_review_intent(self) -> dict[str, Any] | None:
        """Return the staged complete create intent, if Review was requested."""
        return (
            dict(self._create_review_request)
            if self._create_review_request is not None
            else None
        )

    def _restore_create_configure_from_resume(self) -> None:
        """Repaint create Configure after Back from a resumed create Review.

        The resume hydration jumps straight to checked Review, so the
        Configure widget was never painted. Restore the recovered draft,
        re-describe the owner form, and schedule a live check.
        """
        draft = self._state.create_draft
        if draft is None:
            return
        self._create_resume_pending_restore = False
        if draft.owner and draft.owner not in self._create_owners:
            self._create_owners = (*self._create_owners, draft.owner)
        self._create_drafts[draft.owner] = draft
        self._paint_create_configure()
        self._describe_create_form(draft.owner)
        self._schedule_create_check()
        try:
            self.query_one(NewProjectCreateConfigure).focus_name()
        except Exception:
            pass

    def _on_create_back_requested(self) -> None:
        """Return to Source, cancelling pending create work."""
        self._create_generation += 1
        self._create_form_generation += 1
        try:
            self.query_one(NewProjectCreateConfigure).cancel_pending()
        except Exception:
            pass
        self._state.back_to_source()
        self._state.wizard_mode = "add"
        self._show_stage("source")

    def _on_create_add_instead(self, identity: CreateIdentity) -> None:
        """Switch an explicitly taken remote to existing-repo Configure."""
        if not identity.valid:
            return
        from .new_project_source_model import SourceRow as _SourceRow

        self._create_generation += 1
        self._create_form_generation += 1
        try:
            self.query_one(NewProjectCreateConfigure).cancel_pending()
        except Exception:
            pass
        workflow_type = self._state.workflow_type
        metadata = getattr(self, "_provider_by_id", {}).get(workflow_type)
        seed = add_instead_seed(
            identity=identity,
            workflow_type=workflow_type,
            provider_display=str(getattr(metadata, "display_name", "") or ""),
            storage_policy=str(getattr(metadata, "sdd_storage_policy", "") or ""),
        )
        row = _SourceRow(
            row_id=f"create-add-instead:{identity.identity_key}",
            group="paste",
            display=identity.display or identity.canonical_ref,
            ref=identity.canonical_ref,
            owner=identity.owner,
            data={
                **seed,
                "name": identity.name,
                "project_name_base": identity.project_name_base,
                "project_key_base": identity.project_key_base,
                "identity_key": identity.identity_key,
                "web_url": identity.web_url,
            },
        )
        self._state.selected = row
        self._state.to_add_configure()
        self._prepare_configure(row, preserve=False)
        self._show_stage(self._state.stage)
        try:
            from .new_project_configure import NewProjectConfigure as _Configure

            self.query_one(_Configure).focus_name()
        except Exception:
            pass

    def _describe_create_form(self, owner: str) -> None:
        """Fetch the provider form off-thread with stale-owner guards."""
        self._create_form_generation += 1
        generation = self._create_form_generation
        self._create_form_owner = owner
        if not owner and self._state.workflow_type != _BARE_GIT_WORKFLOW:
            self._create_form = None
            self._create_form_status = "unavailable"
            self._create_form_message = "No owners available for this provider."
            self._create_form_remedy = ()
            if self._state.wizard_mode == "create":
                self._paint_create_configure()
            return
        self._create_form_status = "loading"
        self._create_form_message = ""
        self._create_form_remedy = ()
        if self._state.wizard_mode == "create":
            self._paint_create_configure()
        workflow_type = self._state.workflow_type
        spawn_pump_free_task(
            self,
            self._observe_create_form(generation, workflow_type, owner),
            name=f"new-project-create-form:{workflow_type}:{owner}",
            registry_attr=_CREATE_TASKS,
        )

    async def _observe_create_form(
        self, generation: int, workflow_type: str, owner: str
    ) -> None:
        try:
            form = await _describe_form_off_thread(workflow_type, owner)
        except Exception:
            form = None
        if not self.is_mounted:
            return
        if (
            generation != self._create_form_generation
            or self._state.wizard_mode != "create"
            or self._state.workflow_type != workflow_type
            or self._create_form_owner != owner
        ):
            return
        current = self._state.create_draft
        if current is None or current.owner != owner:
            return
        self._create_form = form
        if form is None:
            self._create_form_status = "unavailable"
            self._create_form_message = (
                "This provider does not support repository creation."
            )
            self._create_form_remedy = ()
        else:
            self._create_form_status = "ready"
            self._create_form_message = form.message
            self._create_form_remedy = tuple(form.remedy_argv)
            supported = supported_create_visibilities(form)
            if current.visibility not in supported:
                updated = replace(
                    current,
                    visibility=default_create_visibility(
                        owner=owner,
                        supported=supported,
                        last_visibility=self._preferences.last_visibility,
                    ),
                )
                self._state.set_create_draft(updated)
                self._create_drafts[owner] = updated
        self._paint_create_configure()
        self._schedule_create_check()

    def _schedule_create_check(self) -> None:
        """Run probe, checkout observation, and planning off-thread."""
        if self._state.wizard_mode != "create":
            return
        draft = self._state.create_draft
        if draft is None:
            return
        identity = normalize_create_name(
            self._state.workflow_type, draft.owner, draft.raw_name
        )
        self._create_identity = identity
        if not identity.valid:
            self._create_availability = CreateAvailabilityInfo(
                status="unavailable", reason=identity.error
            )
            self._create_plan = {}
            self._create_plan_identity = ""
            self._paint_create_configure()
            return
        self._create_generation += 1
        generation = self._create_generation
        workflow_type = self._state.workflow_type
        owner = draft.owner
        cached = self._create_probe_cache.get((workflow_type, identity.canonical_ref))
        metadata = getattr(self, "_provider_by_id", {}).get(workflow_type)
        spawn_pump_free_task(
            self,
            self._run_create_check(
                generation=generation,
                workflow_type=workflow_type,
                owner=owner,
                identity=identity,
                draft=draft,
                cached_probe=cached,
                provider_display=str(getattr(metadata, "display_name", "") or ""),
                storage_policy=str(getattr(metadata, "sdd_storage_policy", "") or ""),
            ),
            name=f"new-project-create-check:{identity.canonical_ref}",
            registry_attr=_CREATE_TASKS,
        )

    async def _run_create_check(
        self,
        *,
        generation: int,
        workflow_type: str,
        owner: str,
        identity: CreateIdentity,
        draft: CreateDraft,
        cached_probe: Any | None,
        provider_display: str,
        storage_policy: str,
    ) -> None:
        """Observe the settled target and rebuild the local create plan."""
        if cached_probe is None:
            try:
                probe = await asyncio.to_thread(
                    workspace_provider.probe_repo,
                    workflow_type,
                    identity.canonical_ref,
                )
            except Exception as error:
                probe = None
                probe_error = str(error)
            else:
                probe_error = ""
        else:
            probe = cached_probe
            probe_error = ""
        try:
            checkout = await asyncio.to_thread(
                observe_create_checkout,
                identity.checkout_dir,
                identity_key=identity.identity_key,
                workflow_type=workflow_type,
            )
        except Exception:
            checkout = {
                "state": "absent",
                "origin_url": "",
                "config_dirty": False,
                "on_default_branch": None,
            }
        effective = lenient_effective_options(self._create_form, draft.provider_values)
        try:
            facts = assemble_create_facts(
                records=self._create_records,
                probe=probe,
                identity_key=identity.identity_key,
                checkout=checkout,
            )
            document = await asyncio.to_thread(
                plan_create_display,
                identity=identity,
                workflow_type=workflow_type,
                provider_display=provider_display,
                storage_policy=storage_policy,
                project=draft.project,
                visibility=draft.visibility,
                effective_options=effective,
                facts=facts,
            )
        except Exception as error:
            document = {}
            plan_error = str(error) or type(error).__name__
        else:
            plan_error = ""
        if probe is not None:
            self._create_probe_cache[(workflow_type, identity.canonical_ref)] = probe
        if not self.is_mounted:
            return
        if not probe_result_current(
            generation=generation,
            expected_generation=self._create_generation,
            mode=self._state.wizard_mode,
            expected_mode="create",
            owner=owner,
            expected_owner=(
                self._state.create_draft.owner if self._state.create_draft else ""
            ),
            identity_key=identity.identity_key,
            expected_identity_key=self._create_identity.identity_key,
        ):
            return
        if self._state.create_draft != draft:
            return
        availability = classify_create_probe(probe)
        if probe is None and probe_error:
            availability = CreateAvailabilityInfo(
                status="unavailable", reason=probe_error
            )
        self._create_availability = availability
        self._create_plan = document
        self._create_plan_identity = identity.identity_key if document else ""
        widget = self.query_one(NewProjectCreateConfigure)
        if plan_error and not document:
            widget.apply_check(
                availability=availability,
                document={},
                identity_valid=False,
                identity_reason=plan_error,
                confirmable=False,
            )
            return
        verdict, reason = create_identity_verdict(document)
        widget.apply_check(
            availability=availability,
            document=document,
            identity_valid=bool(document) and verdict,
            identity_reason=reason,
            confirmable=self._create_confirmable(draft),
        )


__all__ = [
    "AVAILABILITY_DEBOUNCE_SECONDS",
    "FIRST_USE_VISIBILITY",
    "CreateAvailability",
    "CreateAvailabilityInfo",
    "CreateDraft",
    "CreateFormStatus",
    "CreateIdentity",
    "NewProjectCreateConfigure",
    "NewProjectCreateFlowMixin",
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
