"""Public facade for ``sase skill init`` and its ``sase init skills`` alias."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import shutil
import sys

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.main._init_skills_apply import run_init_skills as _run_init_skills_impl
from sase.main._init_skills_interaction import (
    deferred_skill_deploy_warnings as _deferred_skill_deploy_warnings_impl,
    delete_retired_source as _delete_retired_source_impl,
    deploy_to_chezmoi as _deploy_to_chezmoi_impl,
    prompt_delete_retired as _prompt_delete_retired_impl,
    prompt_overwrite as _prompt_overwrite_impl,
    retired_delete_action as _retired_delete_action_impl,
    skill_deploy_commit_tags as _skill_deploy_commit_tags_impl,
)
from sase.main._init_skills_manifest import ManagedSkillFile, prepare_skill_manifest
from sase.main._init_skills_plan import plan_init_skills as _plan_init_skills_impl
from sase.main._init_skills_rendering import (
    RenderedSkillDeploymentTarget,
    RenderedSkillTarget,
    format_skill_output as _format_skill_output_impl,
    format_skill_outputs as _format_skill_outputs_impl,
    format_unique_skill_outputs_batch as _format_unique_skill_outputs_batch_impl,
    planned_skill_operation as _planned_skill_operation_impl,
    render_skill_deployment_targets as _render_skill_deployment_targets_impl,
    render_skill_targets as _render_skill_targets_impl,
    summarize_skill_actions as _summarize_skill_actions_impl,
)
from sase.main._init_skills_runtime import InitSkillsRuntime
from sase.main._init_skills_sources import (
    all_providers as _all_providers_impl,
    provider_context as _provider_context_impl,
    select_skill_xprompts as _select_skill_xprompts,
    skill_deploy_subpaths as _skill_deploy_subpaths_impl,
    target_path_for_subpath as _target_path_for_subpath_impl,
)
from sase.main._init_skills_source_integrity import skill_source_integrity_error
from sase.main.init_plan import InitAction, InitOperation, InitPlan
from sase.xprompt.load_issues import collect_xprompt_load_issues
from sase.xprompt.loader import get_all_xprompts, load_skills_from_package
from sase.xprompt.loader_skills import SKILL_PLACEMENT_ISSUE_KIND
from sase.xprompt.models import XPrompt

_COMMAND_LABEL = "skill init"
_PRETTIER_WARNING = (
    f"{_COMMAND_LABEL}: prettier not found on PATH; output may not match "
    "chezmoi CI formatting"
)
_DELETE_WARNING = (
    "  Warning: retired generated skill exists, skipping delete "
    "(not a TTY; use -f to force or -y to answer yes)"
)
_RenderedSkillTarget = RenderedSkillTarget
_RenderedSkillDeploymentTarget = RenderedSkillDeploymentTarget


def _all_providers() -> list[str]:
    """Return every registered provider name from ``sase_llm`` entry points."""
    return _all_providers_impl()


def _registered_provider_names() -> tuple[str, ...]:
    """Return registered provider names in registry order."""
    return tuple(_all_providers())


def registered_provider_names() -> tuple[str, ...]:
    """Return registered provider names in registry order."""
    return _registered_provider_names()


def _provider_validation_error(provider: str | None) -> str | None:
    """Return an error for an unknown provider filter, if any."""
    if provider is None:
        return None
    registered = _registered_provider_names()
    if provider in registered:
        return None
    names = ", ".join(registered) if registered else "(none)"
    return f"unknown provider {provider!r}; registered providers: {names}"


def _provider_context(provider: str) -> dict[str, str]:
    """Return the Jinja2 rendering context a plugin supplies for its SKILL.md."""
    return _provider_context_impl(provider)


def _skill_deploy_subpaths(provider: str) -> list[str]:
    """Return deployment subdirectories for *provider*."""
    return _skill_deploy_subpaths_impl(provider)


def _skill_deploy_subpath(provider: str) -> str:
    """Return the primary skill deployment subdirectory for *provider*."""
    return _skill_deploy_subpaths(provider)[0]


def _get_target_providers(skill_field: bool | list[str]) -> list[str]:
    """Return the list of providers a skill should be deployed to."""
    known = [
        provider for provider in _all_providers() if _skill_deploy_subpaths(provider)
    ]
    if skill_field is True:
        return list(known)
    if isinstance(skill_field, list):
        return [provider for provider in skill_field if provider in known]
    return []


def _target_path_for_subpath(subpath: str, skill_name: str, use_chezmoi: bool) -> Path:
    """Return the deployment path for one skill subpath."""
    return _target_path_for_subpath_impl(
        subpath,
        skill_name,
        use_chezmoi=use_chezmoi,
        chezmoi_home=CHEZMOI_HOME,
    )


def _get_target_path(provider: str, skill_name: str, use_chezmoi: bool) -> Path:
    """Return the primary deployment path for a skill file."""
    return _target_path_for_subpath(
        _skill_deploy_subpath(provider), skill_name, use_chezmoi
    )


def _get_target_paths(provider: str, skill_name: str, use_chezmoi: bool) -> list[Path]:
    """Return every deployment path for a provider skill file."""
    primary = _get_target_path(provider, skill_name, use_chezmoi)
    extras = [
        _target_path_for_subpath(subpath, skill_name, use_chezmoi)
        for subpath in _skill_deploy_subpaths(provider)[1:]
    ]
    return [primary, *extras]


def _load_skill_sources() -> tuple[list[XPrompt], tuple[str, ...]]:
    """Return installable skill sources and placement rule violations."""
    with collect_xprompt_load_issues() as issues:
        selected = _select_skill_xprompts(
            dict(load_skills_from_package()),
            get_all_xprompts(project=""),
        )
    placement_errors = tuple(
        dict.fromkeys(
            issue.error for issue in issues if issue.kind == SKILL_PLACEMENT_ISSUE_KIND
        )
    )
    return selected, placement_errors


def prettier_available() -> bool:
    """Return whether generated Markdown can be formatted with prettier."""
    return _prettier_available()


def load_skill_sources() -> tuple[list[XPrompt], tuple[str, ...]]:
    """Return installable skill sources plus placement rule violations."""
    return _load_skill_sources()


def get_skill_target_providers(skill_field: bool | list[str]) -> list[str]:
    """Return providers a skill should be deployed to."""
    return _get_target_providers(skill_field)


def _prettier_available() -> bool:
    """Return whether generated Markdown can be formatted with prettier."""
    return shutil.which("prettier") is not None


def _format_skill_output(output: str, *, use_prettier: bool) -> str:
    """Format generated skill Markdown with the same path used by apply."""
    return _format_skill_output_impl(output, use_prettier=use_prettier)


def _format_unique_skill_outputs_batch(outputs: Sequence[str]) -> list[str]:
    """Format unique generated skill Markdown bodies with one Prettier command."""
    return _format_unique_skill_outputs_batch_impl(outputs)


def _format_skill_outputs(outputs: Sequence[str], *, use_prettier: bool) -> list[str]:
    """Format generated skill Markdown once per unique raw output."""
    return _format_skill_outputs_impl(
        outputs,
        use_prettier=use_prettier,
        batch_formatter=_format_unique_skill_outputs_batch,
        single_formatter=lambda output: _format_skill_output(output, use_prettier=True),
    )


def _render_skill_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_chezmoi: bool,
    use_prettier: bool,
) -> list[RenderedSkillTarget]:
    """Render every selected skill/provider target without writing files."""
    return _render_skill_targets_impl(
        skill_xprompts,
        provider_filter=provider_filter,
        use_chezmoi=use_chezmoi,
        get_target_providers=_get_target_providers,
        get_provider_context=_provider_context,
        get_target_paths=_get_target_paths,
        format_outputs=lambda outputs: _format_skill_outputs(
            outputs, use_prettier=use_prettier
        ),
    )


def _render_skill_deployment_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_prettier: bool,
) -> list[RenderedSkillDeploymentTarget]:
    """Render selected generated skill targets paired for source/home deploy."""
    return _render_skill_deployment_targets_impl(
        skill_xprompts,
        provider_filter=provider_filter,
        get_target_providers=_get_target_providers,
        get_provider_context=_provider_context,
        get_target_paths=_get_target_paths,
        format_outputs=lambda outputs: _format_skill_outputs(
            outputs, use_prettier=use_prettier
        ),
    )


def render_skill_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_chezmoi: bool,
    use_prettier: bool,
) -> list[RenderedSkillTarget]:
    """Render every selected skill/provider target without writing files."""
    return _render_skill_targets(
        skill_xprompts,
        provider_filter=provider_filter,
        use_chezmoi=use_chezmoi,
        use_prettier=use_prettier,
    )


def render_skill_deployment_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_prettier: bool,
) -> list[RenderedSkillDeploymentTarget]:
    """Render selected generated skill targets paired for source/home deploy."""
    return _render_skill_deployment_targets(
        skill_xprompts,
        provider_filter=provider_filter,
        use_prettier=use_prettier,
    )


def _planned_skill_operation(
    target: RenderedSkillTarget,
) -> tuple[InitOperation, str] | None:
    """Return planned operation/detail for a skill target, or ``None``."""
    return _planned_skill_operation_impl(target)


def planned_skill_operation(
    target: RenderedSkillTarget,
) -> tuple[InitOperation, str] | None:
    """Return planned operation/detail for a skill target, or ``None``."""
    return _planned_skill_operation(target)


def _summarize_skill_actions(actions: tuple[InitAction, ...]) -> str:
    """Return a compact summary for generated skill actions."""
    return _summarize_skill_actions_impl([action.operation for action in actions])


def _retired_delete_action(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> InitAction:
    return _retired_delete_action_impl(
        entry, chezmoi_home=chezmoi_home, home_root=home_root
    )


def _delete_retired_source(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
) -> bool:
    return _delete_retired_source_impl(entry, chezmoi_home=chezmoi_home)


def _prompt_overwrite(target: Path, new_content: str) -> bool:
    return _prompt_overwrite_impl(target, new_content)


def _prompt_delete_retired(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> bool:
    return _prompt_delete_retired_impl(
        entry, chezmoi_home=chezmoi_home, home_root=home_root
    )


def _skill_deploy_commit_tags(source_commit: str | None) -> dict[str, object]:
    return _skill_deploy_commit_tags_impl(source_commit)


def _deploy_to_chezmoi(
    written_paths: list[Path],
    args: argparse.Namespace,
    *,
    source_commit: str | None = None,
    delete_targets: Sequence[Path] = (),
) -> int:
    """Deploy written generated-skill paths through chezmoi."""
    return _deploy_to_chezmoi_impl(
        written_paths,
        args,
        command_label=_COMMAND_LABEL,
        chezmoi_home=CHEZMOI_HOME,
        source_commit=source_commit,
        delete_targets=delete_targets,
    )


def _deferred_skill_deploy_warnings(
    pending_count: int, integrity_error: str | None
) -> tuple[str, ...]:
    return _deferred_skill_deploy_warnings_impl(pending_count, integrity_error)


def _runtime() -> InitSkillsRuntime:
    """Return this module through the typed workflow boundary."""
    return InitSkillsRuntime(
        chezmoi_home=CHEZMOI_HOME,
        command_label=_COMMAND_LABEL,
        prettier_warning=_PRETTIER_WARNING,
        delete_warning=_DELETE_WARNING,
        get_use_chezmoi=get_use_chezmoi,
        provider_validation_error=_provider_validation_error,
        load_skill_sources=_load_skill_sources,
        prettier_available=_prettier_available,
        render_skill_deployment_targets=_render_skill_deployment_targets,
        render_skill_targets=_render_skill_targets,
        registered_provider_names=_registered_provider_names,
        planned_skill_operation=_planned_skill_operation,
        summarize_skill_actions=_summarize_skill_actions,
        retired_delete_action=_retired_delete_action,
        prompt_overwrite=_prompt_overwrite,
        prompt_delete_retired=_prompt_delete_retired,
        delete_retired_source=_delete_retired_source,
        skill_deploy_commit_tags=_skill_deploy_commit_tags,
        deploy_to_chezmoi=_deploy_to_chezmoi,
        deferred_skill_deploy_warnings=_deferred_skill_deploy_warnings,
        skill_source_integrity_error=skill_source_integrity_error,
        prepare_skill_manifest=prepare_skill_manifest,
        plan_init_skills=plan_init_skills,
        run_init_skills=run_init_skills,
    )


def plan_init_skills(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for generated provider skill files."""
    return _plan_init_skills_impl(args, runtime=_runtime())


def run_init_skills(args: argparse.Namespace) -> int:
    """Apply ``sase init skills`` and return a process exit code."""
    return _run_init_skills_impl(args, runtime=_runtime())


def handle_init_skills_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init skills``."""
    sys.exit(run_init_skills(args))
