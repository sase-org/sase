"""Apply workflow for generated provider skills."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
import sys

from sase.main._init_chezmoi_deploy import (
    chezmoi_deploy_lock,
    defer_chezmoi_paths,
    print_chezmoi_deploy_lock_timeout,
)
from sase.main._init_skills_manifest import (
    ManagedSkillFile,
    plan_skill_manifest_ownership,
    retired_skill_files_with_drift,
)
from sase.main._init_skills_rendering import (
    RenderedSkillTarget,
    SkillFrameTemplateError,
)
from sase.main._init_skills_runtime import InitSkillsRuntime
from sase.main.init_plan import InitAction, InitPlan
from sase.memory.locks import LockTimeoutError


def run_init_skills(
    args: argparse.Namespace,
    *,
    runtime: InitSkillsRuntime,
) -> int:
    """Apply ``sase init skills`` and return a process exit code."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="skills",
                    label="Skills",
                    plan=runtime.plan_init_skills,
                    run=runtime.run_init_skills,
                ),
            ),
        )

    use_chezmoi = runtime.get_use_chezmoi()
    is_tty = sys.stdin.isatty()
    provider_filter: str | None = getattr(args, "provider", None)
    force: bool = getattr(args, "force", False)
    assume_yes: bool = getattr(args, "yes", False)
    dry_run: bool = getattr(args, "dry_run", False)

    provider_error = runtime.provider_validation_error(provider_filter)
    if provider_error is not None:
        print(f"{runtime.command_label}: {provider_error}", file=sys.stderr)
        return 2

    skill_xprompts, placement_errors = runtime.load_skill_sources()
    if placement_errors:
        for error in placement_errors:
            print(f"{runtime.command_label}: {error}", file=sys.stderr)
        return 1

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
                print(f"{runtime.command_label}: {ownership_error}", file=sys.stderr)
                return 1
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
            deployment_targets = []
            retired_entries = ()
    except (SkillFrameTemplateError, ValueError) as exc:
        print(f"{runtime.command_label}: {exc}", file=sys.stderr)
        return 1
    if targets and not use_prettier:
        print(runtime.prettier_warning, file=sys.stderr)

    if getattr(args, "diff", False):
        return _render_diff(runtime, targets, retired_entries, use_chezmoi=use_chezmoi)

    deploy_lock_stack = _acquire_deploy_lock(runtime, use_chezmoi, dry_run)
    if deploy_lock_stack is False:
        return 1

    has_changes = any(
        runtime.planned_skill_operation(target) is not None for target in targets
    ) or bool(retired_entries)
    manifest_write = None
    if use_chezmoi and not dry_run:
        manifest_write, manifest_error = runtime.prepare_skill_manifest(
            skill_xprompts,
            chezmoi_home=runtime.chezmoi_home,
            force=force,
            current_targets=deployment_targets,
            provider_filter=provider_filter,
            registered_providers=runtime.registered_provider_names(),
            home_root=Path.home(),
        )
        if manifest_error is not None:
            print(f"{runtime.command_label}: {manifest_error}", file=sys.stderr)
            _close_lock(deploy_lock_stack)
            return 1

    manifest_changed = manifest_write is not None and manifest_write.content is not None
    allow_dirty: bool = getattr(args, "allow_dirty", False)
    if (
        use_chezmoi
        and not dry_run
        and (has_changes or manifest_changed)
        and not allow_dirty
    ):
        source_error = runtime.skill_source_integrity_error()
        if source_error is not None:
            print(f"{runtime.command_label}: {source_error}", file=sys.stderr)
            _close_lock(deploy_lock_stack)
            return 1

    written = 0
    deleted = 0
    skipped = 0
    unchanged = 0
    written_paths: list[Path] = []
    live_delete_targets: list[Path] = []

    for target in targets:
        planned = runtime.planned_skill_operation(target)
        if planned is None:
            unchanged += 1
            continue

        if dry_run:
            operation, _detail = planned
            print(f"  {operation}: {target.path}")
            continue

        if target.path.exists() and not force and not assume_yes:
            if not is_tty:
                print(
                    f"  Warning: {target.path} exists, skipping "
                    "(not a TTY; use -f to force or -y to answer yes)",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            if not runtime.prompt_overwrite(target.path, target.content):
                skipped += 1
                continue

        target.path.parent.mkdir(parents=True, exist_ok=True)
        target.path.write_text(target.content, encoding="utf-8")
        print(f"  {target.path}")
        written += 1
        written_paths.append(target.path)

    if use_chezmoi:
        for entry in retired_entries:
            source_path = entry.source_path(runtime.chezmoi_home)
            home_path = entry.home_path(Path.home())
            if dry_run:
                print(f"  delete: {source_path} -> {home_path}")
                continue

            if not force and not assume_yes:
                if not is_tty:
                    print(
                        f"{runtime.delete_warning}: {source_path} -> {home_path}",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue
                if not runtime.prompt_delete_retired(
                    entry,
                    chezmoi_home=runtime.chezmoi_home,
                    home_root=Path.home(),
                ):
                    skipped += 1
                    continue

            if not runtime.delete_retired_source(
                entry, chezmoi_home=runtime.chezmoi_home
            ):
                skipped += 1
                continue
            print(f"  deleted: {source_path}")
            deleted += 1
            written_paths.append(source_path)
            live_delete_targets.append(home_path)

    if manifest_changed and skipped == 0 and manifest_write is not None:
        manifest_content = manifest_write.content
        assert manifest_content is not None
        manifest_write.path.parent.mkdir(parents=True, exist_ok=True)
        manifest_write.path.write_text(manifest_content, encoding="utf-8")
        print(f"  {manifest_write.path}")
        written_paths.append(manifest_write.path)

    _print_summary(
        dry_run=dry_run,
        source_count=len(skill_xprompts),
        written=written,
        deleted=deleted,
        skipped=skipped,
        unchanged=unchanged,
    )

    exit_code = 0
    if use_chezmoi and not dry_run and (written_paths or live_delete_targets):
        source_commit = manifest_write.source_commit if manifest_write else None
        commit_tags = runtime.skill_deploy_commit_tags(source_commit)
        if not defer_chezmoi_paths(
            written_paths,
            chezmoi_home=runtime.chezmoi_home,
            commit_tags=commit_tags,
            include_runtime_commit_tags=True,
            delete_targets=live_delete_targets,
            delete_target_root=Path.home(),
        ):
            exit_code = runtime.deploy_to_chezmoi(
                written_paths,
                args,
                source_commit=source_commit,
                delete_targets=live_delete_targets,
            )

    _close_lock(deploy_lock_stack)
    return exit_code


def _render_diff(
    runtime: InitSkillsRuntime,
    targets: Sequence[RenderedSkillTarget],
    retired_entries: Sequence[ManagedSkillFile],
    *,
    use_chezmoi: bool,
) -> int:
    from .init_preview import preview_console, render_plan_diff

    preview_actions: list[InitAction] = []
    for target in targets:
        planned = runtime.planned_skill_operation(target)
        if planned is None:
            continue
        operation, detail = planned
        preview_actions.append(
            InitAction(
                path=target.path,
                operation=operation,
                detail=detail,
                new_content=target.content,
            )
        )
    if use_chezmoi:
        preview_actions.extend(
            runtime.retired_delete_action(
                entry,
                chezmoi_home=runtime.chezmoi_home,
                home_root=Path.home(),
            )
            for entry in retired_entries
        )
    render_plan_diff(
        preview_console(sys.stdout),
        InitPlan(
            command="skills",
            label="Skills",
            summary="",
            actions=tuple(preview_actions),
        ),
    )
    return 0


def _acquire_deploy_lock(
    runtime: InitSkillsRuntime,
    use_chezmoi: bool,
    dry_run: bool,
) -> ExitStack | None | bool:
    if not use_chezmoi or dry_run:
        return None
    stack = ExitStack()
    try:
        stack.enter_context(
            chezmoi_deploy_lock(runtime.chezmoi_home.parent, runtime.command_label)
        )
    except LockTimeoutError as exc:
        stack.close()
        print_chezmoi_deploy_lock_timeout(runtime.command_label, exc)
        return False
    return stack


def _close_lock(stack: ExitStack | None | bool) -> None:
    if isinstance(stack, ExitStack):
        stack.close()


def _print_summary(
    *,
    dry_run: bool,
    source_count: int,
    written: int,
    deleted: int,
    skipped: int,
    unchanged: int,
) -> None:
    if dry_run:
        print(f"\nDry run: {source_count} source entries, no files written")
    elif deleted:
        print(
            f"\nWritten: {written}, Deleted: {deleted}, "
            f"Skipped: {skipped}, Unchanged: {unchanged}"
        )
    else:
        print(f"\nWritten: {written}, Skipped: {skipped}, Unchanged: {unchanged}")
