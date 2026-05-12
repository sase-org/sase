"""Auto-discovery of ``memory/long/*.md`` files as keyword-triggered xprompts."""

from pathlib import Path

from .loader_parsing import parse_yaml_front_matter
from .models import XPrompt


def _get_memory_long_search_dirs() -> list[tuple[Path, bool]]:
    """Return directories to scan for ``memory/long/*.md`` files.

    Each entry is ``(directory, is_cwd_relative)`` where *is_cwd_relative*
    controls whether ``$(cat ...)`` uses a CWD-relative or absolute path.

    Priority order (first wins on name collision):
    1. ``<cwd>/memory/long/``
    2. ``<cwd>/.claude/memory/long/``
    3. ``<cwd>/.gemini/memory/long/``
    4. ``<cwd>/.codex/memory/long/``
    5. ``~/.claude/memory/long/``
    6. ``~/.gemini/memory/long/``
    7. ``~/.codex/memory/long/``
    """
    cwd = Path.cwd()
    home = Path.home()
    return [
        (cwd / "memory" / "long", True),
        (cwd / ".claude" / "memory" / "long", True),
        (cwd / ".gemini" / "memory" / "long", True),
        (cwd / ".codex" / "memory" / "long", True),
        (home / ".claude" / "memory" / "long", False),
        (home / ".gemini" / "memory" / "long", False),
        (home / ".codex" / "memory" / "long", False),
    ]


def load_memory_long_xprompts() -> dict[str, XPrompt]:
    """Auto-discover ``memory/long/*.md`` files with ``keywords`` frontmatter.

    Files with a ``keywords`` field in their YAML frontmatter are treated as
    memory xprompts.  The generated xprompt uses ``$(cat <path>)`` for shell
    substitution — relative paths for CWD-based files, absolute for home-based.

    Returns:
        Dictionary mapping ``memory/long/<stem>`` to XPrompt objects.
    """
    from .tags import XPromptTag

    cwd = Path.cwd()
    xprompts: dict[str, XPrompt] = {}

    # Process in reverse priority order so higher-priority dirs overwrite.
    for search_dir, is_cwd_relative in reversed(_get_memory_long_search_dirs()):
        if not search_dir.is_dir():
            continue

        for md_file in sorted(search_dir.glob("*.md")):
            if not md_file.is_file():
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            front_matter, _ = parse_yaml_front_matter(content)
            if not front_matter or "keywords" not in front_matter:
                continue

            keywords = front_matter["keywords"]
            if not isinstance(keywords, list):
                continue

            name = f"memory/long/{md_file.stem}"

            if is_cwd_relative:
                cat_path = str(md_file.relative_to(cwd))
            else:
                cat_path = str(md_file)

            xprompts[name] = XPrompt(
                name=name,
                content=f"$(cat {cat_path})",
                tags=frozenset({XPromptTag.memory}),
                keywords=keywords,
                source_path=str(md_file),
            )

    return xprompts
