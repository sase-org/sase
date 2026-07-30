"""Pure logic for the recursive fuzzy file finder (Ctrl+R).

This module mirrors the single-level ``file_completion`` engine: it is pure
presentation/glue that performs filesystem I/O but holds no Textual state.  It
provides three building blocks for the :class:`RecursiveFileFinderModal`:

* :func:`enumerate_recursive_candidates` -- git-aware recursive enumeration of
  files (and their intermediate directories) under a root.
* :func:`_fuzzy_match` / :func:`_rank_candidates` -- shared Rust fuzzy matching
  with quality ranking and matched-run output for highlighting.
* :class:`FinderModel` -- the thin, unit-testable finder state (candidates +
  query + filtered view + selection index) the modal renders.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.core.fuzzy_facade import FuzzyMatch, fuzzy_match, fuzzy_sort_key

# ── Enumeration constants ─────────────────────────────────────────────

MAX_RESULTS = 20000
"""Safety cap on enumerated entries (files + derived dirs) before truncation."""

GIT_TIMEOUT_SECONDS = 5.0
"""How long to wait for ``git ls-files`` before falling back to a walk."""

IGNORE_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "__pycache__",
        "target",
        ".venv",
        "venv",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".next",
        ".cache",
        ".idea",
    }
)
"""Heavy/uninteresting directories skipped by the non-git filesystem walk."""


def _fuzzy_match(query: str, text: str) -> FuzzyMatch | None:
    """Fuzzy-match *query* against *text* with the shared core matcher."""
    return fuzzy_match(query, text)


def _rank_candidates(
    query: str,
    candidates: list[CompletionCandidate],
) -> list[tuple[CompletionCandidate, FuzzyMatch]]:
    """Filter and rank *candidates* against *query*.

    With a non-empty query, only matching candidates are returned, sorted with
    the shared fuzzy ordering: tier, descending score, shorter display path,
    then case-insensitive path. With an empty query, every candidate is
    returned in a shallow-and-short-first default order.
    """
    if not query:
        ordered = sorted(
            candidates,
            key=lambda c: (c.display.count("/"), len(c.display), c.display.lower()),
        )
        empty = FuzzyMatch(tier=0, score=0, runs=())
        return [(c, empty) for c in ordered]

    scored: list[tuple[CompletionCandidate, FuzzyMatch]] = []
    for candidate in candidates:
        match = _fuzzy_match(query, candidate.display)
        if match is not None:
            scored.append((candidate, match))
    scored.sort(key=lambda cm: fuzzy_sort_key(cm[1], cm[0].display))
    return scored


# ── Candidate enumeration ─────────────────────────────────────────────


def _git_list_files(root_abs: str) -> list[str] | None:
    """List tracked + untracked-not-ignored files relative to *root_abs*.

    Returns ``None`` when *root_abs* is not inside a git work tree (or git is
    unavailable), signalling the caller to fall back to a filesystem walk.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root_abs,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [
        chunk.decode("utf-8", "replace")
        for chunk in result.stdout.split(b"\0")
        if chunk
    ]


def _walk_list_files(root_abs: str) -> list[str]:
    """Walk *root_abs*, skipping dotdirs and heavy dirs; return rel posix paths."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in IGNORE_DIRS
        ]
        rel_dir = os.path.relpath(dirpath, root_abs)
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            files.append(rel.replace(os.sep, "/"))
        if len(files) > MAX_RESULTS:
            break
    return files


def _build_candidates(
    files: list[str],
    root_display: str,
) -> list[CompletionCandidate]:
    """Turn relative file paths into file + derived-directory candidates.

    Both ``display`` and ``insertion`` are ``root_display`` + the relative path
    (with a trailing ``/`` for directories) so the finder shows exactly the
    text that will be inserted into the prompt.
    """
    seen_dirs: set[str] = set()
    file_candidates: list[CompletionCandidate] = []
    dir_candidates: list[CompletionCandidate] = []

    for rel in files:
        rel = rel.strip("/")
        if not rel:
            continue
        full = f"{root_display}{rel}"
        file_candidates.append(
            CompletionCandidate(
                display=full,
                insertion=full,
                is_dir=False,
                name=rel.rsplit("/", 1)[-1],
            )
        )
        # Derive every intermediate directory prefix from the file path.
        parts = rel.split("/")
        for depth in range(1, len(parts)):
            dir_rel = "/".join(parts[:depth])
            if dir_rel in seen_dirs:
                continue
            seen_dirs.add(dir_rel)
            dir_full = f"{root_display}{dir_rel}/"
            dir_candidates.append(
                CompletionCandidate(
                    display=dir_full,
                    insertion=dir_full,
                    is_dir=True,
                    name=parts[depth - 1],
                )
            )

    return dir_candidates + file_candidates


def enumerate_recursive_candidates(
    root_abs: str,
    root_display: str,
) -> tuple[list[CompletionCandidate], bool]:
    """Enumerate selectable files and directories under *root_abs*.

    Git-aware: inside a git repo this respects ``.gitignore`` (tracked +
    untracked-not-ignored).  Outside git it walks the filesystem, skipping
    dotdirs and heavy directories.  Directories are derived from the file
    paths, so an ignored directory never appears.

    *root_display* is the insertion prefix (e.g. ``"src/"`` or ``""`` for the
    current working directory) prepended to each relative path.

    Returns ``(candidates, truncated)`` where *truncated* is ``True`` when the
    enumeration hit :data:`MAX_RESULTS` and the result list is incomplete.
    """
    git_files = _git_list_files(root_abs)
    files = git_files if git_files is not None else _walk_list_files(root_abs)

    truncated = len(files) > MAX_RESULTS
    if truncated:
        files = files[:MAX_RESULTS]

    return _build_candidates(files, root_display), truncated


# ── Root / token-range resolution ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RecursiveFinderContext:
    """Where Ctrl+R should search and which prompt range it replaces.

    ``root_display`` is the insertion prefix prepended to chosen paths (e.g.
    ``"src/"`` or ``""`` for the working directory); ``root_abs`` is the
    filesystem directory to enumerate; ``(row, start, end)`` is the prompt
    token range replaced on accept; ``query`` pre-seeds the fuzzy filter.
    """

    root_display: str
    root_abs: str
    row: int
    start: int
    end: int
    query: str


def derive_root_from_path(path: str, is_dir: bool) -> str:
    """Return the insertion-prefix root "to the left of" *path*.

    A directory entry becomes the root itself (with a trailing slash); a file
    entry becomes its parent directory (``""`` when it has no parent).  A
    leading ``@`` file-reference marker is preserved.
    """
    prefix = ""
    if path.startswith("@"):
        prefix, path = "@", path[1:]
    if is_dir:
        root = path if path.endswith("/") else f"{path}/"
    elif "/" in path:
        root = path[: path.rindex("/") + 1]
    else:
        root = ""
    return f"{prefix}{root}"


def split_root_and_query(token: str) -> tuple[str, str]:
    """Split a path *token* into ``(root_display_prefix, partial_query)``.

    ``"src/foo"`` -> ``("src/", "foo")``; ``"foo"`` -> ``("", "foo")``.  A
    leading ``@`` file-reference marker is preserved on the root prefix.
    """
    prefix = ""
    if token.startswith("@"):
        prefix, token = "@", token[1:]
    if "/" in token:
        cut = token.rindex("/") + 1
        return f"{prefix}{token[:cut]}", token[cut:]
    return prefix, token


def resolve_root_abs(
    root_display: str,
    *,
    base_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve an insertion-prefix root to an absolute filesystem directory."""
    path = root_display[1:] if root_display.startswith("@") else root_display
    if not path:
        return (
            os.path.abspath(os.fspath(base_dir))
            if base_dir is not None
            else os.getcwd()
        )
    expanded = os.path.expandvars(os.path.expanduser(path))
    if base_dir is not None and not os.path.isabs(expanded):
        expanded = os.path.join(os.fspath(base_dir), expanded)
    return os.path.abspath(expanded)


# ── Finder state ──────────────────────────────────────────────────────


@dataclass
class FinderModel:
    """Thin, unit-testable finder state backing the modal view.

    Holds the enumerated candidates, the transient fuzzy query, the ranked
    filtered view, and the selection index.  Mutating the query or moving the
    selection keeps the index in range.
    """

    candidates: list[CompletionCandidate]
    query: str = ""
    matches: list[tuple[CompletionCandidate, FuzzyMatch]] = field(default_factory=list)
    index: int = 0

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.matches = _rank_candidates(self.query, self.candidates)
        if self.index >= len(self.matches):
            self.index = max(0, len(self.matches) - 1)

    def set_query(self, query: str) -> None:
        """Replace the fuzzy query, re-rank, and reset the selection to the top."""
        self.query = query
        self.index = 0
        self._recompute()

    def move(self, delta: int) -> None:
        """Move the selection by *delta*, wrapping around the filtered view."""
        if not self.matches:
            return
        self.index = (self.index + delta) % len(self.matches)

    @property
    def total(self) -> int:
        """Number of candidates before filtering."""
        return len(self.candidates)

    @property
    def match_count(self) -> int:
        """Number of candidates passing the current query."""
        return len(self.matches)

    @property
    def selected(self) -> CompletionCandidate | None:
        """The currently highlighted candidate, or ``None`` when empty."""
        if not self.matches:
            return None
        return self.matches[self.index][0]
