"""Read-only git probes used by the bead event-stream integrity guards.

Every probe here tolerates failure: a missing revision, a missing remote,
or a git error yields ``None`` or an empty result so the guards degrade to
"nothing to check" rather than reporting a clean or corrupt store on bad
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from sase.bead._stream_integrity_files import (
    is_event_stream_relpath,
    parse_stream_text,
)
from sase.sdd._git import (
    DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS,
    ENV_LOCAL_TIMEOUT,
    run_sdd_git,
    sdd_git_command,
)

_HISTORY_COMMIT_LIMIT = 300
_UPSTREAM_REVS = ("@{upstream}", "origin/HEAD", "origin/main", "origin/master")


@dataclass(frozen=True, slots=True)
class _HistoryRecord:
    """One commit that shrank a stream file, paired with its first parent."""

    sha: str
    parent: str
    subject: str
    path: str


def show_text(repo_root: Path, rev: str, relpath: str) -> str | None:
    """Return ``rev:relpath`` contents, or ``None`` when it does not exist."""
    result = run_sdd_git(
        ["show", f"{rev}:{relpath}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.show",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def merge_base(repo_root: Path, left: str, right: str) -> str | None:
    """Return the merge base of *left* and *right*, or ``None``."""
    result = run_sdd_git(
        ["merge-base", left, right],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.merge_base",
    )
    sha = result.stdout.strip()
    return sha or None if result.returncode == 0 else None


def is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    """Return whether *ancestor* is reachable from *descendant*."""
    result = run_sdd_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.is_ancestor",
    )
    return result.returncode == 0


def resolve_upstream_rev(repo_root: Path) -> str | None:
    """Return the first resolvable upstream revision, or ``None``."""
    for rev in _UPSTREAM_REVS:
        result = run_sdd_git(
            ["rev-parse", "--verify", rev],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            op="bead.stream.upstream",
        )
        if result.returncode == 0 and result.stdout.strip():
            return rev
    return None


def diff_names(
    repo_root: Path,
    left: str,
    right: str,
    pathspec: str,
) -> list[str] | None:
    """Return paths changed between *left* and *right*, or ``None`` on error."""
    result = run_sdd_git(
        ["diff", "--name-only", left, right, "--", pathspec],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.diff_names",
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def stream_paths_at_rev(
    repo_root: Path,
    rev: str,
    stream_dir: str,
) -> dict[str, str]:
    """Return ``{stream_id: relpath}`` for every stream under *stream_dir* at *rev*.

    Only the ``git ls-tree`` name list is read (one subprocess); no blob
    contents are fetched. Tolerates failure by returning an empty mapping.
    """
    result = run_sdd_git(
        ["ls-tree", "-r", "--name-only", rev, "--", f"{stream_dir}/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.ls_tree",
    )
    if result.returncode != 0:
        return {}
    paths: dict[str, str] = {}
    for relpath in result.stdout.splitlines():
        path = relpath.strip()
        if not path or not is_event_stream_relpath(path):
            continue
        paths[Path(path).stem] = path
    return paths


def batch_show_texts(
    repo_root: Path,
    rev: str,
    relpaths: list[str],
) -> dict[str, str | None]:
    """Return ``{relpath: text}`` for *relpaths* at *rev* in one subprocess.

    Blob reads go through a single ``git cat-file --batch`` process instead
    of one ``git show`` per path. Missing blobs map to ``None``. Any git or
    parsing failure maps every requested path to ``None`` so callers degrade
    to "nothing to check".
    """
    unique = list(dict.fromkeys(relpaths))
    if not unique:
        return {}
    specs = [f"{rev}:{path}" for path in unique]
    try:
        cmd = sdd_git_command(["cat-file", "--batch"])
        proc = subprocess.Popen(
            cmd,
            cwd=repo_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, _stderr = proc.communicate(
                "".join(f"{spec}\n" for spec in specs).encode(),
                timeout=_batch_timeout(),
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        if proc.returncode != 0:
            return dict.fromkeys(unique)
        texts: dict[str, str | None] = {}
        pos = 0
        for path in unique:
            newline = stdout.find(b"\n", pos)
            if newline < 0:
                return dict.fromkeys(unique)
            header = stdout[pos:newline].decode("utf-8", errors="replace")
            pos = newline + 1
            if header.endswith(" missing"):
                texts[path] = None
                continue
            parts = header.split()
            if len(parts) != 3:
                return dict.fromkeys(unique)
            try:
                size = int(parts[2])
            except ValueError:
                return dict.fromkeys(unique)
            if size < 0 or pos + size > len(stdout):
                return dict.fromkeys(unique)
            try:
                texts[path] = stdout[pos : pos + size].decode("utf-8")
            except UnicodeDecodeError:
                texts[path] = None
            pos += size
            if stdout[pos : pos + 1] == b"\n":
                pos += 1
        return texts
    except Exception:
        return dict.fromkeys(unique)


def _batch_timeout() -> float:
    raw = os.environ.get(ENV_LOCAL_TIMEOUT)
    if raw is None:
        return DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS


def streams_at_rev(
    repo_root: Path,
    rev: str,
    stream_dir: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return every readable event stream under *stream_dir* at *rev*."""
    paths = stream_paths_at_rev(repo_root, rev, stream_dir)
    if not paths:
        return {}
    texts = batch_show_texts(repo_root, rev, list(paths.values()))
    streams: dict[str, list[dict[str, Any]]] = {}
    for stream_id, path in paths.items():
        text = texts.get(path)
        if text is None:
            continue
        try:
            streams[stream_id] = parse_stream_text(text)
        except json.JSONDecodeError:
            continue
    return streams


def stream_history_records(
    repo_root: Path,
    stream_dir: str,
) -> list[_HistoryRecord]:
    """Return oldest-first commits under *stream_dir* that deleted stream lines."""
    result = run_sdd_git(
        [
            "log",
            "--pretty=format:%H%x09%P%x09%s",
            "--numstat",
            f"--max-count={_HISTORY_COMMIT_LIMIT}",
            "HEAD",
            "--",
            f"{stream_dir}/",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.history",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    records: list[_HistoryRecord] = []
    current_sha = ""
    current_parent = ""
    current_subject = ""
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        sha, sep, rest = line.partition("\t")
        if sep and _is_commit_sha(sha):
            parents, _parent_sep, subject = rest.partition("\t")
            current_sha = sha
            current_parent = parents.split()[0] if parents.strip() else ""
            current_subject = subject
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not current_sha or not current_parent:
            continue
        added, deleted, path = parts
        if not is_event_stream_relpath(path):
            continue
        if deleted in {"0", "-"} and added != "-":
            continue
        records.append(
            _HistoryRecord(
                sha=current_sha,
                parent=current_parent,
                subject=current_subject,
                path=path,
            )
        )
    records.reverse()
    return records


def _is_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)
