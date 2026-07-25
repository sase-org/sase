"""Initialize configured project sidecars and repository-local wiring."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from ._repo_init_config import (
    ConfigUpdate as _ConfigUpdate,
    configured_sidecar_specs as _configured_sidecar_specs_impl,
    explicit_sidecar_config_update as _explicit_sidecar_config_update_impl,
    format_roles as _format_roles_impl,
    materialized_compatibility_roles as _materialized_compatibility_roles_impl,
    project_provider_sdd_policy as _project_provider_sdd_policy_impl,
    repo_project_management as _repo_project_management_impl,
    sidecar_config_action_detail as _sidecar_config_action_detail_impl,
)
from ._repo_init_sidecars import (
    plan_legacy_store_actions as _plan_legacy_store_actions_impl,
    plan_sidecar_actions as _plan_sidecar_actions_impl,
    run_configured_sidecars as _run_configured_sidecars_impl,
    run_legacy_store_init as _run_legacy_store_init_impl,
    run_materialized_sidecars as _run_materialized_sidecars_impl,
)
from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory

if TYPE_CHECKING:
    from sase.project_management import ProjectManagementStatus
    from sase.sdd._sidecar_init import SidecarInitSpec

_NON_PROJECT_REPO_MESSAGE = "sase repo init: not a project directory (no VCS found); skipping repository initialization"
_UNMANAGED_REPO_MESSAGE = (
    "Repository initialization skipped: repository is not SASE-managed; set "
    "is_sase_managed: true in the target repository's sase/sase.yml to enable it"
)
_COMMAND_LABEL = "repo init"

# Keep the former private helper names available from this module. Besides making
# the move less disruptive, these forwarding seams let tests replace provider and
# sidecar discovery without reaching into the implementation modules.


def handle_repo_init_command(args: argparse.Namespace) -> None:
    """Handle ``sase repo init`` and its ``sase init repo`` alias."""

    raise SystemExit(run_repo_init(args))


def run_repo_init(args: argparse.Namespace) -> int:
    """Apply configured sidecar, plans-config, and ignore-rule initialization."""

    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="repo",
                    label="Repos",
                    plan=plan_repo_init,
                    run=run_repo_init,
                ),
            ),
        )

    project_root, management = _repo_project_management(getattr(args, "path", None))
    if not is_project_directory(project_root):
        print(_NON_PROJECT_REPO_MESSAGE, file=sys.stderr)
        return 1
    if management.error is not None:
        print(f"error: {management.error}", file=sys.stderr)
        return 1
    if not management.is_sase_managed:
        print(_UNMANAGED_REPO_MESSAGE)
        return 0

    plan = plan_repo_init(args)
    if plan.blockers:
        for blocker in plan.blockers:
            print(f"error: {blocker}", file=sys.stderr)
        return 1
    if getattr(args, "diff", False):
        from .init_preview import preview_console, render_plan_diff

        render_plan_diff(preview_console(sys.stdout), plan)

    changed_project_paths: list[Path] = []
    config_update = _explicit_sidecar_config_update(management.config_path)
    if config_update.error is not None:
        print(f"error: {config_update.error}", file=sys.stderr)
        return 1
    if config_update.changed:
        try:
            config_update.path.write_text(config_update.updated_text, encoding="utf-8")
        except OSError as exc:
            print(
                f"error: {config_update.path}: failed to write file: {exc}",
                file=sys.stderr,
            )
            return 1
        changed_project_paths.append(config_update.path)
        roles = _format_roles(config_update.added_roles)
        print(
            f"{_COMMAND_LABEL}: updated {config_update.path} with repos.sidecar {roles}"
        )

    try:
        policy = _project_provider_sdd_policy(project_root)
        if policy == "separate_repo":
            exit_code = _run_configured_sidecars(args, project_root)
        elif _has_materialized_sidecar_store(project_root):
            exit_code = _run_materialized_sidecars(project_root)
        else:
            exit_code = _run_legacy_store_init(project_root)
    except Exception as exc:  # noqa: BLE001 - provider and store failures are user-facing.
        from sase.sdd.store import SddMaterializationError

        if isinstance(exc, SddMaterializationError):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise
    if exit_code != 0:
        return exit_code

    from .init_workspace_handler import (
        commit_workspace_paths,
        ensure_workspace_gitignore,
        find_git_root,
    )

    changed_gitignore = ensure_workspace_gitignore(project_root)
    if changed_gitignore is not None:
        changed_project_paths.append(changed_gitignore)
        print(f"{_COMMAND_LABEL}: updated {changed_gitignore}")

    if not changed_project_paths or getattr(args, "no_commit", False):
        return 0
    git_root = find_git_root(project_root)
    if git_root is None:
        return 0
    return commit_workspace_paths(
        git_root,
        tuple(dict.fromkeys(changed_project_paths)),
        command_label=_COMMAND_LABEL,
        message="chore: initialize SASE repositories",
    )


def plan_repo_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for repository and sidecar initialization."""

    project_root, management = _repo_project_management(getattr(args, "path", None))
    if not is_project_directory(project_root):
        return InitPlan(
            command="repo",
            label="Repos",
            summary=_NON_PROJECT_REPO_MESSAGE,
            actions=(),
            blockers=(_NON_PROJECT_REPO_MESSAGE,),
        )
    if management.error is not None:
        return InitPlan(
            command="repo",
            label="Repos",
            summary="cannot determine whether the repository is SASE-managed",
            actions=(),
            blockers=(management.error,),
        )
    if not management.is_sase_managed:
        return InitPlan(
            command="repo",
            label="Repos",
            summary=_UNMANAGED_REPO_MESSAGE,
            actions=(),
            warnings=(_UNMANAGED_REPO_MESSAGE,),
        )

    actions: list[InitAction] = []
    warnings: list[str] = []
    blockers: list[str] = []

    config_update = _explicit_sidecar_config_update(management.config_path)
    if config_update.error is not None:
        blockers.append(config_update.error)
    elif config_update.changed:
        actions.append(
            InitAction(
                path=config_update.path,
                operation="update" if config_update.path.exists() else "create",
                detail=_sidecar_config_action_detail(config_update.added_roles),
                new_content=config_update.updated_text,
            )
        )

    policy = _project_provider_sdd_policy(project_root)
    if policy == "separate_repo" or _has_materialized_sidecar_store(project_root):
        from sase.sdd.store import SddMaterializationError

        specs = _configured_sidecar_specs(project_root)
        try:
            sidecar_actions, sidecar_warnings = _plan_sidecar_actions(
                project_root, specs
            )
        except SddMaterializationError as exc:
            blockers.append(str(exc))
        else:
            actions.extend(sidecar_actions)
            warnings.extend(sidecar_warnings)
    else:
        legacy_actions, legacy_warnings = _plan_legacy_store_actions(project_root)
        actions.extend(legacy_actions)
        warnings.extend(legacy_warnings)

    from .init_workspace_handler import plan_init_workspace

    workspace_args = argparse.Namespace(path=str(project_root))
    actions.extend(plan_init_workspace(workspace_args).actions)

    return InitPlan(
        command="repo",
        label="Repos",
        summary=_summarize_repo_actions(actions),
        actions=tuple(actions),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )


def _run_configured_sidecars(args: argparse.Namespace, project_root: Path) -> int:
    specs = _configured_sidecar_specs(project_root)
    return _run_configured_sidecars_impl(args, project_root, specs)


def _run_materialized_sidecars(project_root: Path) -> int:
    specs = _configured_sidecar_specs(project_root)
    recorded_roles = _materialized_compatibility_roles(project_root)
    return _run_materialized_sidecars_impl(
        project_root,
        specs,
        recorded_roles,
    )


def _run_legacy_store_init(project_root: Path) -> int:
    return _run_legacy_store_init_impl(project_root)


def _plan_legacy_store_actions(
    project_root: Path,
) -> tuple[list[InitAction], list[str]]:
    return _plan_legacy_store_actions_impl(project_root)


def _plan_sidecar_actions(
    project_root: Path,
    specs: tuple[SidecarInitSpec, ...],
) -> tuple[list[InitAction], list[str]]:
    recorded_roles = _materialized_compatibility_roles(project_root)
    return _plan_sidecar_actions_impl(
        project_root,
        specs,
        recorded_roles,
    )


def _configured_sidecar_specs(project_root: Path) -> tuple[SidecarInitSpec, ...]:
    return _configured_sidecar_specs_impl(project_root)


def _explicit_sidecar_config_update(config_path: Path) -> _ConfigUpdate:
    return _explicit_sidecar_config_update_impl(config_path)


def _sidecar_config_action_detail(roles: tuple[str, ...]) -> str:
    return _sidecar_config_action_detail_impl(roles)


def _format_roles(roles: tuple[str, ...]) -> str:
    return _format_roles_impl(roles)


def _repo_project_management(
    path: str | Path | None,
) -> tuple[Path, ProjectManagementStatus]:
    return _repo_project_management_impl(path)


def _project_provider_sdd_policy(project_root: Path) -> str | None:
    return _project_provider_sdd_policy_impl(project_root)


def _has_materialized_sidecar_store(project_root: Path) -> bool:
    return bool(_materialized_compatibility_roles(project_root))


def _materialized_compatibility_roles(project_root: Path) -> frozenset[str]:
    return _materialized_compatibility_roles_impl(project_root)


def _summarize_repo_actions(actions: list[InitAction]) -> str:
    if not actions:
        return "configured sidecars, project repo config, and ignore rules are current"
    details = " ".join(action.detail.casefold() for action in actions)
    parts: list[str] = []
    if "sidecar repository" in details:
        parts.append("create or connect configured sidecar repositories")
    if any(action.path.name == "README.md" for action in actions):
        parts.append("refresh sidecar guide files")
    if any(action.path.name == "sase.yml" for action in actions):
        parts.append("declare the plans, research, and agents sidecars")
    if any(action.path.name == ".gitignore" for action in actions):
        parts.append("update repository ignore rules")
    if not parts:
        return f"apply {len(actions)} repository initialization actions"
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


__all__ = [
    "handle_repo_init_command",
    "plan_repo_init",
    "run_repo_init",
]
