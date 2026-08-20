"""Mtime-keyed, names-only indexes and lazy save-preview reads."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Literal

import yaml  # type: ignore[import-untyped]

from .prompt_frontmatter import PromptFrontmatter
from .save import load_config_xprompt_markdown
from .config_yaml import generate_xprompt_yaml
from .snippet_config_yaml import generate_snippet_yaml

IndexKind = Literal["directory", "xprompt_config", "snippet_config"]
DefinitionKind = Literal["markdown", "xprompt_config", "snippet_config"]

_INDEX_CACHE: dict[tuple[IndexKind, str], tuple[tuple[int, int], frozenset[str]]] = {}
_DEFINITION_CACHE: dict[
    tuple[DefinitionKind, str, str], tuple[tuple[int, int], str]
] = {}
_CACHE_LOCK = Lock()


def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def names_for_location(kind: IndexKind, path: str) -> frozenset[str]:
    """Return names stored at one location without loading definitions."""
    location = Path(path)
    signature = _signature(location)
    key = (kind, str(location))
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    if kind == "directory":
        names = (
            frozenset(entry.stem for entry in location.glob("*.md") if entry.is_file())
            if location.is_dir()
            else frozenset()
        )
    else:
        names = _config_names(location, snippet=kind == "snippet_config")

    with _CACHE_LOCK:
        _INDEX_CACHE[key] = (signature, names)
    return names


def _config_names(path: Path, *, snippet: bool) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return frozenset()
    if not isinstance(payload, dict):
        return frozenset()
    mapping: object
    if snippet:
        ace = payload.get("ace")
        mapping = ace.get("snippets") if isinstance(ace, dict) else None
    else:
        mapping = payload.get("xprompts")
    if not isinstance(mapping, dict):
        return frozenset()
    return frozenset(str(name) for name in mapping)


def load_definition(
    kind: DefinitionKind,
    path: str,
    name: str,
) -> str:
    """Load one colliding definition lazily, cached by target mtime."""
    source = Path(path)
    signature = _signature(source)
    key = (kind, str(source), name)
    with _CACHE_LOCK:
        cached = _DEFINITION_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    if kind == "markdown":
        text = source.read_text(encoding="utf-8")
    elif kind == "xprompt_config":
        markdown = load_config_xprompt_markdown(source, name)
        frontmatter, body = _split_markdown(markdown)
        lines = [
            "xprompts:",
            *generate_xprompt_yaml(name, [], body, frontmatter=frontmatter),
        ]
        text = "\n".join(lines) + "\n"
    else:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        ace = payload.get("ace", {}) if isinstance(payload, dict) else {}
        snippets = ace.get("snippets", {}) if isinstance(ace, dict) else {}
        if not isinstance(snippets, dict) or name not in snippets:
            raise KeyError(name)
        lines = [
            "ace:",
            "  snippets:",
            *generate_snippet_yaml(name, str(snippets[name])),
        ]
        text = "\n".join(lines) + "\n"

    with _CACHE_LOCK:
        _DEFINITION_CACHE[key] = (signature, text)
    return text


def invalidate_save_index(path: str | Path | None = None) -> None:
    """Drop cached names and definitions, optionally for one location only."""
    if path is None:
        with _CACHE_LOCK:
            _INDEX_CACHE.clear()
            _DEFINITION_CACHE.clear()
        return
    location = str(Path(path))
    with _CACHE_LOCK:
        index_keys = [item for item in _INDEX_CACHE if item[1] == location]
        definition_keys = [item for item in _DEFINITION_CACHE if item[1] == location]
        for index_key in index_keys:
            _INDEX_CACHE.pop(index_key, None)
        for definition_key in definition_keys:
            _DEFINITION_CACHE.pop(definition_key, None)


def _split_markdown(markdown: str) -> tuple[PromptFrontmatter, str]:
    if not markdown.startswith("---"):
        return PromptFrontmatter(), markdown.rstrip("\n")
    lines = markdown.splitlines()
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return PromptFrontmatter(), markdown.rstrip("\n")
    raw = "\n".join(lines[: closing + 1])
    return PromptFrontmatter.parse(raw), "\n".join(lines[closing + 1 :]).lstrip("\n")


__all__ = [
    "DefinitionKind",
    "IndexKind",
    "invalidate_save_index",
    "load_definition",
    "names_for_location",
]
