"""Handler for the 'sase skill init' command (and its 'sase init skills' alias)."""

import argparse
from collections.abc import Sequence
import shutil
import sys
from pathlib import Path

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.main._init_skills_rendering import (
    RenderedSkillTarget,
    SkillFrameTemplateError,
    format_skill_output as _format_skill_output_impl,
    format_skill_outputs as _format_skill_outputs_impl,
    format_unique_skill_outputs_batch as _format_unique_skill_outputs_batch_impl,
    planned_skill_operation as _planned_skill_operation_impl,
    render_skill_targets as _render_skill_targets_impl,
    summarize_skill_actions as _summarize_skill_actions_impl,
)
from sase.main._init_skills_sources import (
    all_providers as _all_providers_impl,
    provider_context as _provider_context_impl,
    select_skill_xprompts as _select_skill_xprompts,
    skill_deploy_subpaths as _skill_deploy_subpaths_impl,
    target_path_for_subpath as _target_path_for_subpath_impl,
)
from sase.main._init_skills_source_integrity import skill_source_integrity_error
from sase.main._init_chezmoi_deploy import (
    ChezmoiDeployBehavior,
    defer_chezmoi_paths,
    deploy_to_chezmoi,
)
from sase.main.init_plan import InitAction, InitOperation, InitPlan
from sase.xprompt.loader import get_all_xprompts, load_xprompts_from_internal
from sase.xprompt.models import XPrompt

_COMMAND_LABEL = "skill init"
_PRETTIER_WARNING = (
    f"{_COMMAND_LABEL}: prettier not found on PATH; output may not match "
    "chezmoi CI formatting"
)
_RenderedSkillTarget = RenderedSkillTarget


def _all_providers() -> list[str]:
    """Return every registered provider name from ``sase_llm`` entry points."""
    return _all_providers_impl()


def _registered_provider_names() -> tuple[str, ...]:
    """Return registered provider names in registry order."""
    return tuple(_all_providers())


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
    """Return subdirectories (under ``~/`` or ``CHEZMOI_HOME``) for *provider*.

    Plugins may override via :meth:`llm_skill_deploy_subpath`; otherwise the
    primary default is ``.{provider}``. Returning ``None`` opts out of skill
    deployment. Plugins may also expose extra deployment locations via
    :meth:`llm_additional_skill_deploy_subpaths`.
    """
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
        return [p for p in skill_field if p in known]
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


def _load_skill_xprompts() -> list[XPrompt]:
    """Return loaded xprompts that are installable as provider skills."""
    # Passing an empty project disables project auto-detection while still
    # loading the global runtime catalog, including user config overlays.
    return _select_skill_xprompts(
        dict(load_xprompts_from_internal()),
        get_all_xprompts(project=""),
    )


def prettier_available() -> bool:
    """Return whether generated Markdown can be formatted with prettier."""
    return _prettier_available()


def load_skill_xprompts() -> list[XPrompt]:
    """Return loaded xprompts that are installable as provider skills."""
    return _load_skill_xprompts()


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


def _prompt_overwrite(target: Path, new_content: str) -> bool:
    """Interactively prompt the user about overwriting an existing file.

    Returns True if the user chose to overwrite, False to skip.
    """
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


def _deploy_to_chezmoi(written_paths: list[Path], args: argparse.Namespace) -> int:
    """Stage, commit, push, and ``chezmoi apply`` after writing skill files.

    Returns the desired process exit code (0 on success, 1 on pull/push/apply
    failure). Honors ``--no-commit`` / ``--no-push`` / ``--no-apply`` flags.
    """
    no_commit: bool = getattr(args, "no_commit", False)
    no_push: bool = getattr(args, "no_push", False)
    no_apply: bool = getattr(args, "no_apply", False)
    provider_filter: str | None = getattr(args, "provider", None)

    message = "chore: regenerate skills via sase skill init"
    if provider_filter:
        message = f"chore: regenerate {provider_filter} skills via sase skill init"

    return deploy_to_chezmoi(
        written_paths,
        ChezmoiDeployBehavior(
            command_label=_COMMAND_LABEL,
            commit_message=message,
            auto_commit_type="skills",
            chezmoi_home=CHEZMOI_HOME,
            no_commit=no_commit,
            no_push=no_push,
            no_apply=no_apply,
            git_failure_is_error=False,
            chezmoi_missing_is_error=False,
            git_missing_suffix=", skipping deploy",
            not_repo_suffix=", skipping deploy",
        ),
    )


def plan_init_skills(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for generated provider skill files."""
    use_chezmoi = get_use_chezmoi()
    provider_filter: str | None = getattr(args, "provider", None)
    provider_error = _provider_validation_error(provider_filter)
    if provider_error is not None:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="cannot plan generated skill files until provider is valid",
            actions=(),
            blockers=(provider_error,),
        )

    skill_xprompts = _load_skill_xprompts()
    use_prettier = _prettier_available()
    try:
        targets = _render_skill_targets(
            skill_xprompts,
            provider_filter=provider_filter,
            use_chezmoi=use_chezmoi,
            use_prettier=use_prettier,
        )
    except SkillFrameTemplateError as exc:
        return InitPlan(
            command="skills",
            label="Skills",
            summary="cannot plan generated skill files until the frame template is fixed",
            actions=(),
            blockers=(str(exc),),
        )

    actions: list[InitAction] = []
    for target in targets:
        planned = _planned_skill_operation(target)
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

    warnings = (_PRETTIER_WARNING,) if targets and not use_prettier else ()
    return InitPlan(
        command="skills",
        label="Skills",
        summary=_summarize_skill_actions(tuple(actions)),
        actions=tuple(actions),
        warnings=warnings,
    )


def run_init_skills(args: argparse.Namespace) -> int:
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
                    plan=plan_init_skills,
                    run=run_init_skills,
                ),
            ),
        )

    use_chezmoi = get_use_chezmoi()
    is_tty = sys.stdin.isatty()
    provider_filter: str | None = getattr(args, "provider", None)
    force: bool = getattr(args, "force", False)
    dry_run: bool = getattr(args, "dry_run", False)

    provider_error = _provider_validation_error(provider_filter)
    if provider_error is not None:
        print(f"{_COMMAND_LABEL}: {provider_error}", file=sys.stderr)
        return 2

    skill_xprompts = _load_skill_xprompts()
    if not skill_xprompts:
        print("No skill source entries found.")
        return 0

    use_prettier = _prettier_available()
    try:
        targets = _render_skill_targets(
            skill_xprompts,
            provider_filter=provider_filter,
            use_chezmoi=use_chezmoi,
            use_prettier=use_prettier,
        )
    except SkillFrameTemplateError as exc:
        print(f"{_COMMAND_LABEL}: {exc}", file=sys.stderr)
        return 1
    if targets and not use_prettier:
        print(_PRETTIER_WARNING, file=sys.stderr)

    diff: bool = getattr(args, "diff", False)
    if diff:
        from .init_preview import preview_console, render_plan_diff

        preview_actions: list[InitAction] = []
        for target in targets:
            planned = _planned_skill_operation(target)
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

    has_changes = any(
        _planned_skill_operation(target) is not None for target in targets
    )
    allow_dirty: bool = getattr(args, "allow_dirty", False)
    if use_chezmoi and not dry_run and has_changes and not allow_dirty:
        source_error = skill_source_integrity_error()
        if source_error is not None:
            print(f"{_COMMAND_LABEL}: {source_error}", file=sys.stderr)
            return 1

    written = 0
    skipped = 0
    unchanged = 0
    written_paths: list[Path] = []

    for target in targets:
        planned = _planned_skill_operation(target)
        if planned is None:
            unchanged += 1
            continue

        if dry_run:
            operation, _detail = planned
            print(f"  {operation}: {target.path}")
            continue

        if target.path.exists() and not force:
            if not is_tty:
                print(
                    f"  Warning: {target.path} exists, skipping (not a TTY; use -f to force)",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            if not _prompt_overwrite(target.path, target.content):
                skipped += 1
                continue

        target.path.parent.mkdir(parents=True, exist_ok=True)
        target.path.write_text(target.content, encoding="utf-8")
        print(f"  {target.path}")
        written += 1
        written_paths.append(target.path)

    if dry_run:
        print(f"\nDry run: {len(skill_xprompts)} source entries, no files written")
    else:
        print(f"\nWritten: {written}, Skipped: {skipped}, Unchanged: {unchanged}")

    exit_code = 0
    if use_chezmoi and not dry_run and written > 0:
        if defer_chezmoi_paths(written_paths, chezmoi_home=CHEZMOI_HOME):
            exit_code = 0
        else:
            exit_code = _deploy_to_chezmoi(written_paths, args)

    return exit_code


def handle_init_skills_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init skills``."""
    sys.exit(run_init_skills(args))
