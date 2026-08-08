"""Shared PARENT-section checking for SDD plan validation and repair.

A workspace's plans checkout is a snapshot of an asynchronously published
store: a phase plan can land before the epic plan its ``PARENT`` header points
at. Treating that window as a hard error reddens ``just check`` for every agent
in the workspace over a file none of them wrote or can produce, so the severity
here is scoped to what the workspace actually owns -- plan files with local
changes -- and an already-published plan whose parent has yet to land is
reported as a pending-publication warning instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sase.sdd._link_models import SddFile, SddIssue
from sase.sdd.plan_header_block import (
    PlanHeaderSection,
    PlanHeaderSectionKind,
)

_PARENT_MISSING_CODE = "parent-missing-target"
_PARENT_UNPUBLISHED_CODE = "parent-unpublished"


@dataclass
class LocalPlanChanges:
    """Lazy view of which plan files the current workspace owns locally.

    A plan file is owned when the plans checkout reports it as added,
    modified, or untracked. When the root is not a usable git checkout every
    file counts as owned, which keeps standalone plan trees strict.
    """

    root: Path
    _paths: frozenset[Path] | None = field(default=None, init=False)
    _loaded: bool = field(default=False, init=False)

    def owns(self, path: Path) -> bool:
        """Return whether *path* carries local, unpublished changes."""

        if not self._loaded:
            self._paths = _local_git_changes(self.root)
            self._loaded = True
        if self._paths is None:
            return True
        return path.resolve(strict=False) in self._paths


def _parent_section_label(sections: tuple[PlanHeaderSection, ...]) -> str | None:
    """Return the PARENT header label when the plan declares one."""

    parent = next(
        (
            section
            for section in sections
            if section.kind is PlanHeaderSectionKind.PARENT
        ),
        None,
    )
    return None if parent is None else parent.label


def _parent_target_resolves(root: Path, label: str) -> bool:
    """Return whether *label* names a plan file present under *root*."""

    from sase.sdd._paths import has_month_dirs
    from sase.sdd.plan_refs import resolve_plan_reference_from_roots

    plans_root = root / "plans" if has_month_dirs(root / "plans") else root
    resolution = resolve_plan_reference_from_roots(label, roots=(plans_root,))
    resolved = resolution.resolved_path
    return resolved is not None and resolved.is_file()


def parent_section_issue(
    root: Path,
    file: SddFile,
    sections: tuple[PlanHeaderSection, ...],
    changes: LocalPlanChanges,
) -> SddIssue | None:
    """Return the PARENT issue for *file*, or ``None`` when it resolves."""

    label = _parent_section_label(sections)
    if label is None or _parent_target_resolves(root, label):
        return None
    if changes.owns(file.path):
        return SddIssue(
            severity="error",
            code=_PARENT_MISSING_CODE,
            path=file.relpath,
            message=f"PARENT target does not resolve to a plan file: {label}",
        )
    return SddIssue(
        severity="warning",
        code=_PARENT_UNPUBLISHED_CODE,
        path=file.relpath,
        message=(
            f"PARENT target is not published to the plans store yet: {label}; "
            "this plan is already published, so the reference resolves once "
            "the parent plan lands"
        ),
    )


def _local_git_changes(root: Path) -> frozenset[Path] | None:
    """Return absolute paths git reports as locally changed under *root*."""

    from sase.sdd._git import run_sdd_git

    if not root.is_dir():
        return None
    try:
        toplevel = run_sdd_git(
            ["rev-parse", "--show-toplevel"],
            cwd=root,
            op="sdd.links.parent_scope",
            check=False,
            capture_output=True,
            text=True,
        )
        if toplevel.returncode != 0 or not toplevel.stdout.strip():
            return None
        status = run_sdd_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            op="sdd.links.parent_scope",
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001 - scoping falls back to strict validation.
        return None
    if status.returncode != 0:
        return None

    repo_root = Path(toplevel.stdout.strip())
    return frozenset(
        (repo_root / relative).resolve(strict=False)
        for relative in _porcelain_paths(status.stdout)
    )


def _porcelain_paths(status_output: str) -> list[str]:
    """Return every path named by ``status --porcelain=v1 -z`` output.

    Rename and copy entries emit their original path as a bare follow-on
    record; both halves count as owned, which errs toward strict validation.
    """

    paths: list[str] = []
    for record in status_output.split("\0"):
        if not record:
            continue
        if len(record) > 3 and record[2] == " ":
            paths.append(record[3:])
        else:
            paths.append(record)
    return paths


__all__ = [
    "LocalPlanChanges",
    "parent_section_issue",
]
