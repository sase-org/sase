"""Handler for the 'sase skill init' command (and its 'sase init skills' alias)."""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import jinja2

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.llm_provider.registry import iter_plugins
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
_PRETTIER_FORMAT_ARGS = [
    "prettier",
    "--prose-wrap=always",
    "--print-width=120",
    "--parser=markdown",
]
# Bound the prettier subprocess: skill planning runs inside `sase doctor`
# (config.init), which promises bounded checks — a hung prettier shim must
# degrade to unformatted output instead of hanging the report.
_PRETTIER_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class RenderedSkillTarget:
    """One generated skill file target."""

    path: Path
    content: str
    provider: str
    skill_name: str


_RenderedSkillTarget = RenderedSkillTarget


@dataclass(frozen=True)
class _RawRenderedSkillTarget:
    """One generated skill file target before Markdown formatting."""

    path: Path
    content: str
    provider: str
    skill_name: str


def _all_providers() -> list[str]:
    """Return every registered provider name from ``sase_llm`` entry points."""
    return [name for name, _ in iter_plugins()]


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
    for name, plugin in iter_plugins():
        if name != provider:
            continue
        method = getattr(plugin, "llm_skill_template_context", None)
        if method is None:
            return {}
        return method() or {}
    return {}


def _skill_deploy_subpaths(provider: str) -> list[str]:
    """Return subdirectories (under ``~/`` or ``CHEZMOI_HOME``) for *provider*.

    Plugins may override via :meth:`llm_skill_deploy_subpath`; otherwise the
    primary default is ``.{provider}``. Returning ``None`` opts out of skill
    deployment. Plugins may also expose extra deployment locations via
    :meth:`llm_additional_skill_deploy_subpaths`.
    """
    primary: str | None = f".{provider}"
    additional: list[str] = []

    for name, plugin in iter_plugins():
        if name != provider:
            continue
        method = getattr(plugin, "llm_skill_deploy_subpath", None)
        if method is not None:
            subpath = method()
            primary = str(subpath) if subpath else None
        additional_method = getattr(
            plugin, "llm_additional_skill_deploy_subpaths", None
        )
        if additional_method is not None:
            subpaths = additional_method() or []
            if isinstance(subpaths, str):
                additional = [subpaths]
            else:
                additional = list(subpaths)
        break

    result: list[str] = []
    seen: set[str] = set()
    for subpath in [primary, *additional]:
        if subpath is None:
            continue
        normalized = str(subpath).strip("/")
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


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
    if use_chezmoi:
        # Only the first path segment is a dotfile under chezmoi; nested
        # directories keep their plain names.
        parts = subpath.split("/")
        parts[0] = "dot_" + parts[0].removeprefix(".")
        return CHEZMOI_HOME / Path(*parts) / "skills" / skill_name / "SKILL.md"
    return Path.home() / subpath / "skills" / skill_name / "SKILL.md"


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
    xprompts = dict(load_xprompts_from_internal())
    # Passing an empty project disables project auto-detection while still
    # loading the global runtime catalog, including user config overlays.
    xprompts.update(get_all_xprompts(project=""))
    return sorted((xp for xp in xprompts.values() if xp.skill), key=lambda xp: xp.name)


def prettier_available() -> bool:
    """Return whether generated Markdown can be formatted with prettier."""
    return _prettier_available()


def load_skill_xprompts() -> list[XPrompt]:
    """Return loaded xprompts that are installable as provider skills."""
    return _load_skill_xprompts()


def get_skill_target_providers(skill_field: bool | list[str]) -> list[str]:
    """Return providers a skill should be deployed to."""
    return _get_target_providers(skill_field)


_PRETTIER_COMMENT_RE = re.compile(r"^<!-- prettier-ignore[^\n]*-->\n?", re.MULTILINE)


def _render_skill(
    body: str, description: str, context: dict[str, str]
) -> tuple[str, str]:
    """Render a skill body and description through Jinja2."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    rendered_body = env.from_string(body).render(context)
    rendered_desc = env.from_string(description).render(context)
    # Strip prettier-ignore comments (template metadata, not skill content)
    rendered_body = _PRETTIER_COMMENT_RE.sub("", rendered_body)
    # Collapse resulting triple+ blank lines and strip leading blanks
    rendered_body = re.sub(r"\n{3,}", "\n\n", rendered_body)
    rendered_body = rendered_body.lstrip("\n")
    return rendered_body, rendered_desc


def _skill_use_audit_directive(name: str) -> str:
    """Return the generated first-step audit directive for a skill."""
    return (
        "Before doing anything else, run this command to record that you are "
        "using this skill:\n\n"
        "```bash\n"
        f'sase skill use {name} --reason "<one-line reason for using this skill>"\n'
        "```\n\n"
    )


def _build_output(
    name: str, description: str, body: str, log_skill_use: bool = True
) -> str:
    """Build the final SKILL.md content with frontmatter.

    When *log_skill_use* is true (the default), the generated skill begins with
    the audit directive instructing the agent to record its own use. Skills that
    set ``log_skill_use: false`` in their source omit that directive.
    """
    if "\n" in description.strip():
        # Multi-line: use YAML literal block scalar (|)
        header = f"---\nname: {name}\ndescription: |\n"
        for line in description.strip().splitlines():
            header += f"  {line}\n"
        header += "---"
    elif len(f"description: {description}") > 120:
        # Long single-line: wrap as YAML plain scalar with continuation indent
        wrapped = textwrap.fill(description, width=118)
        indented = textwrap.indent(wrapped, "  ")
        header = f"---\nname: {name}\ndescription:\n{indented}\n---"
    else:
        header = f"---\nname: {name}\ndescription: {description}\n---"
    directive = _skill_use_audit_directive(name) if log_skill_use else ""
    content = header + "\n\n" + directive + body
    if not content.endswith("\n"):
        content += "\n"
    return content


def _prettier_available() -> bool:
    """Return whether generated Markdown can be formatted with prettier."""
    return shutil.which("prettier") is not None


def _unescape_prettier_underscores(text: str) -> str:
    """Apply the post-Prettier underscore unescaping used by existing formatting."""
    while r"\_" in text:
        text = text.replace(r"\_", "_")
    return text


def _format_skill_output(output: str, *, use_prettier: bool) -> str:
    """Format generated skill Markdown with the same path used by apply."""
    if not use_prettier:
        return output

    from sase.file_references import format_with_prettier

    return format_with_prettier(output)


def _format_unique_skill_outputs_batch(outputs: Sequence[str]) -> list[str]:
    """Format unique generated skill Markdown bodies with one Prettier command."""
    if not outputs:
        return []

    with tempfile.TemporaryDirectory(prefix="sase-init-skills-") as temp_dir:
        temp_path = Path(temp_dir)
        paths: list[Path] = []
        for index, output in enumerate(outputs):
            path = temp_path / f"skill-{index}.md"
            path.write_text(output, encoding="utf-8")
            paths.append(path)

        subprocess.run(
            [
                _PRETTIER_FORMAT_ARGS[0],
                "--write",
                *_PRETTIER_FORMAT_ARGS[1:],
                *(str(path) for path in paths),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=_PRETTIER_TIMEOUT_SECONDS,
        )
        return [
            _unescape_prettier_underscores(path.read_text(encoding="utf-8"))
            for path in paths
        ]


def _format_skill_outputs(outputs: Sequence[str], *, use_prettier: bool) -> list[str]:
    """Format generated skill Markdown once per unique raw output."""
    raw_outputs = list(outputs)
    if not use_prettier or not raw_outputs:
        return raw_outputs

    unique_outputs: list[str] = []
    unique_indexes: dict[str, int] = {}
    for output in raw_outputs:
        if output in unique_indexes:
            continue
        unique_indexes[output] = len(unique_outputs)
        unique_outputs.append(output)

    try:
        formatted_unique_outputs = _format_unique_skill_outputs_batch(unique_outputs)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        formatted_unique_outputs = [
            _format_skill_output(output, use_prettier=True) for output in unique_outputs
        ]

    return [formatted_unique_outputs[unique_indexes[output]] for output in raw_outputs]


def _render_skill_targets(
    skill_xprompts: list[XPrompt],
    *,
    provider_filter: str | None,
    use_chezmoi: bool,
    use_prettier: bool,
) -> list[RenderedSkillTarget]:
    """Render every selected skill/provider target without writing files."""
    raw_targets: list[_RawRenderedSkillTarget] = []

    for xprompt in skill_xprompts:
        name = xprompt.name
        description = xprompt.description or ""
        skill_field = xprompt.skill
        if not skill_field:
            continue

        target_providers = _get_target_providers(skill_field)
        if provider_filter:
            target_providers = [p for p in target_providers if p == provider_filter]

        for provider in target_providers:
            context = _provider_context(provider)
            rendered_body, rendered_desc = _render_skill(
                xprompt.content, description, context
            )
            output = _build_output(
                name,
                rendered_desc.strip(),
                rendered_body,
                log_skill_use=xprompt.log_skill_use,
            )
            for target in _get_target_paths(provider, name, use_chezmoi):
                raw_targets.append(
                    _RawRenderedSkillTarget(
                        path=target,
                        content=output,
                        provider=provider,
                        skill_name=name,
                    )
                )

    formatted_outputs = _format_skill_outputs(
        [target.content for target in raw_targets],
        use_prettier=use_prettier,
    )
    return [
        RenderedSkillTarget(
            path=target.path,
            content=content,
            provider=target.provider,
            skill_name=target.skill_name,
        )
        for target, content in zip(raw_targets, formatted_outputs, strict=True)
    ]


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
    detail = f"{target.provider}/{target.skill_name}"
    if not target.path.exists():
        return "create", detail
    try:
        existing = target.path.read_text(encoding="utf-8")
    except OSError:
        return "overwrite", detail
    except UnicodeDecodeError:
        return "overwrite", detail
    if existing == target.content:
        return None
    return "overwrite", detail


def planned_skill_operation(
    target: RenderedSkillTarget,
) -> tuple[InitOperation, str] | None:
    """Return planned operation/detail for a skill target, or ``None``."""
    return _planned_skill_operation(target)


def _summarize_skill_actions(actions: tuple[InitAction, ...]) -> str:
    """Return a compact summary for generated skill actions."""
    if not actions:
        return "provider skill files are current"
    operations = {action.operation for action in actions}
    count = len(actions)
    noun = "provider skill file" if count == 1 else "provider skill files"
    if operations == {"create"}:
        return f"create {count} {noun}"
    if operations == {"overwrite"}:
        return f"overwrite {count} {noun}"
    return f"refresh {count} {noun}"


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
    targets = _render_skill_targets(
        skill_xprompts,
        provider_filter=provider_filter,
        use_chezmoi=use_chezmoi,
        use_prettier=use_prettier,
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
    targets = _render_skill_targets(
        skill_xprompts,
        provider_filter=provider_filter,
        use_chezmoi=use_chezmoi,
        use_prettier=use_prettier,
    )
    if targets and not use_prettier:
        print(_PRETTIER_WARNING, file=sys.stderr)

    if getattr(args, "diff", False):
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
