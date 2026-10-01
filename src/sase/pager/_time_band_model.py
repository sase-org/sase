"""Timeline model for the pager time band.

Normalizes provider timeline wire rows into :class:`TimeBandData` for one
section's moment, and serves the band's jump-label targets ahead of body
targets so band letters stay stable. Row rendering lives in
:mod:`sase.pager._time_band_render`; shared vocabulary lives in
:mod:`sase.pager._time_band_vocab`.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sase.pager._time_band_vocab import NO_HISTORY_HONEST
from sase.pager._time_band_vocab import is_hidden_class
from sase.pager._time_band_vocab import short_display_for_subject_id


@dataclass(frozen=True, slots=True)
class TimeBandTarget:
    """One jump-label target inside the band, in assignment order.

    Targets are assigned before body targets so their letters stay stable.
    ``kind`` selects the resolver: ``bead`` through ``pager/beads.py``,
    ``agent`` through the known agent-chat kinds, ``commit`` through the
    stitch/commit resolver when one exists (copy-only otherwise), and
    ``source`` opens that note at the same commit in the read view.
    """

    kind: Literal["bead", "agent", "commit", "source"]
    display: str
    ref: str
    commit: str | None = None


@dataclass(frozen=True, slots=True)
class TimeBandVersion:
    """One committed version normalized for band rendering."""

    ordinal: int
    commit: str
    committer_time: int
    class_name: str
    hidden: bool
    volume: int
    words_added: int
    words_removed: int
    created_words: int | None
    section_paths: tuple[str, ...] = ()
    frontmatter_phrase: str | None = None
    bead: str | None = None
    agent: str | None = None
    sources: tuple[tuple[str, str], ...] = ()
    config_paths: tuple[str, ...] = ()
    regen_only: bool = False
    diverged: bool = False
    aliased_paths: tuple[str, ...] = ()
    path: str = ""
    source_path: str = ""
    similarity: int | None = None


@dataclass(frozen=True, slots=True)
class TimeBandData:
    """Everything the band needs to paint one section's moment."""

    mode: Literal["now", "past", "notice"]
    subject_id: str
    subject_kind: str
    display_name: str
    versions: tuple[TimeBandVersion, ...] = ()
    spark_current: int | None = None
    current: TimeBandVersion | None = None
    newest: TimeBandVersion | None = None
    dirty: bool = False
    honest_kind: str = "ok"
    honest_detail: str | None = None
    upstream_ahead: int | None = None
    upstream_branch: str | None = None
    is_template: bool = False
    managed: bool = True
    now_epoch: int = 0
    total_visible: int = 0


def _honest_state_kind(
    timeline: Mapping[str, Any] | None,
    *,
    indexing: bool = False,
) -> tuple[str, str | None]:
    """Return the band's honest state as ``(kind, detail)``.

    ``kind`` is one of ``ok``, ``indexing``, ``untracked``, ``ignored``,
    ``no_vcs``, ``shallow``, ``template``, or ``unavailable``. ``detail``
    carries the truncation date, the template note, or the failure reason.
    """
    if indexing or timeline is None:
        return ("indexing", None)
    if not isinstance(timeline, Mapping):
        return ("unavailable", "unexpected timeline shape")
    error = timeline.get("error")
    if isinstance(error, str) and error and error != "unsupported":
        return ("unavailable", error)
    state = str(timeline.get("state", "tracked") or "tracked")
    normalized = state.lower().replace("_", "").replace(" ", "")
    if "untracked" in normalized:
        return ("untracked", None)
    if "ignored" in normalized or "excluded" in normalized:
        return ("ignored", None)
    if normalized in ("novcs", "norepo", "nogit") or "no vcs" in state.lower():
        return ("no_vcs", None)
    health = timeline.get("health")
    if isinstance(health, Mapping) and bool(health.get("shallow")):
        boundary = health.get("shallow_boundary_time")
        detail: str | None = None
        if isinstance(boundary, (int, float)) and boundary:
            try:
                detail = datetime.datetime.fromtimestamp(int(boundary)).strftime(
                    "%Y-%m-%d"
                )
            except (OverflowError, OSError, ValueError):
                detail = None
        return ("shallow", detail)
    if bool(timeline.get("is_template")):
        return ("template", "per-host rendering")
    return ("ok", None)


def _subject_kind_of(subject_id: str) -> str:
    """Return the subject kind embedded in a subject id."""
    kind, _, _ = subject_id.partition(":")
    return kind or "note"


def _versions_from_timeline(
    timeline: Mapping[str, Any],
) -> tuple[TimeBandVersion, ...]:
    """Normalize wire version rows, oldest first, skipping pseudo-versions."""
    rows = timeline.get("versions", ())
    parsed: list[TimeBandVersion] = []
    if not isinstance(rows, (list, tuple)):
        return ()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            ordinal = int(row.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ordinal <= 0:
            continue
        parsed.append(_version_from_row(row, ordinal))
    parsed.sort(key=lambda version: version.ordinal)
    return tuple(parsed)


def _version_from_row(row: Mapping[str, Any], ordinal: int) -> TimeBandVersion:
    summary = row.get("summary")
    summary_map = dict(summary) if isinstance(summary, Mapping) else {}
    provenance = row.get("provenance")
    provenance_map = dict(provenance) if isinstance(provenance, Mapping) else {}
    cause = row.get("cause")
    cause_map = dict(cause) if isinstance(cause, Mapping) else {}
    sources: list[tuple[str, str]] = []
    for entry in cause_map.get("sources", ()):
        if not isinstance(entry, Mapping):
            continue
        subject_id = str(entry.get("subject_id", "") or "")
        if not subject_id:
            continue
        sources.append((subject_id, short_display_for_subject_id(subject_id)))
    config_paths = tuple(
        str(path) for path in cause_map.get("config_paths", ()) if str(path)
    )
    section_paths = tuple(
        str(section) for section in summary_map.get("section_paths", ()) if str(section)
    )
    aliased = tuple(str(path) for path in row.get("aliased_paths", ()) if str(path))
    try:
        similarity = row.get("similarity")
        similarity_value = int(similarity) if similarity is not None else None
    except (TypeError, ValueError):
        similarity_value = None
    class_name = str(row.get("class", "") or "unclassified")
    try:
        created_words_raw = summary_map.get("created_words")
        created_words = (
            int(created_words_raw) if created_words_raw is not None else None
        )
    except (TypeError, ValueError):
        created_words = None
    try:
        volume = int(summary_map.get("volume", 0) or 0)
    except (TypeError, ValueError):
        volume = 0
    try:
        words_added = int(summary_map.get("words_added", 0) or 0)
        words_removed = int(summary_map.get("words_removed", 0) or 0)
    except (TypeError, ValueError):
        words_added, words_removed = 0, 0
    try:
        committer_time = int(row.get("committer_time", 0) or 0)
    except (TypeError, ValueError):
        committer_time = 0
    hidden = bool(row.get("hidden", False) or row.get("hidden_by_default", False))
    bead = provenance_map.get("bead")
    agent = provenance_map.get("agent")
    return TimeBandVersion(
        ordinal=ordinal,
        commit=str(row.get("commit", "") or ""),
        committer_time=committer_time,
        class_name=class_name,
        hidden=hidden or is_hidden_class(class_name),
        volume=max(volume, 0),
        words_added=max(words_added, 0),
        words_removed=max(words_removed, 0),
        created_words=created_words,
        section_paths=section_paths,
        frontmatter_phrase=str(summary_map.get("frontmatter_phrase") or "") or None,
        bead=str(bead) if bead else None,
        agent=str(agent) if agent else None,
        sources=tuple(sources),
        config_paths=config_paths,
        regen_only=bool(cause_map.get("regen_only", False)),
        diverged=bool(row.get("diverged", False)),
        aliased_paths=aliased,
        path=str(row.get("path", "") or ""),
        source_path=str(row.get("source_path", "") or ""),
        similarity=similarity_value,
    )


def build_time_band_data(
    *,
    subject_id: str,
    timeline: Mapping[str, Any] | None,
    current_ordinal: int,
    dirty: bool = False,
    loading: bool = False,
    now_epoch: int = 0,
    total_visible: int = 0,
) -> TimeBandData | None:
    """Build the band model for one section's moment, or ``None`` to hide.

    ``current_ordinal`` 0 means the live worktree (now); positive ordinals
    are committed versions. ``timeline`` carries the provider's timeline
    wire plus ``upstream_ahead``, ``health``, ``is_template``, and
    ``managed`` annotations. ``None`` while indexing yields the dim
    ``indexing…`` notice row.
    """
    kind, detail = _honest_state_kind(timeline, indexing=loading)
    subject_kind = _subject_kind_of(subject_id)
    display_name = short_display_for_subject_id(subject_id)
    upstream_ahead: int | None = None
    upstream_branch: str | None = None
    is_template = False
    managed = True
    if isinstance(timeline, Mapping):
        raw_ahead = timeline.get("upstream_ahead")
        try:
            upstream_ahead = int(raw_ahead) if raw_ahead is not None else None
        except (TypeError, ValueError):
            upstream_ahead = None
        branch = timeline.get("upstream_branch")
        upstream_branch = str(branch) if branch else None
        is_template = bool(timeline.get("is_template", False))
        if timeline.get("managed") is not None:
            managed = bool(timeline.get("managed"))
    if kind in NO_HISTORY_HONEST or (kind == "indexing" and timeline is None):
        if kind == "indexing" and isinstance(timeline, Mapping):
            kind = "ok"
        else:
            return TimeBandData(
                mode="notice",
                subject_id=subject_id,
                subject_kind=subject_kind,
                display_name=display_name,
                honest_kind=kind,
                honest_detail=detail,
                dirty=dirty,
                upstream_ahead=upstream_ahead,
                upstream_branch=upstream_branch,
                is_template=is_template,
                managed=managed,
                now_epoch=now_epoch,
                total_visible=total_visible,
            )
    if timeline is None:
        return None
    versions = _versions_from_timeline(timeline)
    if not versions:
        if kind != "ok":
            return TimeBandData(
                mode="notice",
                subject_id=subject_id,
                subject_kind=subject_kind,
                display_name=display_name,
                honest_kind=kind,
                honest_detail=detail,
                dirty=dirty,
                upstream_ahead=upstream_ahead,
                upstream_branch=upstream_branch,
                is_template=is_template,
                managed=managed,
                now_epoch=now_epoch,
                total_visible=total_visible,
            )
        return None
    newest = versions[-1]
    current: TimeBandVersion | None = None
    spark_current: int | None = None
    if current_ordinal > 0:
        for index, version in enumerate(versions):
            if version.ordinal == current_ordinal:
                current = version
                spark_current = index
                break
        if current is None:
            return None
        mode: Literal["now", "past", "notice"] = "past"
    else:
        mode = "now"
    if kind == "template":
        is_template = True
    return TimeBandData(
        mode=mode,
        subject_id=subject_id,
        subject_kind=subject_kind,
        display_name=display_name,
        versions=versions,
        spark_current=spark_current,
        current=current,
        newest=newest,
        dirty=dirty,
        honest_kind=kind,
        honest_detail=detail,
        upstream_ahead=upstream_ahead,
        upstream_branch=upstream_branch,
        is_template=is_template,
        managed=managed,
        now_epoch=now_epoch,
        total_visible=total_visible,
    )


def time_band_targets(data: TimeBandData) -> tuple[TimeBandTarget, ...]:
    """Return the band's jump-label targets in assignment order.

    Provenance items (bead, agent, SHA) come first, then cause sources, so
    band letters stay stable ahead of body targets.
    """
    if data.mode != "past" or data.current is None:
        return ()
    targets: list[TimeBandTarget] = []
    version = data.current
    if version.bead:
        targets.append(
            TimeBandTarget(
                kind="bead", display=version.bead, ref=f"bead:{version.bead}"
            )
        )
    if version.agent:
        targets.append(
            TimeBandTarget(
                kind="agent", display=version.agent, ref=f"agent:{version.agent}"
            )
        )
    if version.commit:
        targets.append(
            TimeBandTarget(
                kind="commit",
                display=version.commit[:7],
                ref=f"commit:{version.commit}",
                commit=version.commit,
            )
        )
    if data.subject_kind == "instructions":
        for _subject_id, display in version.sources:
            targets.append(TimeBandTarget(kind="source", display=display, ref=display))
    return tuple(targets)


def ref_for_target(target: TimeBandTarget) -> str:
    """Return the ref string ``resolve_ref`` should receive for *target*."""
    return target.ref


__all__ = [
    "TimeBandData",
    "TimeBandTarget",
    "TimeBandVersion",
    "build_time_band_data",
    "ref_for_target",
    "time_band_targets",
]
