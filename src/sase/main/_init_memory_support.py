"""Shared planning inputs and root-plan helpers for ``sase memory init``."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi
from sase.content_layout import LayoutCollisionError
from sase.memory.web import (
    MemoryWeb,
    cross_scope_keyword_warnings,
    discover_memory_webs,
    validate_memory_webs,
)
from sase.project_management import project_management_status

from .init_memory.config import (
    linked_entries_from_config,
    primary_workspace_root_for_memory,
    project_config_read_path,
    project_memory_name,
)
from .init_memory.constants import COMMAND_LABEL
from .init_memory.models import LinkedRepoMemoryEntry, MemoryRootPlan
from .init_memory.roots import plan_memory_root
from .init_memory.staleness import workspace_pinned_sase_mismatch_warning
from .init_project_scope import is_project_directory


@dataclass(frozen=True)
class _MemoryInitInputs:
    use_chezmoi: bool
    no_commit: bool
    is_project_dir: bool
    is_sase_managed: bool
    global_config: Path
    project_root: Path
    home_root: Path
    project_name: str | None
    project_entries: tuple[LinkedRepoMemoryEntry, ...]
    home_entries: tuple[LinkedRepoMemoryEntry, ...]
    config_errors: tuple[str, ...]


def _home_root_path(use_chezmoi: bool) -> Path:
    """Return the home-level root for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME
    return Path.home()


def _global_config_path(use_chezmoi: bool) -> Path:
    """Return the global config source path for the active config mode."""
    if use_chezmoi:
        return CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    return CONFIG_DIR / "sase.yml"


def _required_plugin_errors(config_path: Path) -> tuple[str, ...]:
    """Return ``plugins.required`` blockers before any memory drift comparison."""
    from sase.plugins.required import (
        RequiredPluginError,
        fail_closed_required_plugins,
        required_plugin_blockers,
        resolve_required_plugins,
    )
    from sase.project_management import load_local_config

    loaded = load_local_config(config_path)
    if not loaded.valid:
        return ()
    report = resolve_required_plugins(loaded.config)
    try:
        fail_closed_required_plugins(report)
    except RequiredPluginError:
        return required_plugin_blockers(loaded.config, command_label=COMMAND_LABEL)
    return ()


def load_memory_inputs(args: argparse.Namespace) -> _MemoryInitInputs:
    """Collect config, project, and home inputs for memory init planning."""
    use_chezmoi = get_use_chezmoi()
    project_root = Path.cwd()
    is_project_dir = is_project_directory(project_root)
    primary_root = primary_workspace_root_for_memory(project_root)
    project_config = project_config_read_path()
    global_config = _global_config_path(use_chezmoi)

    project_entries: tuple[LinkedRepoMemoryEntry, ...]
    project_errors: tuple[str, ...]
    project_name: str | None = None
    plugin_errors: tuple[str, ...] = ()
    if is_project_dir:
        management = project_management_status(project_config)
        project_managed = management.is_sase_managed
        plugin_errors = _required_plugin_errors(project_config)
        if management.error is not None:
            project_entries = ()
            project_errors = (management.error,)
        elif project_managed:
            project_name = project_memory_name(project_root)
            project_entries, project_errors = linked_entries_from_config(
                project_config,
                label="project",
                primary_root=primary_root,
                project_name=project_name,
            )
        else:
            project_entries = ()
            project_errors = ()
    else:
        project_managed = False
        project_entries = ()
        project_errors = ()
    home_entries, home_errors = linked_entries_from_config(
        global_config, label="home", primary_root=primary_root
    )
    config_errors = (*plugin_errors, *project_errors, *home_errors)
    if config_errors or not is_project_dir or not project_managed:
        project_name = None
    return _MemoryInitInputs(
        use_chezmoi=use_chezmoi,
        no_commit=bool(getattr(args, "no_commit", False)),
        is_project_dir=is_project_dir,
        is_sase_managed=project_managed,
        global_config=global_config,
        project_root=project_root,
        home_root=_home_root_path(use_chezmoi),
        project_name=project_name,
        project_entries=project_entries,
        home_entries=home_entries,
        config_errors=config_errors,
    )


def memory_root_plans(inputs: _MemoryInitInputs) -> tuple[MemoryRootPlan, ...]:
    """Return project (optional) and home memory root plans for *inputs*."""
    chezmoi_home_roots = (inputs.home_root,) if inputs.use_chezmoi else ()
    root_plans: list[MemoryRootPlan] = []
    if inputs.is_project_dir:
        root_plans.append(
            plan_memory_root(
                inputs.project_root,
                inputs.project_entries,
                project_name=inputs.project_name,
                manage_memory=inputs.is_sase_managed,
                enable_amd=True,
                derive_project_title=inputs.is_sase_managed,
                chezmoi_home_roots=chezmoi_home_roots,
                include_project_agent_docs=True,
                include_project_memory=True,
            )
        )
    home_plan = plan_memory_root(
        inputs.home_root,
        inputs.home_entries,
        enable_amd=True,
        chezmoi_home_roots=chezmoi_home_roots,
    )
    root_plans.append(home_plan)
    return tuple(root_plans)


def memory_root_plan_warnings(
    root_plans: Iterable[MemoryRootPlan],
) -> tuple[str, ...]:
    """Return warnings collected from each planned memory root."""
    return tuple(warning for root_plan in root_plans for warning in root_plan.warnings)


def memory_plan_warnings(inputs: _MemoryInitInputs) -> tuple[str, ...]:
    """Return workspace and cross-scope warnings for the planned roots."""
    warnings: list[str] = []
    if inputs.is_project_dir:
        warning = workspace_pinned_sase_mismatch_warning(inputs.project_root)
        if warning is not None:
            warnings.append(warning)
    warnings.extend(_memory_web_scope_warnings(inputs))
    return tuple(warnings)


def _memory_web_scope_warnings(inputs: _MemoryInitInputs) -> tuple[str, ...]:
    project_webs: tuple[MemoryWeb, ...] = ()
    if inputs.is_project_dir and inputs.is_sase_managed:
        try:
            project_discovery = discover_memory_webs(inputs.project_root)
        except LayoutCollisionError:
            project_discovery = None
        if project_discovery is not None:
            project_report = validate_memory_webs(project_discovery)
            if not project_report.blockers:
                project_webs = project_discovery.webs
    try:
        home_discovery = discover_memory_webs(inputs.home_root)
    except LayoutCollisionError:
        return ()
    home_report = validate_memory_webs(home_discovery)
    if home_report.blockers:
        return ()
    return cross_scope_keyword_warnings(
        project_webs=project_webs,
        home_webs=home_discovery.webs,
    )
