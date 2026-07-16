"""Shared types for the ``sase update`` command implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from sase.axe.process import AxeStartResult
from sase.dev_update import DevUpdatePlan, DevUpdateResult
from sase.dev_update.models import DevCommandRunner
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.receipt import Requirement, ToolReceipt
from sase.uv_tool.runner import UvChangeSet
from sase.uv_tool.render import UpdateSummary
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UPDATE_JSON_SCHEMA_VERSION = 2

ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
VersionFn = Callable[[str], str | None]
ClockFn = Callable[[], float]
InventoryFn = Callable[[], RuntimeVersionInventory]
AxeRunningFn = Callable[[], bool]
RestartAxeFn = Callable[[], AxeStartResult]
RestartStatus = Literal[
    "skipped_no_change",
    "skipped_not_running",
    "restarted",
    "failed",
]


class PlanDevFn(Protocol):
    def __call__(
        self,
        records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
        *,
        host_record: VersionPackageRecord,
        receipt: ToolReceipt | None = None,
        tool_python: str | None = None,
        stale_core_record: VersionPackageRecord | None = None,
    ) -> DevUpdatePlan: ...


class ExecuteDevFn(Protocol):
    def __call__(
        self, plan: DevUpdatePlan, *, run: DevCommandRunner
    ) -> DevUpdateResult: ...


@dataclass(frozen=True)
class RestartInfo:
    """Axe restart outcome after a changed successful update."""

    attempted: bool
    status: RestartStatus
    pid: int | None = None
    message: str = ""
    reason: str | None = None


@dataclass(frozen=True)
class DevRoute:
    """Editable package records selected for the dev-update backend."""

    records: tuple[VersionPackageRecord, ...]
    host_record: VersionPackageRecord
    managed_requirements: tuple[Requirement, ...]
    managed_core_record: VersionPackageRecord | None = None
    #: Wheel-installed ``sase-core-rs`` found in a dev (editable-host) install.
    #: Dev installs always use the editable core build, so this record marks a
    #: clobbered environment the dev-update plan should restore rather than a
    #: package the managed leg may upgrade.
    stale_core_record: VersionPackageRecord | None = None


@dataclass(frozen=True)
class CombinedUpdateResult:
    """Aggregate outcome for one comprehensive editable/managed update."""

    dev_result: DevUpdateResult | None
    managed_summary: UpdateSummary | None
    elapsed: float

    @property
    def changed(self) -> bool:
        return bool(
            (self.dev_result is not None and self.dev_result.changed)
            or (self.managed_summary is not None and self.managed_summary.changed)
        )
