"""Read-only planning workflow for generated provider skills."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.main._init_skills_manifest import (
    plan_skill_manifest_ownership,
    retired_skill_files_with_drift,
)
from sase.main._init_skills_rendering import SkillFrameTemplateError
from sase.main._init_skills_runtime import InitSkillsRuntime
from sase.main.init_plan import InitAction, InitPlan


def plan_init_skills(
    args: argparse.Namespace,
    *,
    runtime: InitSkillsRuntime,
) -> InitPlan:
    """Return a read-only plan for generated provider skill files."""
    use_chezmoi = runtime.get_use_chezmoi()
    provider_filter: str | None = getattr(args, "provider", None)
    provider_error = runtime.provider_validation_error(provider_filter)
    if provider_error is not None:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="cannot plan generated skill files until provider is valid",
            actions=(),
            blockers=(provider_error,),
        )

    skill_xprompts, placement_errors = runtime.load_skill_sources()
    if placement_errors:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="cannot plan generated skill files from a misplaced source set",
            actions=(),
            blockers=placement_errors,
        )

    use_prettier = runtime.prettier_available()
    try:
        if use_chezmoi:
            deployment_targets = runtime.render_skill_deployment_targets(
                skill_xprompts,
                provider_filter=provider_filter,
                use_prettier=use_prettier,
            )
            targets = [target.source_target() for target in deployment_targets]
            ownership_plan, ownership_error = plan_skill_manifest_ownership(
                deployment_targets,
                chezmoi_home=runtime.chezmoi_home,
                home_root=Path.home(),
                provider_filter=provider_filter,
                registered_providers=runtime.registered_provider_names(),
            )
            if ownership_error is not None:
                return InitPlan(
                    command="skills",
                    label="Skills",
                    summary="cannot plan generated skill files until the manifest is fixed",
                    actions=(),
                    blockers=(ownership_error,),
                )
            assert ownership_plan is not None
            retired_entries = retired_skill_files_with_drift(
                ownership_plan.retired_entries,
                chezmoi_home=runtime.chezmoi_home,
                home_root=Path.home(),
            )
        else:
            targets = runtime.render_skill_targets(
                skill_xprompts,
                provider_filter=provider_filter,
                use_chezmoi=use_chezmoi,
                use_prettier=use_prettier,
            )
            retired_entries = ()
    except (SkillFrameTemplateError, ValueError) as exc:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="cannot plan generated skill files until the frame template is fixed",
            actions=(),
            blockers=(str(exc),),
        )

    actions: list[InitAction] = []
    for target in targets:
        planned = runtime.planned_skill_operation(target)
        if planned is None:
            continue
        operation, detail = planned
        actions.append(
            InitAction(
                path=target.path,
                operation=operation,
                detail=detail,
                new_content=target.content,
            )
        )
    if use_chezmoi:
        actions.extend(
            runtime.retired_delete_action(
                entry,
                chezmoi_home=runtime.chezmoi_home,
                home_root=Path.home(),
            )
            for entry in retired_entries
        )

    warnings: list[str] = []
    if targets and not use_prettier:
        warnings.append(runtime.prettier_warning)

    if use_chezmoi and actions and getattr(args, "check", False):
        integrity_error = runtime.skill_source_integrity_error()
        warnings.extend(
            runtime.deferred_skill_deploy_warnings(len(actions), integrity_error)
        )
        actions = []

    return InitPlan(
        command="skills",
        label="Skills",
        summary=runtime.summarize_skill_actions(tuple(actions)),
        actions=tuple(actions),
        warnings=tuple(warnings),
    )
