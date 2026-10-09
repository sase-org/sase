"""Core-owned ``%auto`` autonomy record adapter (``%auto`` E1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.autonomy.record import (
    COVERAGE_LINE,
    LEGACY_AUTONOMY_KEYS,
    apply_record_meta_patch,
    auto_applies,
    autonomy_inherit_record,
    decision_sentence,
    evaluate,
    legacy_projection,
    live_record,
    mutate_record,
    profiles_catalog,
    read_decision_log,
    read_record,
    record_meta_patch,
    record_only,
    refresh_record_from_legacy,
    resolve_selection,
    RETUNE_DROP_KEYS,
    RETUNE_TRIGGER_KEYS,
    retune_meta_record,
    selection_to_prompt_prefix,
    summarize_record,
    with_legacy_projection,
)

if TYPE_CHECKING:
    from sase.autonomy.roles import (
        DEFAULT_ROLE_PROFILE,
        EPIC_LAND_ROLE,
        EPIC_PHASE_ROLE,
        RoleAssignment,
        role_assignments,
        role_auto_directive,
        role_profile,
    )

#: Epic worker role assignments live in ``sase.autonomy.roles``, but that
#: module stays out of this package's eager imports: ``sase.autonomy.gates``
#: is on the TUI startup path (via ``notification_gates.adapter_registry``),
#: and importing this package would otherwise drag ``roles`` (plus config)
#: into the TUI import closure. Role symbols resolve lazily instead.
_LAZY_ROLES = {
    "DEFAULT_ROLE_PROFILE": "sase.autonomy.roles",
    "EPIC_LAND_ROLE": "sase.autonomy.roles",
    "EPIC_PHASE_ROLE": "sase.autonomy.roles",
    "RoleAssignment": "sase.autonomy.roles",
    "role_assignments": "sase.autonomy.roles",
    "role_auto_directive": "sase.autonomy.roles",
    "role_profile": "sase.autonomy.roles",
}


def __getattr__(name: str) -> object:
    """Lazily resolve ``sase.autonomy.roles`` symbols on first use."""
    if name in _LAZY_ROLES:
        import importlib

        module = importlib.import_module(_LAZY_ROLES[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    import sys

    names = set(sys.modules[__name__].__dict__) | set(__all__)
    return sorted(names | set(_LAZY_ROLES))


_PEP562_HOOKS = (__getattr__, __dir__)


__all__ = [
    "COVERAGE_LINE",
    "DEFAULT_ROLE_PROFILE",
    "EPIC_LAND_ROLE",
    "EPIC_PHASE_ROLE",
    "RoleAssignment",
    "LEGACY_AUTONOMY_KEYS",
    "apply_record_meta_patch",
    "auto_applies",
    "autonomy_inherit_record",
    "decision_sentence",
    "evaluate",
    "legacy_projection",
    "live_record",
    "mutate_record",
    "profiles_catalog",
    "read_decision_log",
    "read_record",
    "record_meta_patch",
    "record_only",
    "refresh_record_from_legacy",
    "resolve_selection",
    "RETUNE_DROP_KEYS",
    "RETUNE_TRIGGER_KEYS",
    "retune_meta_record",
    "role_assignments",
    "role_auto_directive",
    "role_profile",
    "selection_to_prompt_prefix",
    "summarize_record",
    "with_legacy_projection",
]
