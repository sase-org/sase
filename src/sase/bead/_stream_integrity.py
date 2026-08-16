"""Append-only guards for version-controlled bead event streams.

A bead event stream may grow and may gain a relocated sibling stream, but a
commit or push must never drop or rewrite events that a committed or remote
ancestor already published. The later semantic merger still rejects a
non-append-only remote; these helpers stop that corruption from being
written in the first place and name it when history already contains it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Literal

from sase.sdd._git import run_sdd_git

_logger = logging.getLogger(__name__)

_STREAM_DIR_PARTS = ("events", "streams")
_HISTORY_COMMIT_LIMIT = 300
_UPSTREAM_REVS = ("@{upstream}", "origin/HEAD", "origin/main", "origin/master")


class BeadStreamIntegrityError(RuntimeError):
    """A bead event stream would shrink or rewrite ancestor history."""


@dataclass(frozen=True, slots=True)
class StreamIntegrityResult:
    """Outcome of preparing changed stream files for a commit."""

    restored_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _StreamAnalysis:
    """How one local stream compares to one ancestor version."""

    kind: Literal["ok", "restore_exact", "restore_superset", "rewrite"]
    first_event: int | None = None
    last_event: int | None = None
    restored_events: tuple[dict[str, Any], ...] | None = None
    restored_text: str | None = None


def is_event_stream_relpath(path: str) -> bool:
    """Return whether *path* is a canonical ``events/streams/*.jsonl`` file."""
    parts = Path(path).parts
    if len(parts) < 3 or not parts[-1].endswith(".jsonl"):
        return False
    return parts[-3:-1] == _STREAM_DIR_PARTS


def prepare_event_streams_for_commit(
    repo_root: Path,
    changed_files: list[str],
    *,
    ancestor_rev: str = "HEAD",
) -> StreamIntegrityResult:
    """Restore recoverable shrinks; raise on a prefix rewrite.

    Local files that are a valid superset of *ancestor_rev* are left alone.
    A pure shrink, or extras that can be replayed on top of the ancestor,
    is rewritten to that valid superset. A rewritten ancestor event restores
    the ancestor bytes and raises :class:`BeadStreamIntegrityError` so the
    caller does not publish corruption.
    """
    stream_paths = [path for path in changed_files if is_event_stream_relpath(path)]
    if not stream_paths:
        return StreamIntegrityResult()

    worktree_streams = _worktree_streams(repo_root, stream_paths)
    new_stream_ids = {
        Path(path).stem
        for path in stream_paths
        if _show_text(repo_root, ancestor_rev, path) is None
    }
    errors: list[str] = []
    restored_exact: list[str] = []
    for path in stream_paths:
        ancestor_text = _show_text(repo_root, ancestor_rev, path)
        if ancestor_text is None:
            continue
        try:
            ancestor_events = parse_stream_text(ancestor_text)
        except json.JSONDecodeError:
            continue
        if not (repo_root / path).is_file():
            # Removing the file is a store-level mutation (bead rm), not a
            # truncated append-only stream.
            continue
        try:
            local_events = _read_worktree_events(repo_root, path)
        except json.JSONDecodeError:
            _write_stream_text(repo_root, path, ancestor_text)
            errors.append(
                f"cannot publish unreadable bead event stream {Path(path).stem}"
            )
            continue
        analysis = analyze_stream_against_ancestor(
            ancestor_events,
            local_events,
            ancestor_text=ancestor_text,
            other_streams=worktree_streams,
            new_stream_ids=new_stream_ids,
            stream_id=Path(path).stem,
        )
        if analysis.kind == "ok":
            continue
        if analysis.kind == "rewrite":
            _write_stream_text(repo_root, path, ancestor_text)
            errors.append(_rewrite_message(Path(path).stem, analysis.first_event))
            continue
        if analysis.kind == "restore_exact":
            _write_stream_text(repo_root, path, ancestor_text)
            restored_exact.append(path)
            _logger.warning(
                "Restored bead event stream %s; worktree was missing ancestor "
                "events %s-%s",
                Path(path).stem,
                analysis.first_event,
                analysis.last_event,
            )
            continue
        if analysis.restored_text is not None:
            _write_stream_text(repo_root, path, analysis.restored_text)
            worktree_streams[Path(path).stem] = list(analysis.restored_events or ())
            _logger.warning(
                "Restored bead event stream %s to the valid local superset; "
                "worktree was missing ancestor events %s-%s",
                Path(path).stem,
                analysis.first_event,
                analysis.last_event,
            )

    if errors:
        raise BeadStreamIntegrityError("; ".join(errors))
    return StreamIntegrityResult(restored_paths=tuple(restored_exact))


def refuse_unpublished_event_stream_shrink(
    repo_root: Path,
    beads_dir: Path,
    *,
    ignore_unreadable: bool = False,
) -> None:
    """Refuse to push a HEAD that shrank a stream relative to its ancestor.

    Only unpublished local commits are inspected. A clone that is merely
    behind its upstream still needs to fetch and rebase, so missing remote
    extras are not treated as a local shrink.
    """
    upstream = _resolve_upstream_rev(repo_root)
    if upstream is None:
        return
    merge_base = _merge_base(repo_root, "HEAD", upstream)
    if merge_base is None:
        return
    ancestor = upstream if _is_ancestor(repo_root, upstream, "HEAD") else merge_base
    stream_dir = _stream_dir_relpath(repo_root, beads_dir)
    changed = _diff_names(repo_root, merge_base, "HEAD", f"{stream_dir}/")
    if changed is None:
        return
    stream_paths = [path for path in changed if is_event_stream_relpath(path)]
    if not stream_paths:
        return

    head_streams = _streams_at_rev(repo_root, "HEAD", stream_dir)
    ancestor_streams = _streams_at_rev(repo_root, ancestor, stream_dir)
    new_stream_ids = set(head_streams) - set(ancestor_streams)
    errors: list[str] = []
    for path in stream_paths:
        stream_id = Path(path).stem
        ancestor_text = _show_text(repo_root, ancestor, path)
        if ancestor_text is None:
            continue
        try:
            ancestor_events = parse_stream_text(ancestor_text)
        except json.JSONDecodeError:
            continue
        head_text = _show_text(repo_root, "HEAD", path)
        if head_text is None:
            continue
        try:
            head_events = parse_stream_text(head_text)
        except json.JSONDecodeError:
            if ignore_unreadable:
                continue
            errors.append(f"cannot publish unreadable bead event stream {stream_id}")
            continue
        analysis = analyze_stream_against_ancestor(
            ancestor_events,
            head_events,
            ancestor_text=ancestor_text,
            other_streams=head_streams,
            new_stream_ids=new_stream_ids,
            stream_id=stream_id,
        )
        if analysis.kind == "ok":
            continue
        if analysis.kind == "rewrite":
            errors.append(_rewrite_message(stream_id, analysis.first_event))
            continue
        errors.append(
            _missing_message(
                stream_id,
                analysis.first_event,
                analysis.last_event,
            )
        )
    if errors:
        raise BeadStreamIntegrityError("; ".join(errors))


def diagnose_event_stream_history(
    repo_root: Path,
    beads_dir: Path,
) -> list[str]:
    """Report committed shrinks or rewrites visible from this clone.

    Read-only: missing remotes, shallow history, and failed git probes are
    omitted rather than treated as a clean store.
    """
    stream_dir = _stream_dir_relpath(repo_root, beads_dir)
    try:
        records = _stream_history_records(repo_root, stream_dir)
    except Exception:
        return []
    if not records:
        return []

    messages: list[str] = []
    seen_streams: set[str] = set()
    for record in records:
        path = record.path
        stream_id = Path(path).stem
        if stream_id in seen_streams:
            continue
        parent_text = _show_text(repo_root, record.parent, path)
        commit_text = _show_text(repo_root, record.sha, path)
        if parent_text is None or commit_text is None:
            continue
        try:
            parent_events = parse_stream_text(parent_text)
            commit_events = (
                [] if commit_text is None else parse_stream_text(commit_text)
            )
        except json.JSONDecodeError:
            continue
        commit_streams = _streams_at_rev(repo_root, record.sha, stream_dir)
        parent_streams = _streams_at_rev(repo_root, record.parent, stream_dir)
        analysis = analyze_stream_against_ancestor(
            parent_events,
            commit_events,
            ancestor_text=parent_text,
            other_streams=commit_streams,
            new_stream_ids=set(commit_streams) - set(parent_streams),
            stream_id=stream_id,
        )
        if analysis.kind == "ok":
            continue
        seen_streams.add(stream_id)
        if analysis.kind == "rewrite":
            messages.append(
                _rewrite_history_message(
                    stream_id,
                    analysis.first_event,
                    record.sha,
                    record.subject,
                )
            )
            continue
        messages.append(
            _missing_history_message(
                stream_id,
                analysis.first_event,
                analysis.last_event,
                record.parent,
                record.sha,
                record.subject,
            )
        )
    return messages


def parse_stream_text(text: str) -> list[dict[str, Any]]:
    """Parse one JSONL event stream into objects."""
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(payload)
    return events


def encode_stream_events(events: list[dict[str, Any]]) -> str:
    """Encode events the way the Rust store writer emits JSONL."""
    return "".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        for event in events
    )


def analyze_stream_against_ancestor(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
    *,
    ancestor_text: str,
    other_streams: dict[str, list[dict[str, Any]]],
    new_stream_ids: set[str],
    stream_id: str,
) -> _StreamAnalysis:
    """Compare *local* to *ancestor* using the Rust append-only rules."""
    rewritten = _first_rewritten_event(ancestor, local)
    if rewritten is not None:
        return _StreamAnalysis(kind="rewrite", first_event=rewritten)

    missing_indexes, extras = _missing_and_extras(ancestor, local)
    if not missing_indexes:
        return _StreamAnalysis(kind="ok")

    missing_events = [ancestor[index] for index in missing_indexes]
    if _relocated_missing_events(
        missing_events,
        other_streams,
        new_stream_ids,
        stream_id,
    ):
        return _StreamAnalysis(kind="ok")

    first_event = missing_indexes[0] + 1
    last_event = missing_indexes[-1] + 1
    if not extras:
        return _StreamAnalysis(
            kind="restore_exact",
            first_event=first_event,
            last_event=last_event,
            restored_events=tuple(ancestor),
            restored_text=ancestor_text,
        )
    restored = list(ancestor)
    restored.extend(extras)
    suffix = encode_stream_events(extras)
    prefix = ancestor_text if ancestor_text.endswith("\n") else ancestor_text + "\n"
    return _StreamAnalysis(
        kind="restore_superset",
        first_event=first_event,
        last_event=last_event,
        restored_events=tuple(restored),
        restored_text=prefix + suffix if ancestor_text else suffix,
    )


def _first_rewritten_event(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> int | None:
    local_by_id = {
        event_id: event for event in local if (event_id := _event_id(event)) is not None
    }
    for index, event in enumerate(ancestor):
        event_id = _event_id(event)
        if event_id is None:
            continue
        counterpart = local_by_id.get(event_id)
        if counterpart is not None and counterpart != event:
            return index + 1
    return None


def _missing_and_extras(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    matched: set[int] = set()
    local_start = 0
    missing: list[int] = []
    for index, ancestor_event in enumerate(ancestor):
        found: int | None = None
        for offset, local_event in enumerate(local[local_start:]):
            if local_event == ancestor_event:
                found = local_start + offset
                break
        if found is None:
            missing.append(index)
            continue
        matched.add(found)
        local_start = found + 1
    extras = [event for offset, event in enumerate(local) if offset not in matched]
    return missing, extras


def _relocated_missing_events(
    missing_events: list[dict[str, Any]],
    other_streams: dict[str, list[dict[str, Any]]],
    new_stream_ids: set[str],
    stream_id: str,
) -> bool:
    if not missing_events or not new_stream_ids:
        return False
    fingerprints: set[tuple[object, ...]] = set()
    event_ids: set[str] = set()
    for candidate_id in new_stream_ids:
        if candidate_id == stream_id:
            continue
        for event in other_streams.get(candidate_id, ()):
            fingerprints.add(_event_fingerprint(event))
            event_id = _event_id(event)
            if event_id is not None:
                event_ids.add(event_id)
    return all(
        _event_id(event) in event_ids or _event_fingerprint(event) in fingerprints
        for event in missing_events
    )


def _event_id(event: dict[str, Any]) -> str | None:
    raw = event.get("event_id")
    return raw if isinstance(raw, str) and raw else None


def _event_fingerprint(event: dict[str, Any]) -> tuple[object, ...]:
    return (
        event.get("timestamp"),
        event.get("actor"),
        event.get("operation"),
    )


def _worktree_streams(
    repo_root: Path,
    stream_paths: list[str],
) -> dict[str, list[dict[str, Any]]]:
    streams: dict[str, list[dict[str, Any]]] = {}
    seen_dirs: set[Path] = set()
    for path in stream_paths:
        stream_dir = (repo_root / path).parent
        if stream_dir in seen_dirs or not stream_dir.is_dir():
            continue
        seen_dirs.add(stream_dir)
        for candidate in sorted(stream_dir.glob("*.jsonl")):
            try:
                streams[candidate.stem] = parse_stream_text(
                    candidate.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
    return streams


def _read_worktree_events(repo_root: Path, relpath: str) -> list[dict[str, Any]]:
    path = repo_root / relpath
    if not path.is_file():
        return []
    return parse_stream_text(path.read_text(encoding="utf-8"))


def _write_stream_text(repo_root: Path, relpath: str, text: str) -> None:
    path = repo_root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _show_text(repo_root: Path, rev: str, relpath: str) -> str | None:
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


def _merge_base(repo_root: Path, left: str, right: str) -> str | None:
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


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    result = run_sdd_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.stream.is_ancestor",
    )
    return result.returncode == 0


def _resolve_upstream_rev(repo_root: Path) -> str | None:
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


def _diff_names(
    repo_root: Path,
    left: str,
    right: str,
    pathspec: str,
) -> list[str] | None:
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


def _streams_at_rev(
    repo_root: Path,
    rev: str,
    stream_dir: str,
) -> dict[str, list[dict[str, Any]]]:
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
    streams: dict[str, list[dict[str, Any]]] = {}
    for relpath in result.stdout.splitlines():
        path = relpath.strip()
        if not path or not is_event_stream_relpath(path):
            continue
        text = _show_text(repo_root, rev, path)
        if text is None:
            continue
        try:
            streams[Path(path).stem] = parse_stream_text(text)
        except json.JSONDecodeError:
            continue
    return streams


def _stream_dir_relpath(repo_root: Path, beads_dir: Path) -> str:
    try:
        relative = beads_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return "/".join(_STREAM_DIR_PARTS)
    if relative in {".", ""}:
        return "/".join(_STREAM_DIR_PARTS)
    return f"{relative}/{'/'.join(_STREAM_DIR_PARTS)}"


@dataclass(frozen=True, slots=True)
class _HistoryRecord:
    sha: str
    parent: str
    subject: str
    path: str


def _stream_history_records(
    repo_root: Path,
    stream_dir: str,
) -> list[_HistoryRecord]:
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


def _rewrite_message(stream_id: str, event_number: int | None) -> str:
    number = event_number if event_number is not None else 0
    return (
        "cannot publish non-append-only bead event stream "
        f"{stream_id}: worktree rewrote ancestor event {number}"
    )


def _missing_message(
    stream_id: str,
    first_event: int | None,
    last_event: int | None,
) -> str:
    first = first_event if first_event is not None else 0
    last = last_event if last_event is not None else first
    return (
        "cannot publish non-append-only bead event stream "
        f"{stream_id}: HEAD missing ancestor events {first}-{last}"
    )


def _rewrite_history_message(
    stream_id: str,
    event_number: int | None,
    sha: str,
    subject: str,
) -> str:
    number = event_number if event_number is not None else 0
    return (
        f"ERROR: bead event stream {stream_id} rewrote event {number}; "
        f"first offending commit {_short_sha(sha)} ({_subject(subject)})"
    )


def _missing_history_message(
    stream_id: str,
    first_event: int | None,
    last_event: int | None,
    ancestor_sha: str,
    sha: str,
    subject: str,
) -> str:
    first = first_event if first_event is not None else 0
    last = last_event if last_event is not None else first
    return (
        f"ERROR: bead event stream {stream_id} is shorter than its own "
        f"history: missing events {first}-{last} present in ancestor "
        f"{_short_sha(ancestor_sha)}; first offending commit "
        f"{_short_sha(sha)} ({_subject(subject)})"
    )


def _is_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _short_sha(sha: str) -> str:
    return sha[:12] if len(sha) > 12 else sha


def _subject(subject: str) -> str:
    text = subject.strip() or "unknown subject"
    if len(text) > 80:
        return text[:77] + "..."
    return text


__all__ = [
    "BeadStreamIntegrityError",
    "StreamIntegrityResult",
    "analyze_stream_against_ancestor",
    "diagnose_event_stream_history",
    "encode_stream_events",
    "is_event_stream_relpath",
    "parse_stream_text",
    "prepare_event_streams_for_commit",
    "refuse_unpublished_event_stream_shrink",
]
