"""Console-free plugin install/update/uninstall operations.

This module is the stable public import surface for plugin mutations. The
implementation is split by operation family in private sibling modules, while
callers continue to import from :mod:`sase.plugins.operations`.
"""

from __future__ import annotations

from sase.plugins.post_change import PluginChangeEffects, empty_effects

from ._operations_common import (
    AvailabilityBatchFn,
    AvailabilityProbeFn,
    ClockFn,
    InstalledIndexFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    ResolvedSpec,
    RunUvFn,
    SpecSource,
    capture_command_snapshot_before,
    post_change_effects,
    resolve_install_spec,
)
from ._operations_install import (
    AlreadyInstalled,
    InstallManyNothing,
    InstallManyOutcome,
    InstallManyPlan,
    InstallManyReady,
    InstallNotFound,
    InstallOutcome,
    InstallPlan,
    InstallReady,
    InstallSkipped,
    execute_install,
    execute_install_many,
    plan_install,
    plan_install_many,
)
from ._operations_uninstall import (
    AlreadyAbsent,
    UninstallOutcome,
    UninstallPlan,
    UninstallReady,
    UninstallUnknown,
    execute_uninstall,
    plan_uninstall,
)
from ._operations_update import (
    NoPlugins,
    NotInstalled,
    UpdateOutcome,
    UpdatePlan,
    UpdateReady,
    UpdateUnknown,
    execute_update,
    plan_update,
)

__all__ = [
    "AlreadyAbsent",
    "AlreadyInstalled",
    "AvailabilityBatchFn",
    "AvailabilityProbeFn",
    "ClockFn",
    "InstallManyNothing",
    "InstallManyOutcome",
    "InstallManyPlan",
    "InstallManyReady",
    "InstallNotFound",
    "InstallOutcome",
    "InstallPlan",
    "InstallReady",
    "InstallSkipped",
    "InstalledIndexFn",
    "LoadFn",
    "NoPlugins",
    "NotInstalled",
    "NotUvTool",
    "PluginChangeEffects",
    "ProbeFn",
    "ResolvedSpec",
    "RunUvFn",
    "SpecSource",
    "UninstallOutcome",
    "UninstallPlan",
    "UninstallReady",
    "UninstallUnknown",
    "UpdateOutcome",
    "UpdatePlan",
    "UpdateReady",
    "UpdateUnknown",
    "capture_command_snapshot_before",
    "empty_effects",
    "execute_install",
    "execute_install_many",
    "execute_uninstall",
    "execute_update",
    "plan_install",
    "plan_install_many",
    "plan_uninstall",
    "plan_update",
    "post_change_effects",
    "resolve_install_spec",
]
