"""Registry construction and report assembly for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sase.core.paths import sase_home
from sase.diagnostics import DiagnosticRegistry, DiagnosticReport
from sase.version.inventory import (
    RuntimeVersionInventory,
    collect_runtime_version_inventory,
)


@dataclass
class DoctorContext:
    """Shared read-only context for one doctor run."""

    cwd: Path
    project: str | None
    sase_home: Path
    verbose: bool = False
    _runtime_inventory: RuntimeVersionInventory | None = field(
        default=None, init=False, repr=False
    )

    def get_runtime_inventory(self) -> RuntimeVersionInventory:
        """Return a cached runtime inventory for this doctor run."""
        if self._runtime_inventory is None:
            self._runtime_inventory = collect_runtime_version_inventory()
        return self._runtime_inventory


def default_doctor_context(
    *,
    project: str | None = None,
    verbose: bool = False,
) -> DoctorContext:
    """Build the default doctor context from the current process."""
    return DoctorContext(
        cwd=Path.cwd(),
        project=project,
        sase_home=sase_home(),
        verbose=verbose,
    )


def build_doctor_registry(context: DoctorContext) -> DiagnosticRegistry:
    """Return the Phase 2 doctor registry in stable order."""
    from sase.doctor.checks_config import config_check_specs
    from sase.doctor.checks_runtime import runtime_check_specs

    return DiagnosticRegistry(
        (*runtime_check_specs(context), *config_check_specs(context))
    )


def run_doctor(
    *,
    context: DoctorContext,
    registry: DiagnosticRegistry,
    selections: tuple[str, ...] = (),
    deep: bool = False,
    strict: bool = False,
) -> DiagnosticReport:
    """Run selected doctor checks and return the stable report model."""
    checks = registry.run(selections, include_deep=deep)
    return DiagnosticReport(
        checks=checks,
        cwd=str(context.cwd),
        project=context.project,
        sase_home=str(context.sase_home),
        deep=deep,
        strict=strict,
        selected_checks=selections,
    )


__all__ = [
    "DoctorContext",
    "build_doctor_registry",
    "default_doctor_context",
    "run_doctor",
]
