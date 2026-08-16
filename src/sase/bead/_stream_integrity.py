"""Append-only guards for version-controlled bead event streams.

A bead event stream may grow and may gain a relocated sibling stream, but a
commit or push must never drop or rewrite events that a committed or remote
ancestor already published. The later semantic merger still rejects a
non-append-only remote; these helpers stop that corruption from being
written in the first place and name it when history already contains it.

The guards live here; their parts live beside them --
:mod:`sase.bead._stream_integrity_files` for path predicates and JSONL IO,
:mod:`sase.bead._stream_integrity_analysis` for the append-only comparison,
:mod:`sase.bead._stream_integrity_git` for read-only git probes, and
:mod:`sase.bead._stream_integrity_messages` for operator-facing wording.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path

from sase.bead._stream_integrity_analysis import analyze_stream_against_ancestor
from sase.bead._stream_integrity_files import (
    is_event_stream_relpath,
    parse_stream_text,
    read_worktree_events,
    stream_dir_relpath,
    worktree_streams,
    write_stream_text,
)
from sase.bead._stream_integrity_git import (
    diff_names,
    is_ancestor,
    merge_base,
    resolve_upstream_rev,
    show_text,
    stream_history_records,
    streams_at_rev,
)
from sase.bead._stream_integrity_messages import (
    missing_history_message,
    missing_message,
    rewrite_history_message,
    rewrite_message,
)

_logger = logging.getLogger(__name__)


class BeadStreamIntegrityError(RuntimeError):
    """A bead event stream would shrink or rewrite ancestor history."""


@dataclass(frozen=True, slots=True)
class _StreamIntegrityResult:
    """Outcome of preparing changed stream files for a commit."""

    restored_paths: tuple[str, ...] = ()


def prepare_event_streams_for_commit(
    repo_root: Path,
    changed_files: list[str],
    *,
    ancestor_rev: str = "HEAD",
) -> _StreamIntegrityResult:
    """Restore recoverable shrinks; raise on a prefix rewrite.

    Local files that are a valid superset of *ancestor_rev* are left alone.
    A pure shrink, or extras that can be replayed on top of the ancestor,
    is rewritten to that valid superset. A rewritten ancestor event restores
    the ancestor bytes and raises :class:`BeadStreamIntegrityError` so the
    caller does not publish corruption.
    """
    stream_paths = [path for path in changed_files if is_event_stream_relpath(path)]
    if not stream_paths:
        return _StreamIntegrityResult()

    local_streams = worktree_streams(repo_root, stream_paths)
    new_stream_ids = {
        Path(path).stem
        for path in stream_paths
        if show_text(repo_root, ancestor_rev, path) is None
    }
    errors: list[str] = []
    restored_exact: list[str] = []
    for path in stream_paths:
        ancestor_text = show_text(repo_root, ancestor_rev, path)
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
            local_events = read_worktree_events(repo_root, path)
        except json.JSONDecodeError:
            write_stream_text(repo_root, path, ancestor_text)
            errors.append(
                f"cannot publish unreadable bead event stream {Path(path).stem}"
            )
            continue
        analysis = analyze_stream_against_ancestor(
            ancestor_events,
            local_events,
            ancestor_text=ancestor_text,
            other_streams=local_streams,
            new_stream_ids=new_stream_ids,
            stream_id=Path(path).stem,
        )
        if analysis.kind == "ok":
            continue
        if analysis.kind == "rewrite":
            write_stream_text(repo_root, path, ancestor_text)
            errors.append(
                rewrite_message(
                    Path(path).stem,
                    analysis.first_event,
                    analysis.rewrite_diagnosis,
                )
            )
            continue
        if analysis.kind == "restore_exact":
            write_stream_text(repo_root, path, ancestor_text)
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
            write_stream_text(repo_root, path, analysis.restored_text)
            local_streams[Path(path).stem] = list(analysis.restored_events or ())
            _logger.warning(
                "Restored bead event stream %s to the valid local superset; "
                "worktree was missing ancestor events %s-%s",
                Path(path).stem,
                analysis.first_event,
                analysis.last_event,
            )

    if errors:
        raise BeadStreamIntegrityError("; ".join(errors))
    return _StreamIntegrityResult(restored_paths=tuple(restored_exact))


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
    upstream = resolve_upstream_rev(repo_root)
    if upstream is None:
        return
    base = merge_base(repo_root, "HEAD", upstream)
    if base is None:
        return
    ancestor = upstream if is_ancestor(repo_root, upstream, "HEAD") else base
    stream_dir = stream_dir_relpath(repo_root, beads_dir)
    changed = diff_names(repo_root, base, "HEAD", f"{stream_dir}/")
    if changed is None:
        return
    stream_paths = [path for path in changed if is_event_stream_relpath(path)]
    if not stream_paths:
        return

    head_streams = streams_at_rev(repo_root, "HEAD", stream_dir)
    ancestor_streams = streams_at_rev(repo_root, ancestor, stream_dir)
    new_stream_ids = set(head_streams) - set(ancestor_streams)
    errors: list[str] = []
    for path in stream_paths:
        stream_id = Path(path).stem
        ancestor_text = show_text(repo_root, ancestor, path)
        if ancestor_text is None:
            continue
        try:
            ancestor_events = parse_stream_text(ancestor_text)
        except json.JSONDecodeError:
            continue
        head_text = show_text(repo_root, "HEAD", path)
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
            errors.append(
                rewrite_message(
                    stream_id,
                    analysis.first_event,
                    analysis.rewrite_diagnosis,
                )
            )
            continue
        errors.append(
            missing_message(
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
    stream_dir = stream_dir_relpath(repo_root, beads_dir)
    try:
        records = stream_history_records(repo_root, stream_dir)
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
        parent_text = show_text(repo_root, record.parent, path)
        commit_text = show_text(repo_root, record.sha, path)
        if parent_text is None or commit_text is None:
            continue
        try:
            parent_events = parse_stream_text(parent_text)
            commit_events = (
                [] if commit_text is None else parse_stream_text(commit_text)
            )
        except json.JSONDecodeError:
            continue
        commit_streams = streams_at_rev(repo_root, record.sha, stream_dir)
        parent_streams = streams_at_rev(repo_root, record.parent, stream_dir)
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
                rewrite_history_message(
                    stream_id,
                    analysis.first_event,
                    record.sha,
                    record.subject,
                )
            )
            continue
        messages.append(
            missing_history_message(
                stream_id,
                analysis.first_event,
                analysis.last_event,
                record.parent,
                record.sha,
                record.subject,
            )
        )
    return messages


__all__ = [
    "BeadStreamIntegrityError",
    "diagnose_event_stream_history",
    "prepare_event_streams_for_commit",
    "refuse_unpublished_event_stream_shrink",
]
