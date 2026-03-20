"""Utilities for writing version-controlled spec and plan (SDD) files."""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.config import load_merged_config

_logger = logging.getLogger(__name__)


def get_sdd_config() -> bool:
    """Check if sdd.version_controlled is enabled in merged config."""
    config = load_merged_config()
    return bool(config.get("sdd", {}).get("version_controlled", False))


def get_sdd_dir(
    workspace_dir: str, workspace_num: int, version_controlled: bool
) -> Path:
    """Return the target directory for SDD files.

    If version_controlled: return Path(workspace_dir) (specs/ and plans/ at project root)
    If not: return primary_workspace / ".sase" / "sdd"
    """
    if version_controlled:
        return Path(workspace_dir)
    return (
        Path(_get_primary_workspace_dir(workspace_dir, workspace_num)) / ".sase" / "sdd"
    )


def _get_primary_workspace_dir(workspace_dir: str, workspace_num: int) -> str:
    """Derive primary workspace dir from current workspace.

    Prefer the project's configured WORKSPACE_DIR (source of truth).
    Fall back to suffix-stripping based on workspace_num.

    For workspace_num == 1, returns workspace_dir as-is.
    For workspace_num > 1, strips the ``_{workspace_num}`` suffix.
    """
    configured_primary = _get_primary_workspace_dir_from_project(workspace_dir)
    if configured_primary:
        return configured_primary

    if workspace_num <= 1:
        return workspace_dir
    suffix = f"_{workspace_num}"
    stripped = workspace_dir.rstrip("/")
    if stripped.endswith(suffix):
        return stripped[: -len(suffix)]
    return workspace_dir


def _get_primary_workspace_dir_from_project(workspace_dir: str) -> str | None:
    """Resolve primary workspace from the project's WORKSPACE_DIR field.

    Returns ``None`` if project/workspace metadata cannot be resolved.
    """
    try:
        from sase.workspace_provider import get_workspace_name
        from sase.workspace_utils import parse_workspace_dir

        project_name = get_workspace_name(workspace_dir)
        if not project_name:
            return None

        project_file = (
            Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
        )
        primary = parse_workspace_dir(str(project_file))
        if not primary:
            return None
        return primary.rstrip("/")
    except Exception:
        return None


def _init_beads(workspace_dir: str, workspace_num: int) -> Path:
    """Bootstrap `.sase/sdd/` as a standalone git repo for local SDD tracking.

    1. Creates `.sase/sdd/` in the primary workspace.
    2. Runs `git init` inside it if not already a git repo.
    3. Runs `bd init --quiet --skip-hooks` in the primary workspace if `beads/` missing.

    Returns the `.sase/sdd/` path.
    """
    primary = _get_primary_workspace_dir(workspace_dir, workspace_num)
    sdd_dir = Path(primary) / ".sase" / "sdd"

    print(f"  Creating {sdd_dir}", flush=True)
    sdd_dir.mkdir(parents=True, exist_ok=True)

    if (sdd_dir / ".git").is_dir():
        print("  Git repo already initialized", flush=True)
    else:
        print("  Initializing git repo ...", flush=True)
        subprocess.run(
            ["git", "init"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )

    gitignore = sdd_dir / ".gitignore"
    if not gitignore.exists():
        print("  Writing .gitignore ...", flush=True)
        gitignore.write_text("beads/beads.db\n", encoding="utf-8")

    beads_dir = sdd_dir / BEADS_DIRNAME_NON_VC
    if beads_dir.is_dir():
        print("  Beads already initialized", flush=True)
    else:
        print("  Initializing beads ...", flush=True)
        BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC)

    commit_sdd_files(sdd_dir, "Initialize beads")

    return sdd_dir


def commit_sdd_files(sdd_dir: Path, message: str) -> None:
    """Auto-commit SDD files in a local `.sase/sdd/` git repo.

    No-op if `sdd_dir` is not a git repo or there are no staged changes.
    """
    if not (sdd_dir / ".git").is_dir():
        return

    subprocess.run(["git", "add", "-A"], cwd=sdd_dir, check=True, capture_output=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=sdd_dir,
        capture_output=True,
    )
    if result.returncode != 0:
        # There are staged changes — commit them
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )


def ensure_beads_initialized(workspace_dir: str, workspace_num: int) -> None:
    """Ensure beads are initialized, calling ``_init_beads`` if necessary.

    For VC repos: initializes ``.sase_beads/`` in the primary workspace root.
    For non-VC repos: delegates to ``_init_beads()`` for ``.sase/sdd/beads/``.
    """
    primary = _get_primary_workspace_dir(workspace_dir, workspace_num)
    if get_sdd_config():
        beads_dir = Path(primary, BEADS_DIRNAME)
        if not beads_dir.is_dir():
            BeadProject.init(Path(primary))
    else:
        beads_dir = Path(primary, ".sase", "sdd", BEADS_DIRNAME_NON_VC)
        if not beads_dir.is_dir():
            _init_beads(workspace_dir, workspace_num)


def write_sdd_files(
    sdd_dir: Path,
    plan_name: str,
    spec_content: str,
    plan_file: str,
) -> tuple[Path, Path]:
    """Write specs/<name>.md and plans/<name>.md to sdd_dir.

    Returns (spec_path, plan_path).
    """
    specs_dir = sdd_dir / "specs"
    plans_dir = sdd_dir / "plans"
    specs_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    spec_path = specs_dir / f"{plan_name}.md"
    spec_path.write_text(spec_content, encoding="utf-8")

    plan_path = plans_dir / f"{plan_name}.md"
    plan_source = Path(plan_file)
    if plan_source.exists():
        from sase.llm_provider._plan_utils import add_created_frontmatter

        content = plan_source.read_text(encoding="utf-8")
        plan_path.write_text(add_created_frontmatter(content), encoding="utf-8")

    return spec_path, plan_path


def update_spec_with_qa(spec_path: Path, qa_markdown: str) -> None:
    """Append Q&A section to an existing spec file."""
    if not spec_path.exists():
        return
    existing = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(
        existing.rstrip("\n") + "\n\n" + qa_markdown + "\n", encoding="utf-8"
    )


def expand_prompt_for_spec(prompt: str) -> str:
    """Expand xprompt references and strip directives for spec storage.

    Performs a "dry" expansion: xprompts are resolved, directives are stripped,
    and embedded workflow ``prompt_part`` content is inlined — but no pre/post
    steps are executed.

    Args:
        prompt: The raw prompt text (may contain ``#refs``, ``%directives``, etc.).

    Returns:
        The fully expanded prompt suitable for writing to a spec file.
    """
    from sase.llm_provider.preprocessing import preprocess_prompt_early

    # Step 1: Expand xprompt references + strip directives
    result = preprocess_prompt_early(prompt)
    expanded = result.prompt

    # Step 2: Dry-expand embedded workflow prompt_parts (no pre/post execution)
    expanded = _dry_expand_embedded_workflows(expanded)

    return expanded


def _dry_expand_embedded_workflows(prompt: str) -> str:
    """Replace embedded workflow references with their rendered prompt_part content.

    This is a "dry" expansion — only the ``prompt_part`` template is rendered
    with the parsed arguments; no pre-steps or post-steps are executed.

    Workflows without a ``prompt_part`` step are left as-is in the text.

    Args:
        prompt: Prompt text (already xprompt-expanded and directive-stripped).

    Returns:
        Prompt with workflow references replaced by rendered prompt_part content.
    """
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import (
        find_matching_paren_for_args,
        normalize_vcs_underscore_refs,
        parse_args,
    )
    from sase.xprompt.loader import get_all_workflows
    from sase.xprompt.models import UNSET
    from sase.xprompt.workflow_executor_utils import render_template

    # Same pattern used by the real embedded workflow executor
    _WORKFLOW_REF_PATTERN = (
        r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
        r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
        r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_.~/-]+)|(\+))?"
    )

    workflows = get_all_workflows()

    # Protect fenced code blocks from expansion
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Normalize #gh_sase → #gh:sase
    prompt = normalize_vcs_underscore_refs(prompt)

    # Collect matches and their replacements
    matches = list(re.finditer(_WORKFLOW_REF_PATTERN, prompt, re.MULTILINE))
    replacements: list[tuple[int, int, str]] = []  # (start, end, replacement)

    for match in matches:
        name = match.group(1)

        if name not in workflows:
            continue

        workflow = workflows[name]

        if not workflow.has_prompt_part():
            continue

        # Parse arguments (mirrors the real executor logic)
        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)
        match_end = match.end()

        positional_args: list[str] = []
        named_args: dict[str, str] = {}

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(prompt, paren_start)
            if paren_end is not None:
                paren_content = prompt[paren_start + 1 : paren_end]
                positional_args, named_args = parse_args(paren_content)
                match_end = paren_end + 1
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                colon_arg = colon_arg[1:-1]
            positional_args = [colon_arg]
        elif plus_suffix is not None:
            positional_args = ["true"]

        # Build args dict with positional → named mapping
        args: dict[str, Any] = dict(named_args)
        for i, value in enumerate(positional_args):
            if i < len(workflow.inputs):
                input_arg = workflow.inputs[i]
                if input_arg.name not in args:
                    args[input_arg.name] = value

        # Apply defaults
        for input_arg in workflow.inputs:
            if input_arg.name not in args and input_arg.default is not UNSET:
                args[input_arg.name] = input_arg.default

        # Render prompt_part
        prompt_part_content = workflow.get_prompt_part_content()
        if prompt_part_content:
            try:
                prompt_part_content = render_template(prompt_part_content, args)
            except Exception:
                _logger.debug(
                    "Failed to render prompt_part for workflow %r, leaving as-is",
                    name,
                )
                continue

        replacements.append((match.start(), match_end, prompt_part_content))

    # Replace right-to-left for position safety
    for start, end, replacement in sorted(
        replacements, key=lambda r: r[0], reverse=True
    ):
        prompt = prompt[:start] + replacement + prompt[end:]

    # Restore fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    return prompt
