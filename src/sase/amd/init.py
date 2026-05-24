"""Planning and application for ``sase amd init``."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.main.init_plan import InitAction, InitPlan

from .constants import (
    AGENTS_FILENAME,
    LONG_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    PROVIDER_SHIM_CONTENT,
    PROVIDER_SHIM_FILES,
    SHORT_MEMORY_END_MARKER,
    SHORT_MEMORY_START_MARKER,
)

COMMAND_LABEL = "init amd"


@dataclass(frozen=True)
class _PlannedWrite:
    path: Path
    content: str
    action: InitAction


@dataclass(frozen=True)
class _AmdInitPlan:
    plan: InitPlan
    writes: tuple[_PlannedWrite, ...]


@dataclass(frozen=True)
class _AmdLongMemoryDescriptionUpdate:
    """Planned frontmatter update for a long-term memory file."""

    path: Path
    content: str


@dataclass(frozen=True)
class AmdMemorySyncPlan:
    """Files needed to keep AMD-managed memory blocks synchronized."""

    title: str | None
    agents_content: str | None
    description_updates: tuple[_AmdLongMemoryDescriptionUpdate, ...]
    blockers: tuple[str, ...] = ()


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{path}: failed to read file: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{path}: failed to decode as UTF-8: {exc}"


def _load_project_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    config_path = root / "sase.yml"
    if not config_path.exists():
        return None, None
    text, read_error = _read_text(config_path)
    if read_error is not None:
        return None, read_error
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        return None, f"{config_path}: failed to parse YAML: {exc}"
    if data is None:
        return None, None
    if not isinstance(data, dict):
        return None, f"{config_path}: expected a YAML mapping at the top level"
    raw = data.get("amd_h1_title")
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, f"{config_path}: amd_h1_title must be a string or null"
    title = raw.strip()
    if not title:
        return None, f"{config_path}: amd_h1_title must not be empty"
    return title, None


def _is_shim_text(text: str) -> bool:
    return text.strip() == PROVIDER_SHIM_CONTENT.strip()


def _provider_statuses(root: Path) -> tuple[dict[Path, str], tuple[str, ...]]:
    statuses: dict[Path, str] = {}
    errors: list[str] = []
    for filename in PROVIDER_SHIM_FILES:
        path = root / filename
        if not path.exists():
            statuses[path] = "missing"
            continue
        text, error = _read_text(path)
        if error is not None or text is None:
            statuses[path] = "custom"
            errors.append(error or f"{path}: failed to read file")
            continue
        if text == PROVIDER_SHIM_CONTENT:
            statuses[path] = "exact_shim"
        elif _is_shim_text(text):
            statuses[path] = "shim"
        else:
            statuses[path] = "custom"
    return statuses, tuple(errors)


def _action_for_write(path: Path, content: str, *, detail: str) -> InitAction | None:
    if not path.exists():
        return InitAction(path=path, operation="create", detail=detail)
    current, _error = _read_text(path)
    if current == content:
        return None
    return InitAction(path=path, operation="overwrite", detail=detail)


def _planned_write(path: Path, content: str, *, detail: str) -> _PlannedWrite | None:
    action = _action_for_write(path, content, detail=detail)
    if action is None:
        return None
    return _PlannedWrite(path=path, content=content, action=action)


def _provider_shim_writes(root: Path) -> tuple[_PlannedWrite, ...]:
    writes: list[_PlannedWrite] = []
    for filename in PROVIDER_SHIM_FILES:
        write = _planned_write(
            root / filename,
            PROVIDER_SHIM_CONTENT,
            detail="provider instruction shim",
        )
        if write is not None:
            writes.append(write)
    return tuple(writes)


_AGENTS_LONG_MEMORY_RE = re.compile(
    r"^\*\*`(?P<path>memory/long/[^`]+\.md)`\*\*[ \t]*\n(?P<body>.*?)(?=\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _existing_agents_long_descriptions(root: Path) -> dict[str, str]:
    agents_path = root / AGENTS_FILENAME
    if not agents_path.exists():
        return {}
    text, error = _read_text(agents_path)
    if error is not None or text is None:
        return {}
    descriptions: dict[str, str] = {}
    for match in _AGENTS_LONG_MEMORY_RE.finditer(text):
        body = " ".join(line.strip() for line in match.group("body").splitlines())
        body = " ".join(body.split())
        body = re.sub(r"\s+_Read when\b.*?_$", "", body).strip()
        if body:
            descriptions[match.group("path")] = body
    return descriptions


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw_frontmatter = text[4:end]
    body_start = end + len("\n---")
    if text[body_start : body_start + 1] == "\n":
        body_start += 1
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(loaded, dict):
        return {}, text[body_start:]
    return loaded, text[body_start:]


def _first_body_paragraph_or_h1(body: str) -> str:
    h1 = ""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and not h1:
            h1 = line[2:].strip()
            continue
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue
        if line.startswith("#"):
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    if paragraphs:
        return " ".join(" ".join(paragraphs[0]).split())
    return " ".join(h1.split())


def _long_memory_description(
    path: Path,
    *,
    root: Path,
    existing_agents_descriptions: dict[str, str],
) -> str:
    rel = path.relative_to(root).as_posix()
    text, error = _read_text(path)
    if error is not None or text is None:
        return path.stem.replace("_", " ").replace("-", " ").strip().capitalize()
    frontmatter, body = _split_frontmatter(text)
    raw_description = frontmatter.get("description")
    if isinstance(raw_description, str) and raw_description.strip():
        return " ".join(raw_description.split())
    existing = existing_agents_descriptions.get(rel)
    if existing:
        return existing
    fallback = _first_body_paragraph_or_h1(body)
    if fallback:
        return fallback
    return path.stem.replace("_", " ").replace("-", " ").strip().capitalize()


def _frontmatter_description_line(description: str) -> str:
    return yaml.safe_dump(
        {"description": description},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()


def _frontmatter_close_line_range(text: str) -> tuple[int, int] | None:
    if not text.startswith("---\n"):
        return None
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        line_start = offset
        offset += len(line)
        if index == 0:
            continue
        if line.strip() == "---":
            return line_start, offset
    return None


def _with_description_frontmatter(text: str, description: str) -> str:
    description_line = _frontmatter_description_line(description)
    close_range = _frontmatter_close_line_range(text)
    if close_range is None:
        return f"---\n{description_line}\n---\n{text}"

    close_start, _close_end = close_range
    before_close = text[:close_start]
    if not before_close.endswith("\n"):
        before_close = f"{before_close}\n"
    return f"{before_close}{description_line}\n{text[close_start:]}"


def _long_memory_descriptions(root: Path) -> dict[str, str]:
    existing_agents_descriptions = _existing_agents_long_descriptions(root)
    return {
        path.relative_to(root).as_posix(): _long_memory_description(
            path,
            root=root,
            existing_agents_descriptions=existing_agents_descriptions,
        )
        for path in _iter_memory_markdown(root, "long")
    }


def _long_memory_description_updates(
    root: Path, descriptions: dict[str, str]
) -> tuple[_AmdLongMemoryDescriptionUpdate, ...]:
    updates: list[_AmdLongMemoryDescriptionUpdate] = []
    for path in _iter_memory_markdown(root, "long"):
        rel = path.relative_to(root).as_posix()
        description = descriptions[rel]
        text, error = _read_text(path)
        if error is not None or text is None:
            continue
        frontmatter, _body = _split_frontmatter(text)
        raw_description = frontmatter.get("description")
        if isinstance(raw_description, str) and raw_description.strip():
            continue
        content = _with_description_frontmatter(text, description)
        if content != text:
            updates.append(
                _AmdLongMemoryDescriptionUpdate(
                    path=path,
                    content=content,
                )
            )
    return tuple(updates)


def _iter_memory_markdown(root: Path, tier: str) -> tuple[Path, ...]:
    memory_root = root / "memory" / tier
    if not memory_root.exists():
        return ()
    return tuple(sorted(path for path in memory_root.rglob("*.md") if path.is_file()))


def _short_memory_references(root: Path) -> tuple[str, ...]:
    refs = {Path("memory/short/sase.md")}
    refs.update(path.relative_to(root) for path in _iter_memory_markdown(root, "short"))
    return tuple(f"@{path.as_posix()}" for path in sorted(refs))


def _render_managed_agents(
    root: Path,
    title: str,
    *,
    long_memory_descriptions: dict[str, str] | None = None,
) -> str:
    """Render the project-managed AMD ``AGENTS.md`` content for *root*."""
    existing_descriptions = _existing_agents_long_descriptions(root)
    long_paths = _iter_memory_markdown(root, "long")
    descriptions = long_memory_descriptions or {}

    lines = [
        f"# {title}",
        "",
        "IMPORTANT: You should not modify any of these memory files without "
        "approval from the user.",
        "",
        "## Tier 1 (short-term) Memory",
        "",
        "The following memory files contain core (always loaded) context:",
        "",
        SHORT_MEMORY_START_MARKER,
        "",
    ]
    lines.extend(f"- {ref}" for ref in _short_memory_references(root))
    lines.extend(
        [
            SHORT_MEMORY_END_MARKER,
            "",
            "## Tier 2 (dynamic) Memory",
            "",
            "When a user prompt matches keywords from dynamic memories, we "
            "append a `### DYNAMIC MEMORY` section at the bottom of",
            "that prompt listing individual `.sase/memory/` file paths \u2014 one "
            "per matched memory:",
            "",
            "```",
            "### DYNAMIC MEMORY",
            "- @.sase/memory/long-facts-about-foobar.md "
            "(memory/long/facts_about_foobar, matched: `foobar facts`)",
            "```",
            "",
            "File names use a prefix that encodes the source tier: `long-` "
            "means the file originates from a long-term (tier 3) memory",
            "source. If a `long-` prefixed file appears in your dynamic memory "
            "section, it contains the same content as the",
            "corresponding tier 3 file below \u2014 you do NOT need to separately "
            "read the tier 3 file.",
            "",
            "## Tier 3 (long-term) Memory",
            "",
            "The below files contain detailed reference material. When working "
            "in their domain, you MUST use your `/sase_memory_read`",
            "skill to review their contents. Do not read canonical "
            "`memory/long/*.md` files directly.",
            "",
            "#### Long-Term Memory Files",
            "",
            LONG_MEMORY_START_MARKER,
            "",
        ]
    )
    for index, path in enumerate(long_paths):
        if index:
            lines.append("")
        rel = path.relative_to(root).as_posix()
        description = descriptions.get(rel) or _long_memory_description(
            path,
            root=root,
            existing_agents_descriptions=existing_descriptions,
        )
        lines.append(f"**`{rel}`**  ")
        lines.append(description)
    lines.extend(["", LONG_MEMORY_END_MARKER, ""])
    return "\n".join(lines)


def plan_amd_memory_sync(root: Path | None = None) -> AmdMemorySyncPlan:
    """Plan AMD-managed memory block synchronization for ``sase memory init``."""
    root = root or Path.cwd()
    title, title_error = _load_project_amd_h1_title(root)
    if title_error is not None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            description_updates=(),
            blockers=(title_error,),
        )
    if title is None:
        return AmdMemorySyncPlan(
            title=None,
            agents_content=None,
            description_updates=(),
        )

    descriptions = _long_memory_descriptions(root)
    updates = _long_memory_description_updates(root, descriptions)
    agents_content = _render_managed_agents(
        root,
        title,
        long_memory_descriptions=descriptions,
    )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        description_updates=updates,
    )


def _migration_writes(
    root: Path,
    provider_statuses: dict[Path, str],
) -> tuple[tuple[_PlannedWrite, ...], tuple[str, ...]]:
    agents_path = root / AGENTS_FILENAME
    if agents_path.exists():
        return (), ()

    custom_provider_paths = tuple(
        path for path, status in provider_statuses.items() if status == "custom"
    )
    shim_provider_paths = tuple(
        path
        for path, status in provider_statuses.items()
        if status in {"exact_shim", "shim"}
    )

    if len(custom_provider_paths) > 1:
        names = ", ".join(path.name for path in custom_provider_paths)
        return (), (
            f"{AGENTS_FILENAME} is missing and multiple provider instruction "
            f"files contain custom content: {names}",
        )

    if len(custom_provider_paths) == 0:
        if shim_provider_paths:
            names = ", ".join(path.name for path in shim_provider_paths)
            return (), (
                f"{AGENTS_FILENAME} is missing but provider shim files already "
                f"point to it: {names}",
            )
        return (), ()

    source_path = custom_provider_paths[0]
    source_text, error = _read_text(source_path)
    if error is not None or source_text is None:
        return (), (error or f"{source_path}: failed to read legacy provider file",)

    writes: list[_PlannedWrite] = []
    agents_write = _planned_write(
        agents_path,
        source_text,
        detail=f"migrate {source_path.name} to AGENTS.md",
    )
    if agents_write is not None:
        writes.append(agents_write)
    writes.extend(_provider_shim_writes(root))
    return tuple(writes), ()


def _summarize_amd_actions(
    actions: tuple[InitAction, ...], blockers: tuple[str, ...]
) -> str:
    if blockers:
        return "cannot initialize agent markdown documents until blockers are fixed"
    if not actions:
        return "agent markdown documents are current"
    if len(actions) == 1:
        action = actions[0]
        return f"{action.operation} {action.detail}"
    operations = {action.operation for action in actions}
    if operations == {"create"}:
        verb = "create"
    elif operations == {"overwrite"}:
        verb = "overwrite"
    else:
        verb = "refresh"
    return f"{verb} {len(actions)} agent markdown documents"


def _build_amd_init_plan(
    root: Path | None = None, *, explicit: bool = True
) -> _AmdInitPlan:
    """Return the pure AMD init plan for *root* without writing files."""
    root = root or Path.cwd()
    title, title_error = _load_project_amd_h1_title(root)
    provider_statuses, provider_errors = _provider_statuses(root)
    blockers = tuple(error for error in (title_error, *provider_errors) if error)
    writes: list[_PlannedWrite] = []

    if not blockers:
        if title is not None:
            agents_write = _planned_write(
                root / AGENTS_FILENAME,
                _render_managed_agents(root, title),
                detail="managed AGENTS.md",
            )
            if agents_write is not None:
                writes.append(agents_write)
            writes.extend(_provider_shim_writes(root))
        elif not explicit:
            pass
        else:
            migration_writes, migration_blockers = _migration_writes(
                root,
                provider_statuses,
            )
            blockers = migration_blockers
            if not blockers:
                writes.extend(migration_writes)
                if not migration_writes:
                    writes.extend(_provider_shim_writes(root))

    actions = tuple(write.action for write in writes)
    return _AmdInitPlan(
        plan=InitPlan(
            command="amd",
            label="AMD",
            summary=_summarize_amd_actions(actions, blockers),
            actions=actions,
            blockers=blockers,
        ),
        writes=tuple(writes),
    )


def _plan_amd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for ``sase amd init``."""
    is_bare_onboarding = (
        getattr(args, "command", None) == "init"
        and getattr(args, "init_subcommand", None) is None
    )
    explicit = not is_bare_onboarding
    return _build_amd_init_plan(explicit=explicit).plan


def plan_amd_init(args: argparse.Namespace) -> InitPlan:
    """Return a read-only AMD init plan for onboarding registries."""
    return _plan_amd_init(args)


def _print_blockers(blockers: tuple[str, ...]) -> None:
    for blocker in blockers:
        print(f"{COMMAND_LABEL}: {blocker}", file=sys.stderr)


def run_amd_init(args: argparse.Namespace) -> int:
    """Apply ``sase amd init`` and return a process exit code."""
    if getattr(args, "check", False):
        from sase.main.init_onboarding import run_init_check
        from sase.main.init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="amd",
                    label="AMD",
                    plan=_plan_amd_init,
                    run=run_amd_init,
                ),
            ),
        )

    built = _build_amd_init_plan()
    if built.plan.blockers:
        _print_blockers(built.plan.blockers)
        return 1

    written: list[Path] = []
    for write in built.writes:
        write.path.parent.mkdir(parents=True, exist_ok=True)
        write.path.write_text(write.content, encoding="utf-8")
        written.append(write.path)

    if written:
        print(f"{COMMAND_LABEL}: initialized agent markdown documents")
        for path in written:
            print(f"  {path}")
    else:
        print(f"{COMMAND_LABEL}: agent markdown documents are current")
    return 0


__all__ = [
    "AmdMemorySyncPlan",
    "plan_amd_memory_sync",
    "plan_amd_init",
    "run_amd_init",
]
