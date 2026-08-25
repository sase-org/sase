"""Public copy-mode target registry helpers for ACE."""

from __future__ import annotations

from ._copy_target_registry import COPY_TARGETS
from ._copy_target_types import CopyTargetCategory, CopyTarget, build_copy_target


_TARGETS_BY_KEY = {(item.group, item.target): item for item in COPY_TARGETS}
_GENERIC_ARTIFACT_COPY_GROUPS = {
    "artifacts_stitches",
    "artifacts_plans",
    "artifacts_beads",
    "artifacts_other",
    "artifacts_documents",
}


def _normalize_copy_group(group: str) -> str:
    """Return the canonical copy-mode group id."""
    if group.startswith("artifacts_ref:"):
        return "artifacts_plans"
    if group == "artifacts_files":
        return "artifacts_other"
    return "patches" if group == "patches" else group


def copy_targets_for(group: str) -> tuple[CopyTarget, ...]:
    """Return the registry entries for *group* in presentation order."""

    group = _normalize_copy_group(group)
    exact = tuple(item for item in COPY_TARGETS if item.group == group)
    if exact:
        return exact
    if group.startswith("artifacts_") and group not in _GENERIC_ARTIFACT_COPY_GROUPS:
        return tuple(
            build_copy_target(
                group,
                item.target,
                item.footer_label,
                item.palette_label,
                item.category,
                item.plural_label,
                accepts_marks=item.accepts_marks,
            )
            for item in COPY_TARGETS
            if item.group == "artifacts_documents"
        )
    return ()


def copy_target_for(group: str, target: str) -> CopyTarget | None:
    """Return one target, preserving the legacy Patch alias."""

    group = _normalize_copy_group(group)
    if group == "patches" and target == "cl_number":
        target = "pr_number"
    found = _TARGETS_BY_KEY.get((group, target))
    if found is not None:
        return found
    if group.startswith("artifacts_") and (group, target) not in _TARGETS_BY_KEY:
        template = _TARGETS_BY_KEY.get(("artifacts_documents", target))
        if template is not None:
            return build_copy_target(
                group,
                template.target,
                template.footer_label,
                template.palette_label,
                template.category,
                template.plural_label,
                accepts_marks=template.accepts_marks,
            )
    return None


__all__ = [
    "COPY_TARGETS",
    "CopyTargetCategory",
    "copy_target_for",
    "copy_targets_for",
]
