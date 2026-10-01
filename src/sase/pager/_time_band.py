"""Time-band chrome for memory-history pager sections.

Pure Rich renderers for the ``#pager-time`` region between the trail band
and the chrome rule (epic design ``plan:202609/memory_history.md`` §4.4).
Everything here is a plain function from timeline data to a Rich
:class:`~rich.text.Text`, so the shapes are unit-testable without booting
an app — modelled on ``_trail_chrome_band.py``.

Row plan (the band is the feature's signature visual):

- At now: a one-row life strip — sparkline, ``last changed …``, and
  ``◌ uncommitted`` when dirty.
- In the past: two rows — a meaning row (class glyph, section path, word
  delta, frontmatter semantics; bead, agent, short SHA on the right) and a
  time row (sparkline, absolute date, ``→ now``, dirty and upstream
  markers).
- Instruction subjects show a cause row instead of the meaning row.
- Honest states (untracked, ignored, no VCS, shallow, template, indexing,
  unavailable) render inside the band and never block the body: states
  with no usable history collapse the band to one honest row, while
  shallow/template annotate the normal rows.

Glyphmirror note: the per-class glyphs intentionally mirror
``sase.memory.history.vocabulary.CLASS_GLYPHS`` so pager core keeps its
no-memory-imports seam (the pager must work before any memory provider
is discovered). ``tests/pager/test_time_band.py`` asserts the two tables
stay identical.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text

#: Bar heights for the log-scaled per-version word volume (one cell each).
SPARKLINE_BLOCKS = "▁▂▃▄▅▆▇█"

#: Cell drawn for hidden-by-default versions inside the sparkline.
HIDDEN_CELL = "·"

#: Style roles for band chrome. The past accent stays violet, never amber:
#: amber already means uncommitted or unpublished (matches ``_chrome.py``).
PAST_STYLE = "#9d7cd8"
UNCOMMITTED_STYLE = "yellow"
DELETED_STYLE = "red"
DIM_STYLE = "dim"
BAND_LABEL_STYLE = "bold black on #FFD75F"

#: Classes hidden unless ``-a/--all`` is passed. Mirrors
#: ``sase.memory.history.vocabulary.HIDDEN_CLASSES``.
HIDDEN_CLASSES: frozenset[str] = frozenset(("moved", "reflow", "whitespace"))

#: Glyph per core version class. Mirrors
#: ``sase.memory.history.vocabulary.CLASS_GLYPHS``.
CLASS_GLYPHS: dict[str, str] = {
    "created": "✚",
    "authored": "◆",
    "promoted": "⇧",
    "demoted": "⇩",
    "frontmatter": "▣",
    "rendered": "⟳",
    "regenerated": "⟳",
    "config": "⚙",
    "regen_only": "⚙",
    "reflow": "≈",
    "whitespace": "≈",
    "moved": "↦",
    "deleted": "✖",
    "uncommitted": "◌",
    "staged": "◌",
    "unclassified": "?",
}

#: Compact chip text for the aliased/diverged instruction states.
ALIAS_SEPARATOR = "≡"
DIVERGED_CHIP = "⚠ diverged"

TimeState = Literal["hidden", "now", "past"]


def _glyph_for_class(class_name: str) -> str:
    """Return the band glyph for a core version class."""
    return CLASS_GLYPHS.get(class_name, "?")


def _is_hidden_class(class_name: str) -> bool:
    """Return whether a class is hidden unless ``-a/--all`` is passed."""
    return class_name in HIDDEN_CLASSES


def format_age(now_epoch: int, then_epoch: int) -> str:
    """Return a compact relative age (``3d``, ``8d``, ``5mo``).

    Mirrors ``sase.memory.history.render_text.format_age`` for pager-core
    use without importing memory modules.
    """
    delta = max(0, now_epoch - then_epoch)
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 30 * 86400:
        return f"{delta // 86400}d"
    if delta < 365 * 86400:
        return f"{delta // (30 * 86400)}mo"
    return f"{delta // (365 * 86400)}y"


def _format_absolute(epoch: int) -> str:
    """Return an absolute local date and time (``Sep 22 2026 14:03``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d %Y %H:%M")


def short_display_for_subject_id(subject_id: str) -> str:
    """Return a compact display name for a subject id.

    Mirrors ``sase.memory.history.render_text.short_display_for_subject_id``
    so cause-row sources read exactly like the CLI renders them.
    """
    kind, _, rest = subject_id.partition(":")
    name = rest.split("/", 1)[1] if "/" in rest else rest
    if kind == "strand":
        return name.replace("/", ":")
    if kind == "instructions":
        if name in (".", ""):
            return "AGENTS.md"
        return f"{name}/AGENTS.md"
    if kind in ("web", "asset"):
        return name
    return name


def _subject_kind_of(subject_id: str) -> str:
    """Return the subject kind embedded in a subject id."""
    kind, _, _ = subject_id.partition(":")
    return kind or "note"


def render_sparkline(
    volumes: list[int],
    classes: list[str],
    current: int | None,
    width: int,
) -> Text:
    """Render one sparkline cell per version, bucketing down to *width*.

    Bar height is the log-scaled word volume. Promotions and demotions use
    the past accent, deletions the error colour, regenerations dim, and
    hidden versions a dim dot. The current version's cell is drawn in the
    past accent with reverse video.
    """
    text = Text(no_wrap=True, overflow="crop")
    width = max(0, int(width))
    count = min(len(volumes), len(classes))
    if width == 0 or count == 0:
        return text
    cells = min(count, width)
    peak = max((max(0, int(volume)) for volume in volumes[:count]), default=0)
    for cell in range(cells):
        start = (cell * count) // cells
        end = max(((cell + 1) * count) // cells, start + 1)
        bucket_volumes = [max(0, int(volumes[index])) for index in range(start, end)]
        bucket_classes = [classes[index] for index in range(start, end)]
        bucket = max(range(len(bucket_volumes)), key=lambda i: bucket_volumes[i])
        volume = bucket_volumes[bucket]
        class_name = bucket_classes[bucket]
        is_current = (
            current is not None and start <= current < end and cells == count
        ) or (
            current is not None and cells < count and (current * cells) // count == cell
        )
        if all(_is_hidden_class(name) for name in bucket_classes):
            text.append(HIDDEN_CELL, style=DIM_STYLE)
            continue
        if peak <= 0:
            char = SPARKLINE_BLOCKS[0]
        else:
            import math

            ratio = math.log1p(volume) / math.log1p(peak)
            char = SPARKLINE_BLOCKS[min(int(round(ratio * 7)), 7)]
        style = _spark_style(class_name, is_current=is_current)
        text.append(char, style=style)
    return text


def _spark_style(class_name: str, *, is_current: bool) -> str:
    """Return the sparkline cell style for one version class."""
    if is_current:
        return f"{PAST_STYLE} reverse"
    if class_name == "deleted":
        return DELETED_STYLE
    if class_name in ("promoted", "demoted"):
        return PAST_STYLE
    if class_name in ("rendered", "regenerated", "regen_only", "config"):
        return DIM_STYLE
    return ""


def chrome_row_budget(
    height: int,
    trail_visible: bool,
    time_state: TimeState | str | None,
) -> tuple[int, int]:
    """Decide row counts for the trail band and the time band together.

    Returns ``(trail_rows, time_rows)``. The past band drops its time row
    below about 30 rows of height, or when the trail band is visible below
    about 40; at 12 rows or fewer the band folds into the subject chip.
    This replaces the trail band's standalone height rule so the two bands
    degrade as one unit.
    """
    screen_height = max(int(height), 1)
    trail_rows = 0
    if trail_visible:
        trail_rows = 1 if screen_height <= 12 else 2
    state = str(time_state or "hidden")
    if state in ("hidden", "folded") or screen_height <= 12:
        return (trail_rows, 0)
    if state == "now":
        return (trail_rows, 1)
    if screen_height < 30 or (trail_visible and screen_height < 40):
        return (trail_rows, 1)
    return (trail_rows, 2)


#: Honest states with no usable history: the band collapses to one row.
NO_HISTORY_HONEST = frozenset({"untracked", "ignored", "no_vcs", "unavailable"})


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


def _honest_row_text(kind: str, detail: str | None) -> Text:
    """Render the one-row honest notice for states with no history."""
    text = Text(no_wrap=True, overflow="crop")
    if kind == "indexing":
        text.append("indexing…", style=DIM_STYLE)
    elif kind == "untracked":
        text.append("UNTRACKED", style=f"bold {UNCOMMITTED_STYLE}")
        text.append(" · commit this file to start its history", style=DIM_STYLE)
    elif kind == "ignored":
        text.append("IGNORED", style=f"bold {UNCOMMITTED_STYLE}")
    elif kind == "no_vcs":
        text.append("NO VCS", style=DIM_STYLE)
        text.append(" · home memory is not in git", style=DIM_STYLE)
    elif kind == "unavailable":
        reason = detail or "unknown reason"
        text.append(f"history unavailable: {reason}", style=DIM_STYLE)
    else:
        text.append("indexing…", style=DIM_STYLE)
    return text


def _honest_prefix(kind: str, detail: str | None) -> Text | None:
    """Return the leading honest segment for history-backed rows, if any."""
    if kind == "shallow":
        text = Text(no_wrap=True, overflow="crop")
        text.append("SHALLOW", style=DIM_STYLE)
        if detail:
            text.append(f" · history truncated at {detail}", style=DIM_STYLE)
        else:
            text.append(" · history truncated", style=DIM_STYLE)
        return text
    if kind == "template":
        text = Text(no_wrap=True, overflow="crop")
        text.append("TEMPLATE", style=DIM_STYLE)
        text.append(" · per-host rendering", style=DIM_STYLE)
        return text
    return None


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
class _TimeBandVersion:
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
    versions: tuple[_TimeBandVersion, ...] = ()
    spark_current: int | None = None
    current: _TimeBandVersion | None = None
    newest: _TimeBandVersion | None = None
    dirty: bool = False
    honest_kind: str = "ok"
    honest_detail: str | None = None
    upstream_ahead: int | None = None
    upstream_branch: str | None = None
    is_template: bool = False
    managed: bool = True
    now_epoch: int = 0
    total_visible: int = 0


def _versions_from_timeline(
    timeline: Mapping[str, Any],
) -> tuple[_TimeBandVersion, ...]:
    """Normalize wire version rows, oldest first, skipping pseudo-versions."""
    rows = timeline.get("versions", ())
    parsed: list[_TimeBandVersion] = []
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


def _version_from_row(row: Mapping[str, Any], ordinal: int) -> _TimeBandVersion:
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
    return _TimeBandVersion(
        ordinal=ordinal,
        commit=str(row.get("commit", "") or ""),
        committer_time=committer_time,
        class_name=class_name,
        hidden=hidden or _is_hidden_class(class_name),
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
    current: _TimeBandVersion | None = None
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


def render_time_band(
    data: TimeBandData,
    *,
    width: int,
    rows: int,
    hints: Mapping[int, str] | None = None,
) -> Text:
    """Render the band for *data*, clipped to *width* cells per row.

    *rows* is the budgeted row count from :func:`chrome_row_budget` (0–2).
    *hints* maps target indexes from :func:`time_band_targets` to their
    jump-hint capsules, painted before each target occurrence.
    """
    width = max(0, int(width))
    rows = max(0, min(int(rows), 2))
    text = Text(no_wrap=True, overflow="crop")
    if width == 0 or rows == 0 or data.mode == "notice":
        if data.mode == "notice" and width and rows:
            return _fit_text(
                _honest_row_text(data.honest_kind, data.honest_detail), width
            )
        return text
    hint_map = dict(hints or {})
    if data.mode == "now":
        return _fit_text(_life_strip_row(data, hint_map), width)
    ordered = time_band_targets(data)
    if rows == 1:
        # Degraded past band: the meaning row survives, the time row drops.
        if data.subject_kind == "instructions":
            return _fit_text(_cause_row(data, ordered, hint_map, width), width)
        return _fit_text(_meaning_row(data, ordered, hint_map, width), width)
    if data.subject_kind == "instructions":
        text.append_text(_fit_text(_cause_row(data, ordered, hint_map, width), width))
    else:
        text.append_text(_fit_text(_meaning_row(data, ordered, hint_map, width), width))
    text.append("\n")
    text.append_text(_fit_text(_time_row(data, width), width))
    return text


def _fit_text(text: Text, width: int) -> Text:
    """Crop *text* to *width* cells with an ellipsis safety net."""
    if width <= 0:
        return Text(no_wrap=True, overflow="crop")
    if cell_len(text.plain) <= width:
        return text
    cropped = text.copy()
    plain = cropped.plain
    kept: list[str] = []
    used = 0
    for character in plain:
        size = cell_len(character)
        if used + size > max(width - 1, 0):
            break
        kept.append(character)
        used += size
    end = len("".join(kept))
    cropped = cropped[:end]
    cropped.append("…")
    return cropped


def _sparkline_for_data(data: TimeBandData, width: int) -> Text:
    """Render the life sparkline for *data* within *width* cells."""
    volumes = [version.volume for version in data.versions]
    classes = [version.class_name for version in data.versions]
    return render_sparkline(volumes, classes, data.spark_current, width)


def _who_text(data: TimeBandData, version: _TimeBandVersion | None) -> str:
    """Return the ``agent.bead`` provenance owner for a life strip."""
    version = version if version is not None else data.newest
    if version is None:
        return ""
    if version.agent and version.bead:
        return f"{version.agent}.{version.bead}"
    return version.agent or version.bead or ""


def _life_strip_row(data: TimeBandData, hint_map: Mapping[int, str]) -> Text:
    """Render the one-row life strip shown at now."""
    del hint_map
    text = Text(no_wrap=True, overflow="crop")
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    if prefix is not None:
        text.append_text(prefix)
        text.append(" · ", style=DIM_STYLE)
    if data.newest is not None and data.newest.committer_time:
        age = format_age(data.now_epoch, data.newest.committer_time)
        who = _who_text(data, data.newest)
        spark = _sparkline_for_data(data, 24)
        text.append_text(spark)
        text.append(f"  last changed {age} ago", style=DIM_STYLE)
        if who:
            text.append(f" · {who}", style=DIM_STYLE)
    elif data.versions:
        text.append_text(_sparkline_for_data(data, 24))
        text.append("  no committed versions", style=DIM_STYLE)
    else:
        text.append("no history yet", style=DIM_STYLE)
    if data.dirty:
        text.append("  ◌ uncommitted", style=UNCOMMITTED_STYLE)
    return text


def _meaning_text(version: _TimeBandVersion) -> tuple[str, str]:
    """Return the ``(glyph, summary)`` left side for a meaning row."""
    glyph = _glyph_for_class(version.class_name)
    if version.class_name == "moved":
        old = version.source_path or version.path
        new = version.path or version.source_path
        if old and new and old != new:
            detail = f"↦ renamed {old} → {new}"
        else:
            detail = "↦ moved"
        if version.similarity is not None:
            detail = f"{detail} {version.similarity}%"
        return (glyph, detail)
    if version.class_name == "created":
        size = f" · {version.created_words}w" if version.created_words else ""
        sections = "".join(f" § {section}" for section in version.section_paths)
        return (glyph, f"created{sections}{size}")
    parts: list[str] = []
    if version.frontmatter_phrase:
        parts.append(version.frontmatter_phrase)
    parts.extend(f"§ {section}" for section in version.section_paths)
    words = _words_text(version)
    if words:
        parts.append(words)
    if not parts:
        parts.append(version.class_name)
    return (glyph, " · ".join(parts))


def _words_text(version: _TimeBandVersion) -> str:
    """Return the word-delta suffix (``+31w -4w``) for a version."""
    if version.class_name == "created":
        return ""
    bits: list[str] = []
    if version.words_added:
        bits.append(f"+{version.words_added}w")
    if version.words_removed:
        bits.append(f"-{version.words_removed}w")
    return " ".join(bits)


def _meaning_row(
    data: TimeBandData,
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    width: int,
) -> Text:
    """Render the past meaning row with SHA→agent→bead→section shedding."""
    version = data.current
    text = Text(no_wrap=True, overflow="crop")
    if version is None:
        return text
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    segments: list[Text] = []
    if prefix is not None:
        segments.append(prefix)
    glyph, summary = _meaning_text(version)
    left = Text(no_wrap=True, overflow="crop")
    left.append(f"{glyph} ", style=PAST_STYLE)
    left.append(summary)
    segments.append(left)
    # Right-side provenance in bead · agent · SHA order; shed SHA, agent,
    # bead, then the section path as width shrinks.
    right_bits: list[tuple[str, Text]] = []
    if version.bead:
        right_bits.append(
            ("bead", _target_text(ordered, hint_map, "bead", version.bead))
        )
    if version.agent:
        right_bits.append(
            ("agent", _target_text(ordered, hint_map, "agent", version.agent))
        )
    if version.commit:
        short = version.commit[:7]
        right_bits.append(("commit", _target_text(ordered, hint_map, "commit", short)))
    shed_sections = " § " in summary
    for shed in ("commit", "agent", "bead", "sections"):
        candidate = _join_meaning_row(segments, right_bits)
        if (
            cell_len(candidate.plain) <= max(width, 0)
            or not right_bits
            and shed != "sections"
        ):
            text.append_text(candidate)
            return text
        if shed == "sections" and shed_sections:
            sections_dropped = Text(no_wrap=True, overflow="crop")
            sections_dropped.append(f"{glyph} ", style=PAST_STYLE)
            head = summary.split(" § ")[0].rstrip("· ")
            words = _words_text(version)
            sections_dropped.append(head + (f" · {words}" if words else ""))
            segments = ([prefix] if prefix is not None else []) + [sections_dropped]
            candidate = _join_meaning_row(segments, right_bits)
            text.append_text(candidate)
            return text
        right_bits = [bit for bit in right_bits if bit[0] != shed]
    candidate = _join_meaning_row(segments, right_bits)
    text.append_text(candidate)
    return text


def _join_meaning_row(segments: list[Text], right_bits: list[tuple[str, Text]]) -> Text:
    """Join meaning-row segments with a two-space gutter before provenance."""
    text = Text(no_wrap=True, overflow="crop")
    for index, segment in enumerate(segments):
        if index:
            text.append(" · ", style=DIM_STYLE)
        text.append_text(segment)
    if right_bits:
        text.append("  ")
        for index, (_, bit) in enumerate(right_bits):
            if index:
                text.append(" · ", style=DIM_STYLE)
            text.append_text(bit)
    return text


def _target_text(
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    kind: str,
    display: str,
) -> Text:
    """Render one band target display with its jump-hint capsule."""
    text = Text(no_wrap=True, overflow="crop")
    for index, target in enumerate(ordered):
        if target.kind == kind and target.display == display:
            hint = hint_map.get(index)
            if hint:
                text.append(f"[{hint}]", style=BAND_LABEL_STYLE)
            break
    text.append(display, style="bold")
    return text


def _cause_row(
    data: TimeBandData,
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    width: int,
) -> Text:
    """Render the instruction-file cause row replacing the meaning row."""
    version = data.current
    text = Text(no_wrap=True, overflow="crop")
    if version is None:
        return text
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    if prefix is not None:
        text.append_text(prefix)
        text.append(" · ", style=DIM_STYLE)
    if not data.managed:
        text.append("◆ hand-edited", style=DIM_STYLE)
    elif version.sources:
        text.append("⟳ rendered", style=DIM_STYLE)
        text.append(" · sources: ", style=DIM_STYLE)
        shown = list(version.sources)
        while shown:
            candidate = _join_sources(shown, ordered, hint_map)
            if cell_len(text.plain) + cell_len(candidate.plain) <= max(width, 0):
                text.append_text(candidate)
                break
            shown = shown[:-1]
        if not shown:
            text.append("…", style=DIM_STYLE)
    elif version.config_paths:
        text.append("⚙ config change", style=DIM_STYLE)
        for path in version.config_paths:
            piece = Text(no_wrap=True, overflow="crop")
            piece.append(" · ", style=DIM_STYLE)
            piece.append(path, style="bold")
            if cell_len(text.plain) + cell_len(piece.plain) > max(width, 0):
                break
            text.append_text(piece)
    else:
        text.append("⚙ regenerated", style=DIM_STYLE)
        text.append(
            " · no source change in this commit (likely a sase upgrade)",
            style=DIM_STYLE,
        )
    chip = _alias_chip(data, version)
    if chip is not None and cell_len(text.plain) + cell_len(chip.plain) + 3 <= max(
        width, 0
    ):
        text.append(" · ", style=DIM_STYLE)
        text.append_text(chip)
    return text


def _join_sources(
    shown: list[tuple[str, str]],
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
) -> Text:
    """Join cause source displays with their hint capsules."""
    text = Text(no_wrap=True, overflow="crop")
    for index, (_subject_id, display) in enumerate(shown):
        if index:
            text.append(", ", style=DIM_STYLE)
        text.append_text(_target_text(ordered, hint_map, "source", display))
    return text


def _alias_chip(data: TimeBandData, version: _TimeBandVersion) -> Text | None:
    """Return the ``≡ AGENTS.md`` / ``⚠ diverged`` chip, if any."""
    if data.subject_kind != "instructions":
        return None
    if version.diverged:
        return Text(DIVERGED_CHIP, style=UNCOMMITTED_STYLE)
    if version.aliased_paths:
        alias = version.aliased_paths[0].replace("\\", "/").rsplit("/", 1)[-1]
        canonical = (version.path.replace("\\", "/").rsplit("/", 1)[-1]) or "AGENTS.md"
        if alias and alias != canonical:
            return Text(f"{alias} {ALIAS_SEPARATOR} {canonical}", style=DIM_STYLE)
    return None


def _time_row(data: TimeBandData, width: int) -> Text:
    """Render the past time row: sparkline, date, and trailing markers."""
    text = Text(no_wrap=True, overflow="crop")
    version = data.current
    if version is None:
        return text
    right = Text(no_wrap=True, overflow="crop")
    right.append("→ now", style=DIM_STYLE)
    if data.dirty:
        right.append(" ◌", style=UNCOMMITTED_STYLE)
    upstream: Text | None = None
    if data.upstream_ahead:
        upstream = Text(no_wrap=True, overflow="crop")
        marker = f"⇡{data.upstream_ahead}"
        if data.upstream_branch:
            marker = f"{marker} on {data.upstream_branch}"
        upstream.append(marker, style=DIM_STYLE)
    date = _format_absolute(version.committer_time) if version.committer_time else ""
    # Shedding order: the absolute date first, then the ⇡N marker.
    spark_room = max(width - cell_len(right.plain) - 4, 1)
    if date:
        date_piece = f"  {date}"
        if upstream is not None:
            probe = f"{date_piece}  {upstream.plain}"
        else:
            probe = date_piece
        if len(data.versions) + cell_len(probe) + cell_len(right.plain) + 4 <= width:
            spark_room = max(width - cell_len(probe) - cell_len(right.plain) - 4, 1)
        else:
            date = ""
    spark_width = min(len(data.versions), spark_room)
    text.append_text(_sparkline_for_data(data, max(spark_width, 1)))
    if date:
        text.append(f"  {date}", style=DIM_STYLE)
    rest = width - cell_len(text.plain) - cell_len(right.plain)
    if upstream is not None and cell_len(upstream.plain) + 3 <= rest:
        text.append("  ")
        text.append_text(upstream)
        rest = width - cell_len(text.plain) - cell_len(right.plain)
    text.append(" " * max(rest, 1))
    text.append_text(right)
    return text


__all__ = [
    "ALIAS_SEPARATOR",
    "BAND_LABEL_STYLE",
    "CLASS_GLYPHS",
    "DELETED_STYLE",
    "DIM_STYLE",
    "DIVERGED_CHIP",
    "HIDDEN_CELL",
    "HIDDEN_CLASSES",
    "NO_HISTORY_HONEST",
    "PAST_STYLE",
    "SPARKLINE_BLOCKS",
    "TimeBandData",
    "TimeBandTarget",
    "TimeState",
    "UNCOMMITTED_STYLE",
    "build_time_band_data",
    "chrome_row_budget",
    "format_age",
    "ref_for_target",
    "render_sparkline",
    "render_time_band",
    "short_display_for_subject_id",
    "time_band_targets",
]
