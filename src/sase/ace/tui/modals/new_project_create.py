"""Create draft and Configure stage for new repositories.

Facade preserving the original module's public import path. The
implementation now lives in sibling modules (each at most 500 lines):

- :mod:`sase.ace.tui.modals.new_project_create_types` — draft, identity,
  and availability types.
- :mod:`sase.ace.tui.modals.new_project_create_model` — pure defaults,
  normalization, probes, checkout observation, and plan assembly.
- :mod:`sase.ace.tui.modals.new_project_create_widget` — the create
  Configure widget.
- :mod:`sase.ace.tui.modals.new_project_create_rendering` — card paint
  and form-slot sync.
- :mod:`sase.ace.tui.modals.new_project_create_flow` — stage seeding and
  navigation.
- :mod:`sase.ace.tui.modals.new_project_create_checks` — off-thread form
  describe, availability, and local planning.

Shared helpers live in the private
:mod:`sase.ace.tui.modals._new_project_create_shared` module under public
names so siblings never import ``_``-prefixed names across modules.

This module implements the ``create-configure`` phase: the frozen create
draft, owner and visibility defaults, pure name normalization, debounced
off-thread availability and checkout checks, Rust identity previews, and
the explicit add-instead transition.

The stage is reachable from test harnesses only. No production Source
affordance selects create Configure yet; the ``recovery-entry`` phase adds
the pinned Create row. The normal add wizard keeps working unchanged.

Threading rules: pure Rust evaluation runs directly on the pump. Provider
``describe_repo_creation`` calls, probes, checkout observations, and
plan-envelope I/O run off-thread in the flow mixin. Typing never starts a
subprocess or provider network call synchronously.
"""

from __future__ import annotations

from .new_project_create_flow import (
    NewProjectCreateFlowMixin as NewProjectCreateFlowMixin,
)
from .new_project_create_model import (
    add_instead_seed as _add_instead_seed,
    assemble_create_facts as assemble_create_facts,
    build_create_plan_request as _build_create_plan_request,
    classify_create_probe as classify_create_probe,
    create_identity_verdict as _create_identity_verdict,
    create_review_request as _create_review_request,
    default_create_owner as _default_create_owner,
    default_create_visibility as _default_create_visibility,
    lenient_effective_options as _lenient_effective_options,
    normalize_create_name as normalize_create_name,
    observe_create_checkout as observe_create_checkout,
    plan_create_display as plan_create_display,
    probe_result_current as _probe_result_current,
    supported_create_visibilities as _supported_create_visibilities,
)
from .new_project_create_types import (
    FIRST_USE_VISIBILITY as FIRST_USE_VISIBILITY,
    CreateAvailability as CreateAvailability,
    CreateAvailabilityInfo as CreateAvailabilityInfo,
    CreateDraft as CreateDraft,
    CreateFormStatus as CreateFormStatus,
    CreateIdentity as CreateIdentity,
)
from .new_project_create_widget import (
    AVAILABILITY_DEBOUNCE_SECONDS as AVAILABILITY_DEBOUNCE_SECONDS,
    NewProjectCreateConfigure as NewProjectCreateConfigure,
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
    "assemble_create_facts",
    "classify_create_probe",
    "normalize_create_name",
    "observe_create_checkout",
    "plan_create_display",
]
