"""Memory rendering and synchronization for AMD-managed instructions."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

from ._config import load_amd_h1_title
from ._shared import (
    AmdLongMemoryDescriptionUpdate,
    AmdMemorySyncPlan,
    read_text,
)
from .constants import (
    AGENTS_FILENAME,
    LONG_MEMORY_END_MARKER,
    LONG_MEMORY_START_MARKER,
    SHORT_MEMORY_END_MARKER,
    SHORT_MEMORY_START_MARKER,
)

_AGENTS_LONG_MEMORY_RE = re.compile(
    r"^\*\*`(?P<path>memory/long/[^`]+\.md)`\*\*[ \t]*\n(?P<body>.*?)(?=\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _existing_agents_long_descriptions(root: Path) -> dict[str, str]:
    agents_path = root / AGENTS_FILENAME
    if not agents_path.exists():
        return {}
    text, error = read_text(agents_path)
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
    text, error = read_text(path)
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
) -> tuple[AmdLongMemoryDescriptionUpdate, ...]:
    updates: list[AmdLongMemoryDescriptionUpdate] = []
    for path in _iter_memory_markdown(root, "long"):
        rel = path.relative_to(root).as_posix()
        description = descriptions[rel]
        text, error = read_text(path)
        if error is not None or text is None:
            continue
        frontmatter, _body = _split_frontmatter(text)
        raw_description = frontmatter.get("description")
        if isinstance(raw_description, str) and raw_description.strip():
            continue
        content = _with_description_frontmatter(text, description)
        if content != text:
            updates.append(
                AmdLongMemoryDescriptionUpdate(
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


def render_managed_agents(
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
        "## Short-Term Memory Files",
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
        ]
    )
    lines.extend(
        [
            "## Long-Term Memory Files",
            "",
            "The below files contain detailed reference material. When working "
            "in their domain, you MUST use your `/sase_memory_read`",
            "skill to review their contents. Do not read canonical "
            "`memory/long/*.md` files directly.",
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
    title, title_error = load_amd_h1_title(root)
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
    agents_content = render_managed_agents(
        root,
        title,
        long_memory_descriptions=descriptions,
    )
    return AmdMemorySyncPlan(
        title=title,
        agents_content=agents_content,
        description_updates=updates,
    )
