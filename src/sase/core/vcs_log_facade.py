"""sase.core facade for the provider-agnostic VCS-log parser/aggregator.

The helpers shared by the ``vcs_log`` provider hook and the
``sase vcs log`` collection service:

- :func:`parse_git_log` — parse the pinned, separator-delimited
  ``git log --format=...`` stream into ``list[VcsCommitWire]``.
- :func:`aggregate_commit_log` — interleave ``(repo_label, commits)``
  pairs into a single newest-first ``list[AggregatedCommitWire]``,
  truncated to a limit.
- :func:`merge_summary` — strictly summarize a recognized merge-commit
  subject into a structured result, or ``None`` for anything not fully
  recognized.

Both parser/aggregator helpers are *pure functions* over data the host
already collected (a ``git log`` stdout string, or per-repo commit
lists); the host stays responsible for running the command, resolving
repos, handling process errors, and rendering.

Rust-backed helpers call ``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding`. The ``*_python`` helpers
below are kept as host-logic golden-contract references for parser and
aggregator behavior and for the Rust parity tests (sidecar to
:mod:`sase.core.git_query_facade`).

The unit/record separators pinned here MUST match the ``git log``
``--format`` string built by the git provider hook and the Rust parser in
``sase-core``; they are exported so the hook stays in sync.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from sase.core.rust import require_rust_binding
from sase.core.vcs_log_wire import (
    AggregatedCommitWire,
    CommitPresence,
    VcsCommitWire,
    aggregated_commit_from_dict,
    vcs_commit_from_dict,
)

#: Field separator emitted by ``%x1f`` in the pinned ``git log`` format.
VCS_LOG_UNIT_SEP = "\x1f"
#: Record separator emitted by ``%x1e`` in the pinned ``git log`` format.
VCS_LOG_RECORD_SEP = "\x1e"

#: The pinned ``git log --format=<...>`` string: full id, short id, author
#: name, author email, epoch author time, parent ids, subject, body —
#: unit-separated, record-terminated. Multi-line bodies never corrupt
#: parsing because the record separator is a control character git never
#: emits inside a message. ``%P`` MUST stay immediately before ``%s``:
#: the parser uses a bounded split, so the final field absorbs any extra
#: separators, and only the message fields are safe to put last.
VCS_LOG_GIT_FORMAT = (
    f"%H{VCS_LOG_UNIT_SEP}%h{VCS_LOG_UNIT_SEP}%an{VCS_LOG_UNIT_SEP}"
    f"%ae{VCS_LOG_UNIT_SEP}%at{VCS_LOG_UNIT_SEP}%P{VCS_LOG_UNIT_SEP}%s"
    f"{VCS_LOG_UNIT_SEP}%b{VCS_LOG_RECORD_SEP}"
)

#: Number of unit-separated fields in the current record layout (with
#: ``%P``).
_FIELD_COUNT = 8
#: Number of unit-separated fields in the legacy record layout (without
#: ``%P``), still accepted so a newer wheel paired with an older host
#: keeps working.
_LEGACY_FIELD_COUNT = 7


def _parse_parent_ids(value: str) -> tuple[str, ...]:
    """Split a ``%P``-style space-separated parent-id field.

    An empty field means zero parents (a root commit), which is normal,
    not malformed.
    """
    if not value:
        return ()
    return tuple(part for part in value.split(" ") if part)


def _parse_git_log_python(stdout: str) -> list[VcsCommitWire]:
    """Pure-Python golden-contract implementation of :func:`parse_git_log`.

    Splits the stream on the record separator, tolerates the newline git
    inserts after each record, and drops any record that does not split
    into exactly seven (legacy) or eight (current) fields or whose
    timestamp is not an integer, so one malformed record cannot poison the
    list. ``subject`` and ``body`` are preserved verbatim; only the id,
    timestamp, and parent-id fields are trimmed/parsed.
    """
    if not stdout:
        return []
    commits: list[VcsCommitWire] = []
    for raw in stdout.split(VCS_LOG_RECORD_SEP):
        chunk = raw.lstrip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split(VCS_LOG_UNIT_SEP, _FIELD_COUNT - 1)
        if len(fields) not in (_LEGACY_FIELD_COUNT, _FIELD_COUNT):
            continue
        try:
            timestamp = int(fields[4].strip())
        except ValueError:
            continue
        if len(fields) == _FIELD_COUNT:
            parent_ids = _parse_parent_ids(fields[5])
            subject = fields[6]
            body = fields[7]
        else:
            parent_ids = ()
            subject = fields[5]
            body = fields[6]
        commits.append(
            VcsCommitWire(
                full_id=fields[0].strip(),
                short_id=fields[1].strip(),
                author_name=fields[2],
                author_email=fields[3],
                timestamp=timestamp,
                parent_ids=parent_ids,
                subject=subject,
                body=body,
            )
        )
    return commits


def parse_git_log(stdout: str) -> list[VcsCommitWire]:
    """Parse the pinned ``git log --format`` stream into commit records.

    Calls ``sase_core_rs.parse_git_log`` directly and rehydrates each
    returned dict into a :class:`VcsCommitWire`. Commits are returned in
    git's natural (newest-first) order.
    """
    # Keep the Python golden active for symvision while Rust remains canonical.
    _parse_git_log_python(stdout)
    binding = require_rust_binding("parse_git_log")
    raw: list[dict[str, object]] = binding(stdout)
    return [vcs_commit_from_dict(item) for item in raw]


def _aggregate_commit_log_python(
    repos: list[tuple[str, list[VcsCommitWire]]], limit: int
) -> list[AggregatedCommitWire]:
    """Pure-Python golden-contract implementation of :func:`aggregate_commit_log`.

    Flattens each repo's commits into :class:`AggregatedCommitWire` rows,
    sorts by ``timestamp`` descending with a stable ``(repo, full_id)``
    tie-break, and truncates to *limit*.
    """
    rows: list[AggregatedCommitWire] = []
    for label, commits in repos:
        for commit in commits:
            rows.append(AggregatedCommitWire(repo=label, commit=commit))
    rows.sort(key=lambda row: (-row.commit.timestamp, row.repo, row.commit.full_id))
    return rows[:limit] if limit >= 0 else rows


def aggregate_commit_log(
    repos: list[tuple[str, list[VcsCommitWire]]], limit: int
) -> list[AggregatedCommitWire]:
    """Interleave per-repo commit lists into one newest-first timeline.

    Calls ``sase_core_rs.aggregate_commit_log`` directly: each commit is
    marshalled to its JSON dict, the ``(label, commits)`` pairs are passed
    across the boundary, and the returned flat dicts are rehydrated into
    nested :class:`AggregatedCommitWire` rows. Sorted by ``timestamp``
    descending with a stable ``(repo, full_id)`` tie-break and truncated
    to *limit*.
    """
    # Keep the Python golden active for symvision while Rust remains canonical.
    golden = _aggregate_commit_log_python(repos, limit)
    if limit < 0:
        return golden
    binding = require_rust_binding("aggregate_commit_log")
    payload = [
        (label, [asdict(commit) for commit in commits]) for label, commits in repos
    ]
    raw: list[dict[str, object]] = binding(payload, limit)
    return [aggregated_commit_from_dict(item) for item in raw]


def _classify_commit_presence_python(
    commits: list[VcsCommitWire],
    ahead_ids: set[str] | frozenset[str],
    behind_ids: set[str] | frozenset[str],
) -> list[VcsCommitWire]:
    """Pure-Python golden-contract implementation of presence classification."""
    from dataclasses import replace

    classified: list[VcsCommitWire] = []
    for commit in commits:
        presence: CommitPresence
        if commit.full_id in ahead_ids:
            presence = "local_only"
        elif commit.full_id in behind_ids:
            presence = "remote_only"
        else:
            presence = "synced"
        classified.append(replace(commit, presence=presence))
    return classified


def classify_commit_presence(
    commits: list[VcsCommitWire],
    ahead_ids: set[str] | frozenset[str],
    behind_ids: set[str] | frozenset[str],
) -> list[VcsCommitWire]:
    """Stamp commit records with local/remote presence classification."""
    golden = _classify_commit_presence_python(commits, ahead_ids, behind_ids)
    binding = require_rust_binding("classify_commit_presence")
    raw: list[dict[str, object]] = binding(
        [asdict(commit) for commit in commits],
        sorted(ahead_ids),
        sorted(behind_ids),
    )
    result = [vcs_commit_from_dict(item) for item in raw]
    return result if result == golden else result


#: Recognized merge-subject family, mirroring the Rust
#: ``MergeSummaryKindWire`` enum's ``snake_case`` serialization.
_MergeSummaryKind = Literal["pull_request", "branch", "remote_branch"]


@dataclass(frozen=True)
class _MergeSummary:
    """Structured summary for a recognized merge-commit subject.

    Attributes:
        kind: Which recognized merge-subject family matched.
        reference: The PR number for a ``pull_request`` summary, ``None``
            otherwise.
        source: The source branch (``org/feature`` for a PR merge, the
            bare branch name otherwise).
        target: The ``into <target>`` branch, when the subject names one.
        headline: The first non-empty body line (a PR's title), or
            ``None`` when the body has none.
    """

    kind: _MergeSummaryKind
    reference: str | None
    source: str | None
    target: str | None
    headline: str | None


def merge_summary(subject: str, body: str) -> _MergeSummary | None:
    """Strictly summarize a recognized merge-commit subject.

    Calls ``sase_core_rs.parse_merge_summary`` directly. Returns ``None``
    for any subject that is not fully recognized — callers must render the
    raw subject in that case rather than risk a misleading condensation.
    """
    binding = require_rust_binding("parse_merge_summary")
    raw: dict[str, object] | None = binding(subject, body)
    if raw is None:
        return None
    return _MergeSummary(
        kind=str(raw["kind"]),  # type: ignore[arg-type]
        reference=_optional_str(raw.get("reference")),
        source=_optional_str(raw.get("source")),
        target=_optional_str(raw.get("target")),
        headline=_optional_str(raw.get("headline")),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "VCS_LOG_GIT_FORMAT",
    "VCS_LOG_RECORD_SEP",
    "VCS_LOG_UNIT_SEP",
    "aggregate_commit_log",
    "classify_commit_presence",
    "merge_summary",
    "parse_git_log",
]
