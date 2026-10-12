"""Candidate discovery and ``sase project suggest`` rendering.

Package-level attributes are lazy re-exports (PEP 562): importing
``sase.project_onboarding`` does not import the discovery engine until an
attribute is actually accessed, keeping the suggest hot path — and every
unrelated CLI startup — from paying for the classification imports.
"""

from __future__ import annotations

from typing import Any

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "CandidateInputs": (
        "sase.project_onboarding.discovery",
        "CandidateInputs",
    ),
    "OwnerResult": ("sase.project_onboarding.discovery", "OwnerResult"),
    "Preferences": ("sase.project_onboarding.preferences", "Preferences"),
    "SUGGEST_SCHEMA_VERSION": (
        "sase.project_onboarding.discovery",
        "SUGGEST_SCHEMA_VERSION",
    ),
    "UserRefError": ("sase.project_onboarding.refs", "UserRefError"),
    "build_plan_document": (
        "sase.project_onboarding.planning",
        "build_plan_document",
    ),
    "detect_actor": ("sase.project_onboarding.human_only", "detect_actor"),
    "emit_event": ("sase.project_onboarding.events", "emit_event"),
    "gather_facts": ("sase.project_onboarding.facts", "gather_facts"),
    "journals_dir": ("sase.project_onboarding.discovery", "journals_dir"),
    "list_incomplete": (
        "sase.project_onboarding.journal",
        "list_incomplete",
    ),
    "load_candidate_inputs": (
        "sase.project_onboarding.discovery",
        "load_candidate_inputs",
    ),
    "load_preferences": (
        "sase.project_onboarding.preferences",
        "load_preferences",
    ),
    "manage_repository": (
        "sase.project_onboarding.manage",
        "manage_repository",
    ),
    "ManagementError": (
        "sase.project_onboarding.manage",
        "ManagementError",
    ),
    "parse_event_line": ("sase.project_onboarding.events", "parse_event_line"),
    "parse_user_ref": ("sase.project_onboarding.refs", "parse_user_ref"),
    "preferences_path": (
        "sase.project_onboarding.preferences",
        "preferences_path",
    ),
    "print_suggest": ("sase.project_onboarding.render", "print_suggest"),
    "record_owner_selection": (
        "sase.project_onboarding.preferences",
        "record_owner_selection",
    ),
    "record_provider_selection": (
        "sase.project_onboarding.preferences",
        "record_provider_selection",
    ),
    "record_visibility_selection": (
        "sase.project_onboarding.preferences",
        "record_visibility_selection",
    ),
    "render_suggest_json": (
        "sase.project_onboarding.render",
        "render_suggest_json",
    ),
    "save_preferences": (
        "sase.project_onboarding.preferences",
        "save_preferences",
    ),
    "suggest": ("sase.project_onboarding.discovery", "suggest"),
}


def __getattr__(name: str) -> Any:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

__all__ = [
    "CandidateInputs",
    "OwnerResult",
    "Preferences",
    "SUGGEST_SCHEMA_VERSION",
    "UserRefError",
    "build_plan_document",
    "detect_actor",
    "emit_event",
    "gather_facts",
    "journals_dir",
    "list_incomplete",
    "load_candidate_inputs",
    "load_preferences",
    "manage_repository",
    "ManagementError",
    "parse_event_line",
    "parse_user_ref",
    "preferences_path",
    "print_suggest",
    "record_owner_selection",
    "record_provider_selection",
    "record_visibility_selection",
    "render_suggest_json",
    "save_preferences",
    "suggest",
]
