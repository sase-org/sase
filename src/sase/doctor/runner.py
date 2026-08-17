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
    env: dict[str, str] = field(default_factory=dict)
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
    import os

    return DoctorContext(
        cwd=Path.cwd(),
        project=project,
        sase_home=sase_home(),
        verbose=verbose,
        env=dict(os.environ),
    )


def build_doctor_registry(context: DoctorContext) -> DiagnosticRegistry:
    """Return the default doctor registry in stable order."""
    from sase.doctor.checks_agent_index import agent_index_check_specs
    from sase.doctor.checks_agent_publication import agent_publication_check_specs
    from sase.doctor.checks_agent_publication_digest import (
        agent_publication_digest_check_specs,
    )
    from sase.doctor.checks_axe import axe_check_specs
    from sase.doctor.checks_external_pr_mirror import (
        external_pr_mirror_check_specs,
    )
    from sase.doctor.checks_project_spec_duplicates import (
        project_spec_duplicate_check_specs,
    )
    from sase.doctor.checks_beads import bead_check_specs
    from sase.doctor.checks_completion import completion_check_specs
    from sase.doctor.checks_flags import flag_check_specs
    from sase.doctor.checks_changespec_refs import (  # legacy module path
        patch_ref_check_specs,
    )
    from sase.doctor.checks_config import config_check_specs
    from sase.doctor.checks_deep import deep_check_specs
    from sase.doctor.checks_external_mirror import external_mirror_check_specs
    from sase.doctor.checks_integrations import integration_check_specs
    from sase.doctor.checks_plugins import plugin_check_specs
    from sase.doctor.checks_project import project_check_specs
    from sase.doctor.checks_providers import provider_check_specs
    from sase.doctor.checks_resources import resource_check_specs
    from sase.doctor.checks_runtime import runtime_check_specs
    from sase.doctor.checks_telemetry import telemetry_check_specs
    from sase.doctor.checks_tools import tools_check_specs
    from sase.doctor.checks_workspace import workspace_check_specs

    return DiagnosticRegistry(
        (
            *runtime_check_specs(context),
            *config_check_specs(context),
            *provider_check_specs(context),
            *plugin_check_specs(context),
            *resource_check_specs(context),
            *axe_check_specs(context),
            *external_mirror_check_specs(context),
            *external_pr_mirror_check_specs(context),
            *project_spec_duplicate_check_specs(context),
            *project_check_specs(context),
            *patch_ref_check_specs(context),
            *workspace_check_specs(context),
            *agent_index_check_specs(context),
            *agent_publication_check_specs(context),
            *agent_publication_digest_check_specs(context),
            *bead_check_specs(context),
            *completion_check_specs(context),
            *flag_check_specs(context),
            *telemetry_check_specs(context),
            *integration_check_specs(context),
            *deep_check_specs(context),
            *tools_check_specs(context),
        )
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
