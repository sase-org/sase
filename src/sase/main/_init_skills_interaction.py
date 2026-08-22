"""Filesystem prompts and chezmoi deployment helpers for generated skills."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from sase.main._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    deploy_to_chezmoi as deploy_to_chezmoi_impl,
)
from sase.main._init_skills_manifest import ManagedSkillFile
from sase.main.init_plan import InitAction, InitPlan
from sase.workflows.commit.runtime_tags import resolve_runtime_workspace_tag


def retired_delete_action(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> InitAction:
    """Return the preview action for one retired managed skill file."""
    source_path = entry.source_path(chezmoi_home)
    home_path = entry.home_path(home_root)
    return InitAction(
        path=source_path,
        operation="delete",
        detail=f"{entry.provider}/{entry.skill_name} -> {home_path}",
    )


def delete_retired_source(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
) -> bool:
    """Delete the chezmoi source side of one retired generated skill."""
    source_path = entry.source_path(chezmoi_home)
    try:
        if source_path.exists():
            source_path.unlink()
        _prune_empty_dir(source_path.parent)
    except OSError as exc:
        print(f"  Warning: could not delete {source_path}: {exc}", file=sys.stderr)
        return False
    return True


def _prune_empty_dir(path: Path) -> None:
    """Remove *path* when it became empty, ignoring expected failures."""
    try:
        path.rmdir()
    except OSError:
        return


def prompt_overwrite(target: Path, new_content: str) -> bool:
    """Interactively prompt about overwriting an existing generated skill."""
    existing = target.read_text(encoding="utf-8")
    if existing == new_content:
        print(f"  {target} (unchanged, skipping)")
        return False

    while True:
        try:
            answer = input(f"  {target} exists. Overwrite? [y/n/d] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False

        if answer == "y":
            return True
        if answer == "n":
            return False
        if answer == "d":
            from .init_preview import preview_console, render_plan_diff

            render_plan_diff(
                preview_console(sys.stdout),
                InitPlan(
                    command="skills",
                    label="Skills",
                    summary="",
                    actions=(
                        InitAction(
                            path=target,
                            operation="overwrite",
                            new_content=new_content,
                        ),
                    ),
                ),
            )


def prompt_delete_retired(
    entry: ManagedSkillFile,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> bool:
    """Interactively prompt for deleting one retired source/live pair."""
    source_path = entry.source_path(chezmoi_home)
    home_path = entry.home_path(home_root)
    while True:
        try:
            answer = (
                input(
                    f"  {source_path} is retired; live target {home_path}. Delete? [y/n/d] "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return False

        if answer == "y":
            return True
        if answer == "n":
            return False
        if answer == "d":
            from .init_preview import preview_console, render_plan_diff

            render_plan_diff(
                preview_console(sys.stdout),
                InitPlan(
                    command="skills",
                    label="Skills",
                    summary="",
                    actions=(
                        retired_delete_action(
                            entry,
                            chezmoi_home=chezmoi_home,
                            home_root=home_root,
                        ),
                    ),
                ),
            )


def skill_deploy_commit_tags(source_commit: str | None) -> dict[str, object]:
    """Return provenance tags for a generated-skill deployment commit."""
    tags: dict[str, object] = {}
    if source_commit:
        tags["SOURCE_REVISION"] = source_commit
    workspace = resolve_runtime_workspace_tag()
    if workspace:
        tags["WORKSPACE"] = workspace
    return tags


def deploy_to_chezmoi(
    written_paths: list[Path],
    args: argparse.Namespace,
    *,
    command_label: str,
    chezmoi_home: Path,
    source_commit: str | None = None,
    delete_targets: Sequence[Path] = (),
) -> int:
    """Deploy written generated-skill paths through chezmoi."""
    no_commit: bool = getattr(args, "no_commit", False)
    no_push: bool = getattr(args, "no_push", False)
    no_apply: bool = getattr(args, "no_apply", False)
    provider_filter: str | None = getattr(args, "provider", None)

    message = "chore: regenerate skills via sase skill init"
    if provider_filter:
        message = f"chore: regenerate {provider_filter} skills via sase skill init"

    return deploy_to_chezmoi_impl(
        written_paths,
        ChezmoiDeployBehavior(
            command_label=command_label,
            commit_message=message,
            auto_commit_type="skills",
            chezmoi_home=chezmoi_home,
            no_commit=no_commit,
            no_push=no_push,
            no_apply=no_apply,
            commit_tags=skill_deploy_commit_tags(source_commit),
            include_runtime_commit_tags=True,
            git_failure_is_error=False,
            chezmoi_missing_is_error=False,
            git_missing_suffix=", skipping deploy",
            not_repo_suffix=", skipping deploy",
            delete_targets=tuple(delete_targets),
            delete_target_root=Path.home(),
        ),
    )


def deferred_skill_deploy_warnings(
    pending_count: int, integrity_error: str | None
) -> tuple[str, ...]:
    """Return ``--check`` warnings for deferred generated-skill drift."""
    noun = "provider skill file" if pending_count == 1 else "provider skill files"
    warning = (
        f"{pending_count} {noun} out of sync with rendered sources; redeploy is "
        "deferred until land. Rerun `sase init skills` after landing."
    )
    if integrity_error is None:
        return (warning,)
    return (warning, integrity_error)
