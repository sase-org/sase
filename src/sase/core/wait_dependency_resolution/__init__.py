"""Shared wait-dependency resolution helpers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from ._confirmation import (
    WaitReleaseConfirmation,
    confirm_dependency_resolution,
)
from ._index import WaitDependencyIndex, build_wait_dependency_index
from ._json_io import read_json_dict
from ._release_telemetry import latest_member_finished_at, parse_finished_at
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
        WaitEpicFollowPatch as WaitEpicFollowPatch,
        WaitReleaseDecision as WaitReleaseDecision,
        apply_wait_epic_follow_patch as apply_wait_epic_follow_patch,
        armed_wait_epic_targets as armed_wait_epic_targets,
        resolve_wait_release as resolve_wait_release,
        set_waiting_until as set_waiting_until,
    )

# The epic-follow release pulls the directive and agent-meta lock modules;
# load it on first use so importing the package (TUI startup) stays cheap.
_LAZY_EXPORTS = {
    "WaitEpicFollowPatch": "sase.core.wait_dependency_resolution._epic_follow_release",
    "WaitReleaseDecision": "sase.core.wait_dependency_resolution._epic_follow_release",
    "apply_wait_epic_follow_patch": (
        "sase.core.wait_dependency_resolution._epic_follow_release"
    ),
    "armed_wait_epic_targets": (
        "sase.core.wait_dependency_resolution._epic_follow_release"
    ),
    "resolve_wait_release": "sase.core.wait_dependency_resolution._epic_follow_release",
    "set_waiting_until": "sase.core.wait_dependency_resolution._epic_follow_release",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)

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
    "latest_member_finished_at",
    "parse_finished_at",
    "read_json_dict",
    "resolve_tribe_wait_binding",
    "resolve_wait_release",
    "set_waiting_until",
    "submitted_plan_artifact",
    "submitted_plan_artifact_for_dir",
]
