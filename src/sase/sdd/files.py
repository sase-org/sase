"""SDD file writing, committing, and directory resolution."""

import logging
import shutil
import subprocess
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_SDD_PLAN_KINDS = {"tales", "epics", "legends"}
_SDD_PLAN_KIND_ALIASES = {"plans": "tales"}
_SDD_PROMPT_KINDS = {"prompts", "specs"}
_SDD_CANONICAL_DIRS = {
    "prompts",
    "tales",
    "epics",
    "legends",
    "myths",
    "research",
    "beads",
}
SDD_DIRECTORY_MAP_FILENAME = "sdd-directory-map.png"
SDD_DIRECTORY_MAP_RELATIVE_PATH = f"assets/{SDD_DIRECTORY_MAP_FILENAME}"

SDD_README_CONTENT = """# Structured Development Docs

The `sdd/` directory keeps durable planning context close to the code it describes. It stores prompts, approved plans,
roadmap material, and bead state in predictable paths so humans and agents can reference the same artifacts over time.

![SDD directory map](assets/sdd-directory-map.png)

## Directory Layout

- `prompts/` stores the original user prompts or expanded prompt snapshots that led to plan-like artifacts.
- `tales/` stores task-level implementation plans and follow-up plans.
- `epics/` stores larger work plans that may be split into phase beads.
- `legends/` stores broad roadmap or strategy artifacts that can spawn epics.
- `myths/` stores long-horizon narrative, strategy, and context artifacts that are broader than active roadmap plans.
- `research/` stores exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- `beads/` stores bead issue data for SDD-backed work tracking.

Prompt, tale, epic, legend, and research files are normally organized under a `YYYYMM/` month directory, for example
`sdd/prompts/202605/example.md`, `sdd/tales/202605/example.md`, and `sdd/research/202605/example.md`. Prompt files
should link to their generated plan-like artifact with frontmatter such as `plan: sdd/tales/202605/example.md`; the
plan-like artifact should link back with `prompt: sdd/prompts/202605/example.md`.

## Commands

- `sase sdd list` lists SDD markdown artifacts.
- `sase sdd validate` checks frontmatter links between prompts and plan-like artifacts.
- `sase sdd repair-links` infers and repairs missing bidirectional links.
- `sase bead` manages SDD bead issues and epic work.

## Compatibility

The canonical directories are `prompts/`, `tales/`, `epics/`, `legends/`, `myths/`, `research/`, and `beads/`. Older
trees may still contain `specs/` for prompt snapshots or `plans/` for tale-like plans; SDD tooling keeps limited
compatibility for those legacy names, but new artifacts should use `prompts/` and `tales/`.
"""

SDD_DIRECTORY_README_CONTENT = {
    "tales": """# Tales

The `tales/` directory stores task-level implementation plans and follow-up plans. Tales are the usual handoff artifact
for focused work that is ready to implement.
""",
    "epics": """# Epics

The `epics/` directory stores larger work plans that may span multiple phases or beads. Epics connect concrete delivery
work to a broader feature or project outcome.
""",
    "legends": """# Legends

The `legends/` directory stores broad roadmap or strategy artifacts that can spawn epics. Legends describe direction and
sequencing before the work is broken into implementation-sized plans.
""",
    "myths": """# Myths

The `myths/` directory stores long-horizon narrative, strategy, and context artifacts. Myths are broader than active
roadmap plans and preserve the background story that helps future plans make sense.
""",
    "research": """# Research

The `research/` directory stores exploratory findings, prior art, options, critiques, and recommendations that inform
later tales, epics, legends, or implementation work.
""",
}


def get_yyyymm(dt: datetime | None = None) -> str:
    """Return a YYYYMM string for SDD subdirectory organization.

    Uses the configured timezone (same as ``add_create_time_frontmatter``).
    """
    if dt is None:
        from sase.core.time import get_timezone

        dt = datetime.now(get_timezone())
    return dt.strftime("%Y%m")


def _sdd_kind_roots(base_dir: Path, kind: str) -> list[Path]:
    """Return lookup roots for an SDD kind, including legacy prompt aliases."""
    aliases: tuple[str, ...]
    if kind in _SDD_PROMPT_KINDS:
        aliases = ("prompts", "specs")
    elif kind in ("tales", "plans"):
        aliases = ("tales", "plans")
    else:
        aliases = (kind,)
    roots: list[Path] = []
    seen: set[Path] = set()
    for alias in aliases:
        for root in (base_dir / "sdd" / alias, base_dir / alias):
            if root not in seen:
                roots.append(root)
                seen.add(root)
    return roots


def find_sdd_file(base_dir: Path, kind: str, name: str) -> Path | None:
    """Search for an SDD file, supporting canonical and legacy layouts.

    Canonical version-controlled paths live under ``sdd/{kind}``. Legacy
    version-controlled paths live at the project root under ``{kind}``. Local
    SDD mode passes ``.sase/sdd`` as ``base_dir``, where ``{kind}`` remains the
    canonical local location.

    Returns the first match, or ``None`` if not found.
    """
    for root in _sdd_kind_roots(base_dir, kind):
        flat = root / name
        if flat.exists():
            return flat
        matches = sorted(root.glob(f"*/{name}"))
        if matches:
            return matches[0]
    return None


def resolve_sdd_readme_path(
    path: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the generated SDD README target.

    ``path`` may point at either a project root or an SDD root. Existing SDD
    roots and paths named ``sdd`` are treated as SDD roots; other paths are
    treated as project roots so init can create a missing ``sdd/`` directory.
    """
    base = Path.cwd() if cwd is None else cwd
    if path is None:
        return (base / "sdd" / "README.md").resolve()

    target = Path(path).expanduser()
    if not target.is_absolute():
        target = base / target

    if _looks_like_sdd_root(target):
        return (target / "README.md").resolve()
    return (target / "sdd" / "README.md").resolve()


def resolve_sdd_asset_path(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve the generated SDD directory map target."""
    return (
        resolve_sdd_readme_path(path, cwd=cwd).parent / SDD_DIRECTORY_MAP_RELATIVE_PATH
    )


def write_sdd_readme(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Create or refresh the canonical SDD README and return its path."""
    readme_path = resolve_sdd_readme_path(path, cwd=cwd)
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(SDD_README_CONTENT, encoding="utf-8")
    _write_sdd_directory_readmes(readme_path.parent)
    _copy_sdd_directory_map(resolve_sdd_asset_path(path, cwd=cwd))
    return readme_path


def _write_sdd_directory_readmes(sdd_root: Path) -> None:
    for dirname, content in SDD_DIRECTORY_README_CONTENT.items():
        readme_path = sdd_root / dirname / "README.md"
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text(content, encoding="utf-8")


def _copy_sdd_directory_map(asset_path: Path) -> None:
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    source = resources.files("sase.sdd").joinpath("assets", SDD_DIRECTORY_MAP_FILENAME)
    with resources.as_file(source) as source_path:
        if source_path.resolve() != asset_path.resolve():
            shutil.copyfile(source_path, asset_path)


def _looks_like_sdd_root(path: Path) -> bool:
    if path.name == "sdd":
        return True
    if not path.is_dir():
        return False
    return any((path / dirname).is_dir() for dirname in _SDD_CANONICAL_DIRS)


def get_sdd_dir(
    workspace_dir: str, workspace_num: int, version_controlled: bool
) -> Path:
    """Return the target directory for SDD files.

    If version_controlled: return Path(workspace_dir) / "sdd"
    If not: return primary_workspace / ".sase" / "sdd"
    """
    if version_controlled:
        return Path(workspace_dir) / "sdd"
    return (
        Path(get_primary_workspace_dir(workspace_dir, workspace_num)) / ".sase" / "sdd"
    )


def get_primary_workspace_dir(workspace_dir: str, workspace_num: int) -> str:
    """Derive primary workspace dir from current workspace.

    Prefer the project's configured WORKSPACE_DIR (source of truth).
    Fall back to suffix-stripping based on workspace_num.

    For workspace_num == 1, returns workspace_dir as-is.
    For workspace_num > 1, strips the ``_{workspace_num}`` suffix.
    """
    configured_primary = _resolve_primary_from_project(workspace_dir)
    if configured_primary:
        return configured_primary

    if workspace_num <= 1:
        return workspace_dir
    suffix = f"_{workspace_num}"
    stripped = workspace_dir.rstrip("/")
    parts = stripped.split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].endswith(suffix):
            parts[i] = parts[i][: -len(suffix)]
            return "/".join(parts)
    return workspace_dir


def _resolve_primary_from_project(workspace_dir: str) -> str | None:
    """Resolve primary workspace from the project's WORKSPACE_DIR field.

    Returns ``None`` if project/workspace metadata cannot be resolved.
    """
    try:
        from sase.workspace_provider import get_workspace_name
        from sase.workspace_provider.utils import parse_workspace_dir

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


def _sdd_link_path(sdd_dir: Path, path: Path) -> str:
    """Return the stable relative path to write into SDD frontmatter."""
    relative = path.relative_to(sdd_dir).as_posix()
    if sdd_dir.name == "sdd" and sdd_dir.parent.name == ".sase":
        return f".sase/sdd/{relative}"
    if sdd_dir.name == "sdd":
        return f"sdd/{relative}"
    return relative


def write_sdd_files(
    sdd_dir: Path,
    plan_name: str,
    prompt_content: str,
    plan_file: str,
    *,
    plan_kind: str = "tales",
) -> tuple[Path, Path]:
    """Write prompts/<YYYYMM>/<name>.md and <plan_kind>/<YYYYMM>/<name>.md.

    Returns (prompt_path, plan_path).
    """
    plan_kind = _SDD_PLAN_KIND_ALIASES.get(plan_kind, plan_kind)
    if plan_kind not in _SDD_PLAN_KINDS:
        raise ValueError(
            f"invalid SDD plan kind {plan_kind!r}; expected one of "
            f"{sorted(_SDD_PLAN_KINDS)}"
        )

    yyyymm = get_yyyymm()
    prompts_dir = sdd_dir / "prompts" / yyyymm
    plans_dir = sdd_dir / plan_kind / yyyymm
    prompts_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = prompts_dir / f"{plan_name}.md"
    plan_path = plans_dir / f"{plan_name}.md"
    prompt_link = _sdd_link_path(sdd_dir, prompt_path)
    plan_link = _sdd_link_path(sdd_dir, plan_path)

    from sase.sdd.frontmatter import set_frontmatter_fields

    prompt_path.write_text(
        set_frontmatter_fields(prompt_content, {"plan": plan_link}),
        encoding="utf-8",
    )

    plan_source = Path(plan_file)
    if plan_source.exists():
        from sase.gemini_wrapper.file_references import format_with_prettier
        from sase.llm_provider._plan_utils import add_create_time_frontmatter

        content = plan_source.read_text(encoding="utf-8")
        content = format_with_prettier(content)
        content = add_create_time_frontmatter(content)
        content = set_frontmatter_fields(content, {"prompt": prompt_link})
        plan_path.write_text(content, encoding="utf-8")

    return prompt_path, plan_path


def update_prompt_with_qa(prompt_path: Path, qa_markdown: str) -> None:
    """Append Q&A section to an existing prompt snapshot."""
    if not prompt_path.exists():
        return
    existing = prompt_path.read_text(encoding="utf-8")
    prompt_path.write_text(
        existing.rstrip("\n") + "\n\n" + qa_markdown + "\n", encoding="utf-8"
    )


def update_spec_with_qa(spec_path: Path, qa_markdown: str) -> None:
    """Append Q&A to an SDD prompt snapshot.

    Compatibility wrapper for callers still using the old ``spec`` terminology.
    """
    update_prompt_with_qa(spec_path, qa_markdown)


def expand_prompt_for_spec(prompt: str) -> str:
    """Expand xprompt references and strip directives for prompt storage.

    Performs a "dry" expansion: xprompts are resolved, directives are stripped,
    and embedded workflow ``prompt_part`` content is inlined — but no pre/post
    steps are executed.

    Args:
        prompt: The raw prompt text (may contain ``#refs``, ``%directives``, etc.).

    Returns:
        The fully expanded prompt suitable for writing to a prompt snapshot.
    """
    from sase.llm_provider.preprocessing import preprocess_prompt_early

    # Step 1: Expand xprompt references + strip directives
    result = preprocess_prompt_early(prompt)
    expanded = result.prompt

    # Step 2: Dry-expand embedded workflow prompt_parts (no pre/post execution)
    expanded = dry_expand_embedded_workflows(expanded)

    return expanded


def dry_expand_embedded_workflows(prompt: str) -> str:
    """Replace embedded workflow references with their rendered prompt_part content.

    This is a "dry" expansion — only the ``prompt_part`` template is rendered
    with the parsed arguments; no pre-steps or post-steps are executed.

    Explicit standalone workflow references (``#!name`` for workflows without a
    ``prompt_part`` step) are preserved as compact markers for spec storage.
    Legacy inline standalone references (``#name``) are rejected so prompt
    snapshots do not capture ambiguous syntax.

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
        iter_xprompt_references,
        normalize_vcs_underscore_refs,
    )
    from sase.xprompt.loader import get_all_workflows
    from sase.xprompt.models import UNSET
    from sase.xprompt.workflow_executor_steps_embedded_types import (
        format_inline_workflow_reference_error,
        parse_workflow_reference_args,
    )
    from sase.xprompt.workflow_executor_utils import render_template

    workflows = get_all_workflows()

    # Protect fenced code blocks from expansion
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Normalize #gh_sase → #gh:sase
    prompt = normalize_vcs_underscore_refs(prompt)

    # Collect matches and their replacements
    refs = iter_xprompt_references(prompt)
    replacements: list[tuple[int, int, str]] = []  # (start, end, replacement)

    for ref in refs:
        name = ref.name
        if name not in workflows:
            continue

        workflow = workflows[name]

        if not workflow.has_prompt_part():
            if ref.is_standalone_marker:
                continue
            raise ValueError(
                format_inline_workflow_reference_error(
                    name=name,
                    raw=ref.raw,
                    has_prompt_part=False,
                )
            )

        if ref.is_standalone_marker:
            raise ValueError(
                format_inline_workflow_reference_error(
                    name=name,
                    raw=ref.raw,
                    has_prompt_part=True,
                )
            )

        # Parse arguments (mirrors the real executor logic)
        positional_args, named_args = parse_workflow_reference_args(ref)
        match_end = ref.end

        # Build args dict with positional -> named mapping
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

        replacements.append((ref.start, match_end, prompt_part_content))

    # Replace right-to-left for position safety
    for start, end, replacement in sorted(
        replacements, key=lambda r: r[0], reverse=True
    ):
        prompt = prompt[:start] + replacement + prompt[end:]

    # Restore fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    return prompt
