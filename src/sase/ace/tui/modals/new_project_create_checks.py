"""Off-thread form describe, availability probe, and local create planning."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sase import workspace_provider
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.workspace_provider._hookspec import RepoCreationForm

from ._new_project_create_shared import BARE_GIT_WORKFLOW
from .new_project_create_model import (
    assemble_create_facts,
    classify_create_probe,
    create_identity_verdict,
    default_create_visibility,
    lenient_effective_options,
    normalize_create_name,
    observe_create_checkout,
    plan_create_display,
    probe_result_current,
    supported_create_visibilities,
)
from .new_project_create_types import (
    CreateAvailabilityInfo,
    CreateDraft,
    CreateFormStatus,
    CreateIdentity,
)
from .new_project_create_widget import NewProjectCreateConfigure

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase

    from .new_project_state import NewProjectStateMachine
    from sase.project_onboarding import Preferences
else:
    _MixinBase = object

_CREATE_TASKS = "_new_project_create_tasks"


async def _describe_form_off_thread(
    workflow_type: str, namespace: str
) -> RepoCreationForm | None:
    """Fetch one provider creation form outside the Textual pump."""
    return await asyncio.to_thread(
        workspace_provider.describe_repo_creation, workflow_type, namespace
    )


class NewProjectCreateChecksMixin(_MixinBase):
    """Fetch provider forms and rebuild the create plan off the pump."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _preferences: Preferences
        _provider_by_id: dict[str, Any]
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

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def call_after_refresh(
            self, callback: Any, *args: Any, **kwargs: Any
        ) -> Any: ...

    def _supported_visibilities(self) -> tuple[str, ...]:
        if self._create_form_status != "ready":
            return ()
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

    def _describe_create_form(self, owner: str) -> None:
        """Fetch the provider form off-thread with stale-owner guards."""
        self._create_form_generation += 1
        generation = self._create_form_generation
        self._create_form_owner = owner
        if not owner and self._state.workflow_type != BARE_GIT_WORKFLOW:
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
        self._paint_observed_create_form(generation, owner)

    def _paint_observed_create_form(
        self, generation: int, owner: str, *, retry: bool = True
    ) -> None:
        """Paint the settled form; retry once if the slot is mid-remount."""
        if not self._create_form_observation_current(generation, owner):
            return
        try:
            self._paint_create_configure()
        except Exception:
            log.exception(
                "create-form paint failed after status=%s owner=%s",
                self._create_form_status,
                owner,
            )
            if (
                retry
                and self.is_mounted
                and self._create_form_observation_current(generation, owner)
            ):
                self.call_after_refresh(
                    lambda: self._paint_observed_create_form(
                        generation, owner, retry=False
                    )
                )
            return
        self._schedule_create_check()

    def _create_form_observation_current(self, generation: int, owner: str) -> bool:
        return (
            self.is_mounted
            and generation == self._create_form_generation
            and self._state.wizard_mode == "create"
            and self._create_form_owner == owner
        )

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
                creation_form=self._create_form,
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


__all__ = ["NewProjectCreateChecksMixin"]
