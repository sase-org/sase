"""The change set the diff-scoped selector runs against.

Split out of :mod:`tests._test_selection` so neither half grows past the
repository's per-file line budget. This half knows only how to ask git what
moved; deciding what that implies for the suite lives next door.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests._test_selection_graph import SelectionError, run_git


@dataclass(frozen=True)
class ChangeSet:
    paths: tuple[str, ...]
    base_ref: str
    merge_base: str | None
    has_rename_or_delete: bool
    head: str | None
    tree_dirty: bool


def _parse_name_status_z(raw: str) -> tuple[list[str], bool]:
    """Parse ``git diff --name-status -z`` into paths and a rename/delete flag.

    With ``-z`` each status code is its own NUL-separated field, and a rename
    or copy is followed by *two* path fields (old, then new). Both are kept:
    the old path seeds nothing but the new one does, and callers only need to
    know that some path moved.
    """
    fields = raw.split("\0")
    paths: list[str] = []
    special = False
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            special = special or code == "R"
            for _ in range(2):
                if index < len(fields):
                    if fields[index]:
                        paths.append(fields[index])
                    index += 1
            continue
        if index < len(fields):
            if fields[index]:
                paths.append(fields[index])
            index += 1
        if code == "D":
            special = True
    return paths, special


def _parse_porcelain_z(raw: str) -> tuple[list[str], bool]:
    """Parse ``git status --porcelain -z`` into paths and a rename/delete flag.

    Each entry is ``XY<space><path>``; a rename or copy puts the original path
    in the following NUL-separated field. Untracked (``??``) entries are
    included so a brand-new test file participates in the change set.
    """
    fields = raw.split("\0")
    paths: list[str] = []
    special = False
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            if index < len(fields) and fields[index]:
                paths.append(fields[index])
            index += 1
            special = special or "R" in status
        if "D" in status:
            special = True
    return paths, special


def commit_change_set(root: Path, sha: str) -> ChangeSet:
    """The change set a single commit introduced, as its own diff against its parent.

    This is the historical analogue of :func:`compute_change_set`: no working
    tree, no merge base against a branch point, just "what did this commit
    change". ``tools/selection_backtest`` replays real commits through the
    selector with it. A root commit has no parent to diff against and raises,
    because a synthetic empty-tree diff would report the whole repository as
    changed and quietly turn one commit's recall into an escalation.
    """
    parent = run_git(root, "rev-parse", f"{sha}^").strip()
    paths, has_rename_or_delete = _parse_name_status_z(
        run_git(root, "diff", "--name-status", "-M", "-z", parent, sha)
    )
    return ChangeSet(
        paths=tuple(sorted(set(paths))),
        base_ref=parent,
        merge_base=parent,
        has_rename_or_delete=has_rename_or_delete,
        head=sha,
        tree_dirty=False,
    )


def compute_change_set(root: Path, base_ref: str) -> ChangeSet:
    """Union the merge-base diff with the working tree's own changes.

    A stale or missing base ref is not an error the selector may paper over:
    the caller sees ``merge_base is None`` and escalates to the full suite,
    because failing toward *more* testing is the only safe direction.
    """
    try:
        merge_base = run_git(root, "merge-base", "HEAD", base_ref).strip() or None
    except SelectionError:
        merge_base = None
    try:
        head = run_git(root, "rev-parse", "HEAD").strip() or None
    except SelectionError:
        head = None

    paths: list[str] = []
    has_rename_or_delete = False
    if merge_base is not None:
        diff_paths, diff_special = _parse_name_status_z(
            run_git(root, "diff", "--name-status", "-M", "-z", merge_base)
        )
        paths.extend(diff_paths)
        has_rename_or_delete = has_rename_or_delete or diff_special

    status_paths, status_special = _parse_porcelain_z(
        run_git(root, "status", "--porcelain", "-z")
    )
    paths.extend(status_paths)
    has_rename_or_delete = has_rename_or_delete or status_special

    return ChangeSet(
        paths=tuple(sorted(set(paths))),
        base_ref=base_ref,
        merge_base=merge_base,
        has_rename_or_delete=has_rename_or_delete,
        head=head,
        tree_dirty=bool(status_paths),
    )
