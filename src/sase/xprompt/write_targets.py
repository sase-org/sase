"""Write-target resolution for editable xprompt definitions.

This module is intentionally UI-free.  ACE uses it when a definition is loaded
into the prompt bar, but the same policy applies to any frontend that edits an
existing xprompt source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import subprocess

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi
from sase.content_layout import (
    chezmoi_source_path,
    memory_reference_name,
    resolve_memory_file_sources,
)
from sase.xprompt.skill_locations import is_canonical_skill_directory


@dataclass(frozen=True)
class XPromptWriteTarget:
    """Concrete file paths for editing an existing xprompt definition."""

    read_path: Path
    write_path: Path
    apply_target: Path | None
    via_chezmoi: bool


XPromptWriteTarget = _XPromptWriteTarget


class WrittenFileKind(StrEnum):
    """Kind of source file written by an xprompt save surface."""

    XPROMPT = "xprompt"
    MEMORY_NOTE = "memory_note"
    SKILL_SOURCE = "skill_source"
    CONFIG_ENTRY = "config_entry"


class PostWriteActionKind(StrEnum):
    """Follow-up action offered after a file write."""

    COMMIT_PUSH = "commit_push"
    APPLY_CHEZMOI = "apply_chezmoi"
    MEMORY_INIT = "memory_init"
    SKILL_INIT = "skill_init"


@dataclass(frozen=True)
class PostWriteActionOffer:
    """One selectable post-write action."""

    kind: PostWriteActionKind
    key: str
    label: str
    subtitle: str
    default_on: bool
    file_path: str
    rel_path: str
    git_root: str | None = None
    commit_message: str | None = None
    apply_target: str | None = None
    command: tuple[str, ...] = ()


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


def write_target_for_written_path(path: Path | str) -> XPromptWriteTarget:
    """Return a write target for a path that is already the write location.

    Save-as destinations and external-editor surfaces often operate directly on
    the chezmoi source path.  In that case there is no pre-remap read path, but
    the source path still maps to one safe scoped ``chezmoi apply`` target.
    """

    write = Path(path).expanduser()
    apply_target = _chezmoi_apply_target_for_source(write)
    return XPromptWriteTarget(
        read_path=apply_target or write,
        write_path=write,
        apply_target=apply_target,
        via_chezmoi=apply_target is not None,
    )


def _chezmoi_apply_target_for_source(path: Path | str) -> Path | None:
    """Return the home target represented by a chezmoi source path, if clear."""

    if not get_use_chezmoi():
        return None
    source = Path(path).expanduser().resolve(strict=False)
    root = CHEZMOI_HOME.expanduser().resolve(strict=False)
    try:
        relative = source.relative_to(root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    decoded = tuple(
        f".{part[4:]}" if part.startswith("dot_") else part for part in relative.parts
    )
    return Path.home().expanduser().joinpath(*decoded)


def classify_written_file(
    path: Path | str,
    *,
    read_path: Path | str | None = None,
) -> WrittenFileKind:
    """Classify a written source path without reading file contents.

    When a read path is available, it wins for memory/skill detection.  A
    chezmoi source path may sit outside the normal home memory root, while the
    original read path still describes the user's xprompt reference surface.
    """

    if read_path is not None:
        read_kind = _classify_single_written_path(Path(read_path).expanduser())
        if read_kind is not WrittenFileKind.XPROMPT:
            return read_kind
    return _classify_single_written_path(Path(path).expanduser())


def build_post_write_action_offers(
    target: XPromptWriteTarget,
    *,
    kind: WrittenFileKind,
    is_new: bool,
    xprompt_name: str,
    noun: str = "xprompt",
    commit_type: str = "xprompt",
) -> tuple[PostWriteActionOffer, ...]:
    """Return the ordered follow-up actions that apply to *target*.

    This probes git state and path policy only.  Callers must run it off the
    Textual event loop.
    """

    rel_path = _display_rel_path(target.write_path)
    if kind is WrittenFileKind.MEMORY_NOTE:
        return (
            PostWriteActionOffer(
                kind=PostWriteActionKind.MEMORY_INIT,
                key="m",
                label="sase memory init",
                subtitle=(
                    "Regenerates AGENTS.md and provider shims, then commits "
                    "and pushes for you."
                ),
                default_on=True,
                file_path=str(target.write_path),
                rel_path=rel_path,
                command=("sase", "memory", "init"),
            ),
        )
    if kind is WrittenFileKind.SKILL_SOURCE:
        return (
            PostWriteActionOffer(
                kind=PostWriteActionKind.SKILL_INIT,
                key="s",
                label="sase skill init",
                subtitle=(
                    "Regenerates and deploys skills, then commits and pushes for you."
                ),
                default_on=True,
                file_path=str(target.write_path),
                rel_path=rel_path,
                command=("sase", "skill", "init"),
            ),
        )

    offers: list[PostWriteActionOffer] = []
    git_offer = _commit_push_offer(
        target,
        is_new=is_new,
        xprompt_name=xprompt_name,
        noun=noun,
        commit_type=commit_type,
    )
    if git_offer is not None:
        offers.append(git_offer)
    if target.via_chezmoi and target.apply_target is not None:
        offers.append(
            PostWriteActionOffer(
                kind=PostWriteActionKind.APPLY_CHEZMOI,
                key="a",
                label="Apply chezmoi",
                subtitle=f"Applies only {target.apply_target}.",
                default_on=True,
                file_path=str(target.write_path),
                rel_path=rel_path,
                apply_target=str(target.apply_target),
            )
        )
    return tuple(offers)


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


def _classify_single_written_path(path: Path) -> WrittenFileKind:
    if path.suffix == ".md" and is_canonical_skill_directory(path.parent):
        return WrittenFileKind.SKILL_SOURCE
    if path.suffix == ".md" and _looks_like_memory_note(path):
        return WrittenFileKind.MEMORY_NOTE
    if path.suffix in {".yml", ".yaml"}:
        return WrittenFileKind.CONFIG_ENTRY
    return WrittenFileKind.XPROMPT


def _commit_push_offer(
    target: XPromptWriteTarget,
    *,
    is_new: bool,
    xprompt_name: str,
    noun: str,
    commit_type: str,
) -> PostWriteActionOffer | None:
    git_root = get_git_root(target.write_path)
    if git_root is None or not has_git_changes(git_root, target.write_path):
        return None
    rel_path = os.path.relpath(target.write_path, git_root)
    verb = "Add" if is_new else "Update"
    subject = f"chore: {verb} {noun} {xprompt_name}"
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    return PostWriteActionOffer(
        kind=PostWriteActionKind.COMMIT_PUSH,
        key="c",
        label="Commit & push",
        subtitle="Stages this file, commits, rebases, and pushes.",
        default_on=True,
        file_path=str(target.write_path),
        rel_path=rel_path,
        git_root=git_root,
        commit_message=apply_auto_commit_type_tag(subject, commit_type),
    )


def get_git_root(file_path: Path | str) -> str | None:
    """Return the git repo root for *file_path*, or ``None`` outside git."""

    directory = str(Path(file_path).parent)
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def has_git_changes(git_root: str, file_path: Path | str) -> bool:
    """Return whether *file_path* has staged or unstaged git changes."""

    try:
        result = subprocess.run(
            ["git", "-C", git_root, "status", "--porcelain", "--", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


def _display_rel_path(path: Path) -> str:
    git_root = get_git_root(path)
    if git_root is not None:
        return os.path.relpath(path, git_root)
    try:
        return str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


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
    "PostWriteActionKind",
    "PostWriteActionOffer",
    "WrittenFileKind",
    "XPromptWriteTarget",
    "build_post_write_action_offers",
    "canonical_reference_for_path",
    "classify_written_file",
    "get_git_root",
    "has_git_changes",
    "resolve_xprompt_write_target",
    "write_target_for_written_path",
]
