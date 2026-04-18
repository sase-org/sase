"""Handler for the 'sase init-skills' command."""

import argparse
import difflib
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import jinja2

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.loader_parsing import parse_yaml_front_matter

ALL_PROVIDERS = ["claude", "gemini", "codex"]

PROVIDER_CONTEXT: dict[str, dict[str, str]] = {
    "claude": {
        "provider_name": "Claude",
        "provider_tool_name": "Claude Code",
        "provider_native_ask_tool": "AskUserQuestion",
    },
    "gemini": {
        "provider_name": "Gemini",
        "provider_tool_name": "Gemini CLI",
        "provider_native_ask_tool": "ask_user",
    },
    "codex": {
        "provider_name": "Codex",
        "provider_tool_name": "Codex",
        "provider_native_ask_tool": "ask_user",
    },
}


def _get_target_providers(skill_field: bool | list[str]) -> list[str]:
    """Return the list of providers a skill should be deployed to."""
    if skill_field is True:
        return list(ALL_PROVIDERS)
    if isinstance(skill_field, list):
        return [p for p in skill_field if p in ALL_PROVIDERS]
    return []


def _get_target_path(provider: str, skill_name: str, use_chezmoi: bool) -> Path:
    """Return the deployment path for a skill file."""
    if use_chezmoi:
        return CHEZMOI_HOME / f"dot_{provider}" / "skills" / skill_name / "SKILL.md"
    return Path.home() / f".{provider}" / "skills" / skill_name / "SKILL.md"


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


def _build_output(name: str, description: str, body: str) -> str:
    """Build the final SKILL.md content with frontmatter."""
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
    content = header + "\n\n" + body
    if not content.endswith("\n"):
        content += "\n"
    return content


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
            diff = difflib.unified_diff(
                existing.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=str(target),
                tofile="(new)",
            )
            sys.stdout.writelines(diff)


def _deploy_to_chezmoi(written_paths: list[Path], args: argparse.Namespace) -> int:
    """Stage, commit, push, and ``chezmoi apply`` after writing skill files.

    Returns the desired process exit code (0 on success, 1 on pull/push/apply
    failure). Honors ``--no-commit`` / ``--no-push`` / ``--no-apply`` flags.
    """
    no_commit: bool = getattr(args, "no_commit", False)
    no_push: bool = getattr(args, "no_push", False)
    no_apply: bool = getattr(args, "no_apply", False)
    provider_filter: str | None = getattr(args, "provider", None)

    if no_commit:
        return 0

    git_root = CHEZMOI_HOME.parent

    try:
        repo_check = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("init-skills: git not found on PATH, skipping deploy", file=sys.stderr)
        return 0

    if repo_check.returncode != 0:
        print(
            f"init-skills: {git_root} is not a git repo, skipping deploy",
            file=sys.stderr,
        )
        return 0

    for path in written_paths:
        subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            check=False,
        )

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        check=False,
    )
    if staged.returncode == 0:
        print(f"\nNothing to commit in {git_root} (files identical to HEAD).")
        return 0

    message = "chore: regenerate skills via sase init-skills"
    if provider_filter:
        message = f"chore: regenerate {provider_filter} skills via sase init-skills"

    print(f"\nCommitting in {git_root}...")
    commit = subprocess.run(
        ["git", "-C", str(git_root), "commit", "-m", message],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        print(f"init-skills: commit failed: {commit.stderr.strip()}", file=sys.stderr)
        return 1
    first_line = commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
    if first_line:
        print(f"  {first_line}")

    if no_push:
        return 0

    print("Pulling...")
    pull = subprocess.run(
        ["git", "-C", str(git_root), "pull", "--rebase"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull.returncode != 0:
        print(f"init-skills: pull failed: {pull.stderr.strip()}", file=sys.stderr)
        return 1
    if pull.stdout.strip():
        print(f"  {pull.stdout.strip().splitlines()[0]}")

    print("Pushing...")
    push = subprocess.run(
        ["git", "-C", str(git_root), "push"],
        capture_output=True,
        text=True,
        check=False,
    )
    if push.returncode != 0:
        print(f"init-skills: push failed: {push.stderr.strip()}", file=sys.stderr)
        return 1
    tail = push.stderr.strip() or push.stdout.strip()
    if tail:
        print(f"  {tail.splitlines()[-1]}")

    if no_apply:
        return 0

    print("Applying chezmoi...")
    try:
        apply = subprocess.run(
            ["chezmoi", "apply"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("init-skills: chezmoi not found on PATH", file=sys.stderr)
        return 0
    if apply.returncode != 0:
        print(
            f"init-skills: chezmoi apply failed: {apply.stderr.strip()}",
            file=sys.stderr,
        )
        return 1
    print("  Done.")
    return 0


def handle_init_skills_command(args: argparse.Namespace) -> None:
    """Handle the 'sase init-skills' command."""
    skills_dir = get_sase_package_xprompts_dir() / "skills"
    if not skills_dir.is_dir():
        print(f"Error: Skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    use_chezmoi = get_use_chezmoi()
    is_tty = sys.stdin.isatty()
    provider_filter: str | None = getattr(args, "provider", None)
    force: bool = getattr(args, "force", False)
    dry_run: bool = getattr(args, "dry_run", False)

    source_files = sorted(skills_dir.glob("*.md"))
    if not source_files:
        print("No skill source files found.")
        sys.exit(0)

    written = 0
    skipped = 0
    written_paths: list[Path] = []

    for src_path in source_files:
        content = src_path.read_text(encoding="utf-8")
        front_matter, body = parse_yaml_front_matter(content)

        if front_matter is None:
            print(
                f"Warning: No frontmatter in {src_path.name}, skipping", file=sys.stderr
            )
            continue

        skill_field = front_matter.get("skill")
        if not skill_field:
            continue

        name = front_matter.get("name", src_path.stem)
        description = front_matter.get("description", "")

        target_providers = _get_target_providers(skill_field)
        if provider_filter:
            target_providers = [p for p in target_providers if p == provider_filter]

        for provider in target_providers:
            context = PROVIDER_CONTEXT[provider]
            rendered_body, rendered_desc = _render_skill(body, description, context)
            output = _build_output(name, rendered_desc.strip(), rendered_body)
            target = _get_target_path(provider, name, use_chezmoi)

            if dry_run:
                print(f"  {target}")
                continue

            if target.exists() and not force:
                if not is_tty:
                    print(
                        f"  Warning: {target} exists, skipping (not a TTY; use -f to force)",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue
                if not _prompt_overwrite(target, output):
                    skipped += 1
                    continue

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output, encoding="utf-8")
            print(f"  {target}")
            written += 1
            written_paths.append(target)

    if dry_run:
        print(f"\nDry run: {len(source_files)} source files, no files written")
    else:
        print(f"\nWritten: {written}, Skipped: {skipped}")

    exit_code = 0
    if use_chezmoi and not dry_run and written > 0:
        exit_code = _deploy_to_chezmoi(written_paths, args)

    sys.exit(exit_code)
