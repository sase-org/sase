"""Catalog fetchers for prompt assets: xprompts, skills, and xprompt tags.

Xprompts and skills are discovered by walking the packaged and configured
file source roots; see :mod:`sase.completion.candidates.catalog` for the
import contract.
"""

from __future__ import annotations

import importlib.resources
import os
from collections.abc import Iterator
from pathlib import Path

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate

_PROMPT_SUFFIXES = frozenset({".md", ".yml", ".yaml"})
_SKIP_XPROMPT_DIR_NAMES = frozenset({"skills"})
_SKIP_PROMPT_NAMES = frozenset(
    {"skill.frame.template.md", "workflow.schema.json", "readme.md"}
)
_XPROMPT_TAGS: tuple[str, ...] = (
    "vcs",
    "crs",
    "fix_hook",
    "rollover",
    "mentor",
    "commit",
    "propose",
    "make_mentor_changes",
    "diff_file",
    "append_to_pr",
    "append_to_commit_and_propose",
    "create_epic_bead",
    "work_phase_bead",
    "work_task_bead",
    "land_epic",
)


def _package_dir(*parts: str) -> Path | None:
    candidate = Path(str(importlib.resources.files("sase").joinpath(*parts)))
    return candidate if candidate.is_dir() else None


def _iter_named_files(
    root: Path, *, skip_dirs: frozenset[str] = frozenset()
) -> Iterator[Path]:
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in skip_dirs and not name.startswith(".")
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            if filename.casefold() in _SKIP_PROMPT_NAMES:
                continue
            path = Path(dirpath) / filename
            if path.suffix.lower() in _PROMPT_SUFFIXES:
                yield path


def xprompt_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: xprompt roots are multi-rooted."""
    return None


def xprompt_candidates(_project: str | None) -> list[Candidate]:
    """Return every xprompt name across the packaged and configured roots."""
    from sase.content_layout import resolve_xprompt_file_sources

    roots: list[Path] = []
    packaged = _package_dir("xprompts")
    if packaged is not None:
        roots.append(packaged)
    defaults = _package_dir("default_xprompts")
    if defaults is not None:
        roots.append(defaults)
    try:
        roots.extend(
            source.path
            for source in resolve_xprompt_file_sources()
            if source.path is not None
        )
    except OSError:
        pass
    candidates: list[Candidate] = []
    for root in roots:
        for path in _iter_named_files(root, skip_dirs=_SKIP_XPROMPT_DIR_NAMES):
            relative = path.relative_to(root).with_suffix("")
            candidates.append(Candidate(relative.as_posix(), root.name))
    return dedupe(candidates)


def skill_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: skill roots are multi-rooted."""
    return None


def skill_candidates(_project: str | None) -> list[Candidate]:
    """Return every skill name across the packaged and configured roots."""
    from sase.content_layout import resolve_skill_file_sources

    roots: list[Path] = []
    packaged = _package_dir("xprompts", "skills")
    if packaged is not None:
        roots.append(packaged)
    try:
        roots.extend(
            source.path
            for source in resolve_skill_file_sources()
            if source.path is not None
        )
    except OSError:
        pass
    candidates: list[Candidate] = []
    for root in roots:
        for path in _iter_named_files(root):
            candidates.append(Candidate(path.stem, "skill"))
    return dedupe(candidates)


def tag_source_path(_project: str | None) -> Path | None:
    """Return no cache-invalidation path: xprompt tags are compiled in."""
    return None


def tag_candidates(_project: str | None) -> list[Candidate]:
    """Return the built-in xprompt tags."""
    return [Candidate(tag, "xprompt tag") for tag in _XPROMPT_TAGS]


__all__ = [
    "skill_candidates",
    "skill_source_path",
    "tag_candidates",
    "tag_source_path",
    "xprompt_candidates",
    "xprompt_source_path",
]
