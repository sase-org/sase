"""Catalog fetchers for project content: glossary terms and memory notes.

Both read through the project's resolved content layout; see
:mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

from pathlib import Path

from sase.completion.candidates.catalog_support import (
    dedupe,
    project_records_and_snapshot,
)
from sase.completion.candidates.protocol import Candidate


def _project_config_path(project: str | None) -> Path | None:
    """Return the ``sase.yml`` read path for *project*, or the current one."""
    from sase.content_layout import (
        discover_project_root,
        resolve_project_config_read_path,
    )

    root: Path | None = None
    if project is None:
        try:
            root = discover_project_root() or Path.cwd()
        except OSError:
            return None
    else:
        records, _snapshot = project_records_and_snapshot(project)
        for record in records:
            workspace_dir = (record.workspace_dir or "").strip()
            if workspace_dir:
                root = Path(workspace_dir)
                break
    if root is None:
        return None
    try:
        return resolve_project_config_read_path(root)
    except Exception:
        return None


def _glossary_reference(text: str) -> str:
    """Return the slug-form reference for a glossary term or alias.

    ``sase glossary`` resolves references case-insensitively and treats
    ``-``, ``_``, and whitespace as equivalent, so the hyphenated lowercase
    form of a multi-word term is both a valid reference and the one shape
    that never needs shell quoting.
    """
    return "-".join(text.casefold().split())


def glossary_source_path(project: str | None) -> Path | None:
    """Return the ``sase.yml`` whose mtime invalidates glossary candidates."""
    return _project_config_path(project)


def glossary_candidates(project: str | None) -> list[Candidate]:
    """Return every glossary term and alias, in slug reference form."""
    import yaml  # type: ignore[import-untyped]

    from sase._yaml_safe import yaml_safe_load
    from sase.completion.shorten import short_summary
    from sase.glossary_config import resolve_glossary_config

    path = _project_config_path(project)
    if path is None:
        return []
    try:
        config = yaml_safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(config, dict):
        return []
    node = resolve_glossary_config(config).node
    if not isinstance(node, dict):
        return []

    candidates: list[Candidate] = []
    for raw_term, raw_entry in node.items():
        term = str(raw_term).strip()
        if not term:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        candidates.append(
            Candidate(
                _glossary_reference(term),
                short_summary(str(entry.get("definition") or "")),
            )
        )
        raw_aliases = entry.get("aliases")
        if not isinstance(raw_aliases, list):
            continue
        for raw_alias in raw_aliases:
            alias = str(raw_alias).strip()
            if alias:
                candidates.append(
                    Candidate(_glossary_reference(alias), f"alias of {term}")
                )
    return dedupe(candidates)


def memory_source_path(_project: str | None) -> Path | None:
    """Return the memory directory whose mtime invalidates memory candidates."""
    from sase.content_layout import discover_project_root, resolve_project_layout

    try:
        root = discover_project_root() or Path.cwd()
        return resolve_project_layout(root).memory.resolve_read("memory")
    except OSError:
        return None


def memory_candidates(_project: str | None) -> list[Candidate]:
    """Return every memory note file name, README excluded."""
    memory_root = memory_source_path(None)
    if memory_root is None or not memory_root.is_dir():
        return []
    candidates: list[Candidate] = []
    for path in sorted(memory_root.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        candidates.append(Candidate(path.name, "memory note"))
    return dedupe(candidates)


__all__ = [
    "glossary_candidates",
    "glossary_source_path",
    "memory_candidates",
    "memory_source_path",
]
