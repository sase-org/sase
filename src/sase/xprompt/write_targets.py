"""Write-target resolution for editable xprompt definitions.

This module is intentionally UI-free.  ACE uses it when a definition is loaded
into the prompt bar, but the same policy applies to any frontend that edits an
existing xprompt source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.content_layout import (
    chezmoi_source_path,
    memory_reference_name,
    resolve_memory_file_sources,
)


@dataclass(frozen=True)
class XPromptWriteTarget:
    """Concrete file paths for editing an existing xprompt definition."""

    read_path: Path
    write_path: Path
    apply_target: Path | None
    via_chezmoi: bool


def resolve_xprompt_write_target(read_path: Path | str) -> XPromptWriteTarget:
    """Resolve where edits to *read_path* must be written.

    Home-managed paths are redirected to the matching chezmoi source only when
    chezmoi mode is enabled and that source file already exists.  The existence
    guard keeps unmanaged home files from being silently moved into the source
    tree.
    """

    read = Path(read_path).expanduser()
    default = XPromptWriteTarget(
        read_path=read,
        write_path=read,
        apply_target=None,
        via_chezmoi=False,
    )
    if not get_use_chezmoi():
        return default

    home = Path.home().expanduser()
    source_root = CHEZMOI_HOME.expanduser()
    read_resolved = read.resolve(strict=False)
    home_resolved = home.resolve(strict=False)
    source_resolved = source_root.resolve(strict=False)
    if not _is_relative_to(read_resolved, home_resolved):
        return default
    if _is_relative_to(read_resolved, source_resolved):
        return default

    source = chezmoi_source_path(
        read,
        home_root=home,
        source_root=source_root,
    )
    if not source.exists():
        return default
    return XPromptWriteTarget(
        read_path=read,
        write_path=source,
        apply_target=read,
        via_chezmoi=True,
    )


def canonical_reference_for_path(
    read_path: Path | str,
    *,
    write_path: Path | str | None = None,
    entry_name: str | None = None,
    reference: str | None = None,
) -> str:
    """Return the xprompt reference a user would type for a binding.

    Explicit references from a caller win for ordinary xprompts, while memory
    notes and skill sources are normalized from the path so a file stem never
    leaks into the target UI as ``#foo`` when the real handle is
    ``#memory/foo`` or ``/foo``.
    """

    read = Path(read_path).expanduser()
    candidates = (
        (read,) if write_path is None else (read, Path(write_path).expanduser())
    )
    if any(_looks_like_skill_source(path) for path in candidates):
        return f"/{read.stem}"
    if any(_looks_like_memory_note(path) for path in candidates):
        return f"#{memory_reference_name(read.stem)}"
    if reference:
        return reference
    if entry_name:
        return f"#{entry_name}"
    return f"#{read.stem}"


def _looks_like_memory_note(path: Path) -> bool:
    if path.suffix != ".md":
        return False
    for source in resolve_memory_file_sources():
        if _is_relative_to(
            path.resolve(strict=False), source.paths.write_path.resolve(strict=False)
        ):
            return True
    return _has_sase_ancestor(path, "memory")


def _looks_like_skill_source(path: Path) -> bool:
    if path.suffix != ".md":
        return False
    return _has_sase_ancestor(path, "skills")


def _has_sase_ancestor(path: Path, directory: str) -> bool:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == directory and index > 0 and parts[index - 1] == "sase":
            return True
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "XPromptWriteTarget",
    "canonical_reference_for_path",
    "resolve_xprompt_write_target",
]
