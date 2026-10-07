"""Shared wait-dependency resolution helpers."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from ._confirmation import (
    WaitReleaseConfirmation,
    confirm_dependency_resolution,
)
from ._index import WaitDependencyIndex, build_wait_dependency_index
from ._json_io import read_json_dict
from ._resolution import dependency_resolution_status
from ._submitted_plans import (
    submitted_plan_artifact,
    submitted_plan_artifact_for_dir,
)
from ._tribe_binding import (
    TribeMemberRow,
    TribeWaitBinding,
    resolve_tribe_wait_binding,
)
from ._types import KNOWN_DONE_OUTCOMES, WAIT_SUCCESS_OUTCOMES, TribeCandidate

if TYPE_CHECKING:
    from ._epic_follow_release import (
        WaitEpicFollowPatch,
        WaitReleaseDecision,
        apply_wait_epic_follow_patch,
        armed_wait_epic_targets,
        resolve_wait_release,
        set_waiting_until,
    )

_LAZY_EPIC_FOLLOW_RELEASE = {
    "WaitEpicFollowPatch": "sase.core.wait_dependency_resolution._epic_follow_release",
    "WaitReleaseDecision": "sase.core.wait_dependency_resolution._epic_follow_release",
    "apply_wait_epic_follow_patch": "sase.core.wait_dependency_resolution._epic_follow_release",
    "armed_wait_epic_targets": "sase.core.wait_dependency_resolution._epic_follow_release",
    "resolve_wait_release": "sase.core.wait_dependency_resolution._epic_follow_release",
    "set_waiting_until": "sase.core.wait_dependency_resolution._epic_follow_release",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EPIC_FOLLOW_RELEASE:
        module = importlib.import_module(_LAZY_EPIC_FOLLOW_RELEASE[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "KNOWN_DONE_OUTCOMES",
    "WaitEpicFollowPatch",
    "WaitReleaseConfirmation",
    "WaitReleaseDecision",
    "TribeMemberRow",
    "TribeWaitBinding",
    "WaitDependencyIndex",
    "WAIT_SUCCESS_OUTCOMES",
    "TribeCandidate",
    "apply_wait_epic_follow_patch",
    "armed_wait_epic_targets",
    "build_wait_dependency_index",
    "confirm_dependency_resolution",
    "dependency_resolution_status",
    "read_json_dict",
    "resolve_tribe_wait_binding",
    "resolve_wait_release",
    "set_waiting_until",
    "submitted_plan_artifact",
    "submitted_plan_artifact_for_dir",
]
