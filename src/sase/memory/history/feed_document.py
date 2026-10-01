"""Pager changes-feed document for ``sase memory history`` with no selector.

Turns ``memory_history_feed`` output into an ordinary pager document with
one section per day (epic design ``plan:202609/memory_history.md`` §4.7
and §15), so ``ctrl+n``/``ctrl+p`` jump between days and search, labels,
and the trail work unchanged.

- Changeset rows show time, subject line, ``⌂`` for home, and provenance
  labels (bead, agent, commit through the existing resolvers).
- Each authored subject row is a label that opens ``subject@version`` in
  the diff view and pushes a trail entry (via the ``resolve_ref_fn`` the
  CLI installs; see :func:`resolve_feed_subject`).
- Generated consequences fold under their cause as one dim ``⟳`` line.
- Regen-only changesets collapse into a per-day count line that reuses
  the diff-view fold mechanism (``history-fold`` kind with an integer
  target): activating it recomposes the day section in place through the
  document's ``expand_fold_fn`` hook, with no trail push.
- Home changesets interleave, tagged ``⌂``.

This module is pure and Textual-free: it renders ``Text`` bodies plus
:class:`~sase.pager.document.AttachedTarget` lists from plain feed dicts,
so builder goldens never need git or the Rust core.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from rich.text import Text

from sase.memory.history.render_text import (
    short_display_for_subject_id,
    summary_text,
)
from sase.memory.history.vocabulary import HOME_TAG, glyph_for
from sase.pager.document import AttachedTarget, PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.diff import FOLD_TARGET_KIND, FOLD_TOKEN

#: Identity prefix for feed day sections. Feed sections carry no
#: ``subject_ref`` or version pin, so the memory history provider never
#: claims them for the time axis.
FEED_SECTION_PREFIX = "history-feed:"

#: Attached-target kind for authored subject rows. The target is a JSON
#: envelope (see :func:`_feed_subject_target`) naming scope, selector, and
#: revision; the CLI's ``resolve_ref_fn`` turns it into a diff-view
#: document, which pushes a trail entry through the normal follow path.
FEED_SUBJECT_KIND = "history-feed-subject"

#: Attached-target kind for provenance items, routed through the existing
#: artifact resolvers (bead opens the bead; agent and commit degrade to
#: copy-only notices when no resolver exists).
FEED_PROVENANCE_KIND = "artifact_ref"

#: Envelope marker identifying a feed-subject target string.
_FEED_SUBJECT_MARKER = "history-feed-subject"

#: Style for dimmed feed chrome (boilerplate rows, consequences, counts).
_FEED_DIM_STYLE = "dim"


@dataclass(frozen=True, slots=True)
class _FeedSubject:
    """One authored subject row's navigation payload."""

    scope_key: str
    selector: str
    revision: str
    display: str


@dataclass(frozen=True, slots=True)
class _FeedFold:
    """One collapsed regen-only group inside a day section."""

    section_identity: str
    fold_index: int
    day_key: str
    hidden_count: int


@dataclass(frozen=True, slots=True)
class _FeedDocumentResult:
    """A built feed document plus its in-place fold table."""

    document: PagerDocument
    folds: tuple[_FeedFold, ...] = ()


def _feed_subject_target(subject: _FeedSubject) -> str:
    """Return the attached-target string for one authored subject row."""
    return json.dumps(
        {
            "kind": _FEED_SUBJECT_MARKER,
            "scope_key": subject.scope_key,
            "selector": subject.selector,
            "revision": subject.revision,
        },
        sort_keys=True,
    )


def parse_feed_subject_target(ref: str) -> _FeedSubject | None:
    """Return the :class:`_FeedSubject` encoded in *ref*, if any."""
    try:
        payload = json.loads(ref)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != _FEED_SUBJECT_MARKER:
        return None
    scope_key = payload.get("scope_key")
    selector = payload.get("selector")
    revision = payload.get("revision")
    if not (
        isinstance(scope_key, str)
        and isinstance(selector, str)
        and isinstance(revision, str)
        and scope_key
        and selector
        and revision
    ):
        return None
    return _FeedSubject(
        scope_key=scope_key, selector=selector, revision=revision, display=""
    )


def _day_key(epoch: int) -> str:
    """Return the grouping key (local ``YYYY-MM-DD``) for *epoch*."""
    if not epoch:
        return "undated"
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def _day_header(epoch: int) -> str:
    """Return the day section title (``Mon Sep 28``) for *epoch*."""
    if not epoch:
        return "undated"
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d")


def _format_clock(epoch: int) -> str:
    """Return a local clock time (``11:03``) for *epoch*."""
    if not epoch:
        return "--:--"
    return datetime.datetime.fromtimestamp(epoch).strftime("%H:%M")


def _words_suffix(summary: dict[str, Any], class_name: str) -> str:
    """Return the word-delta suffix (``+31w −4w``) for a version."""
    if class_name == "created":
        return ""
    added = int(summary.get("words_added", 0) or 0)
    removed = int(summary.get("words_removed", 0) or 0)
    parts = []
    if added:
        parts.append(f"+{added}w")
    if removed:
        parts.append(f"-{removed}w")
    return " ".join(parts)


def _entry_selector(entry: dict[str, Any]) -> str:
    """Return the core selector identifying one feed entry's subject."""
    path = entry.get("path")
    if isinstance(path, str) and path:
        return path
    subject_id = entry.get("subject_id")
    if isinstance(subject_id, str) and subject_id:
        return subject_id
    return ""


def _entry_revision(entry: dict[str, Any], changeset_commit: str | None) -> str:
    """Return the version revision (``vN`` or SHA) for one feed entry."""
    try:
        ordinal = int(entry.get("ordinal", 0) or 0)
    except (TypeError, ValueError):
        ordinal = 0
    if ordinal > 0:
        return f"v{ordinal}"
    commit = entry.get("commit")
    if isinstance(commit, str) and commit:
        return commit
    if isinstance(changeset_commit, str) and changeset_commit:
        return changeset_commit
    return "now"


class _BodyBuilder:
    """Accumulate feed section text plus attached-target spans."""

    def __init__(self) -> None:
        self._chunks: list[tuple[str, str | None]] = []
        self._targets: list[AttachedTarget] = []
        self._length = 0

    def text(self, value: str, *, style: str | None = None) -> None:
        """Append plain (untargeted) text."""
        if not value:
            return
        self._chunks.append((value, style))
        self._length += len(value)

    def target(
        self,
        kind: str,
        target: object,
        value: str,
        *,
        style: str | None = None,
    ) -> None:
        """Append *value* as one attached-target span."""
        if not value:
            return
        start = self._length
        self._chunks.append((value, style))
        self._length += len(value)
        self._targets.append(
            AttachedTarget(
                kind=kind, target=target, start=start, end=self._length, text=value
            )
        )

    def build(self) -> tuple[Text, tuple[AttachedTarget, ...]]:
        """Return the assembled body and its attached targets."""
        body = Text()
        for chunk, style in self._chunks:
            body.append(chunk, style=style)
        return body, tuple(self._targets)


def _provenance_targets(build: _BodyBuilder, changeset: dict[str, Any]) -> None:
    """Append bead/agent/commit provenance labels for one changeset row."""
    provenance = changeset.get("provenance", {})
    if not isinstance(provenance, dict):
        return
    bead = provenance.get("bead")
    agent = provenance.get("agent")
    commit = changeset.get("commit")
    bits: list[tuple[str, str]] = []
    if isinstance(bead, str) and bead:
        bits.append((bead, f"bead:{bead}"))
    if isinstance(agent, str) and agent:
        bits.append((agent, f"agent:{agent}"))
    short = commit[:7] if isinstance(commit, str) and commit else ""
    if short:
        bits.append((short, f"commit:{commit}"))
    for position, (visible, ref) in enumerate(bits):
        if position:
            build.text(" · ", style=_FEED_DIM_STYLE)
        build.target(FEED_PROVENANCE_KIND, ref, visible)


def _render_changeset_rows(
    build: _BodyBuilder,
    changeset: dict[str, Any],
    *,
    scope_key: str,
    dimmed: bool = False,
) -> None:
    """Append one changeset's rows (changeset, subjects, consequences)."""
    provenance = changeset.get("provenance", {})
    subject = provenance.get("subject") if isinstance(provenance, dict) else None
    committer_time = changeset.get("committer_time")
    epoch = int(committer_time or 0)
    home = scope_key == "home"
    boilerplate = bool(changeset.get("boilerplate", False))
    row_style: str | None = _FEED_DIM_STYLE if (dimmed or boilerplate) else None
    build.text(f"  {_format_clock(epoch)}  ", style=row_style)
    build.text(str(subject or "(no subject)"), style=row_style)
    meta_style: str | None = _FEED_DIM_STYLE
    if home or _has_provenance(changeset):
        build.text("   ", style=meta_style)
        if home:
            build.text(f"{HOME_TAG}  ", style=meta_style)
        _provenance_targets(build, changeset)
    build.text("\n")
    for entry in changeset.get("authored", ()):
        if not isinstance(entry, dict):
            continue
        commit = changeset.get("commit")
        _render_subject_row(
            build,
            dict(entry),
            scope_key=scope_key,
            changeset_commit=commit if isinstance(commit, str) else None,
            dimmed=dimmed,
        )
    consequences = [
        item for item in changeset.get("consequences", ()) if isinstance(item, dict)
    ]
    if consequences:
        build.text("            ⟳ ", style=_FEED_DIM_STYLE)
        build.text(
            " · ".join(
                short_display_for_subject_id(str(item.get("subject_id", "")))
                for item in consequences
            ),
            style=_FEED_DIM_STYLE,
        )
        build.text("\n")


def _has_provenance(changeset: dict[str, Any]) -> bool:
    """Return whether a changeset row carries bead/agent/commit labels."""
    provenance = changeset.get("provenance", {})
    if isinstance(provenance, dict) and (
        provenance.get("bead") or provenance.get("agent")
    ):
        return True
    commit = changeset.get("commit")
    return isinstance(commit, str) and bool(commit)


def _render_subject_row(
    build: _BodyBuilder,
    entry: dict[str, Any],
    *,
    scope_key: str,
    changeset_commit: str | None = None,
    dimmed: bool = False,
) -> None:
    """Append one authored subject row with its navigation label."""
    subject_id = str(entry.get("subject_id", ""))
    class_name = str(entry.get("class", "unclassified"))
    display = short_display_for_subject_id(subject_id)
    summary = entry.get("summary", {})
    summary_text_value = summary_text(
        dict(summary) if isinstance(summary, dict) else {}, class_name
    )
    words = _words_suffix(
        dict(summary) if isinstance(summary, dict) else {}, class_name
    )
    row_style: str | None = _FEED_DIM_STYLE if dimmed else None
    build.text(f"          {glyph_for(class_name)} ", style=row_style)
    selector = _entry_selector(entry)
    revision = _entry_revision(entry, changeset_commit)
    subject = _FeedSubject(
        scope_key=scope_key, selector=selector, revision=revision, display=display
    )
    if selector:
        build.target(
            FEED_SUBJECT_KIND, _feed_subject_target(subject), display, style=row_style
        )
    else:
        build.text(display, style=row_style)
    if summary_text_value:
        build.text(f"  {summary_text_value}", style=row_style)
    if words:
        build.text(f"  {words}", style=_FEED_DIM_STYLE)
    build.text("\n")


def _render_regen_count_line(
    build: _BodyBuilder, hidden_count: int, *, fold_index: int
) -> None:
    """Append one collapsed regen-only count line (an expandable fold)."""
    noun = "changeset" if hidden_count == 1 else "changesets"
    build.text(
        f"  ⋯ {hidden_count} regenerated-only {noun} hidden · ",
        style=_FEED_DIM_STYLE,
    )
    build.target(FOLD_TARGET_KIND, fold_index, FOLD_TOKEN, style=_FEED_DIM_STYLE)
    build.text("\n")


def _build_feed_section(
    day_key: str,
    day_title: str,
    day_changesets: list[dict[str, Any]],
    *,
    regen_expanded: bool = False,
) -> tuple[PagerSection, tuple[_FeedFold, ...]]:
    """Build one day section, collapsing regen-only changesets by default."""
    build = _BodyBuilder()
    identity = f"{FEED_SECTION_PREFIX}{day_key}"
    folds: list[_FeedFold] = []
    visible = [
        item for item in day_changesets if not bool(item.get("regen_only", False))
    ]
    hidden = [item for item in day_changesets if bool(item.get("regen_only", False))]
    for changeset in visible:
        scope_key = str(changeset.get("scope_key", ""))
        _render_changeset_rows(build, changeset, scope_key=scope_key)
    if hidden and not regen_expanded:
        _render_regen_count_line(build, len(hidden), fold_index=0)
        folds.append(
            _FeedFold(
                section_identity=identity,
                fold_index=0,
                day_key=day_key,
                hidden_count=len(hidden),
            )
        )
    elif hidden:
        for changeset in hidden:
            scope_key = str(changeset.get("scope_key", ""))
            _render_changeset_rows(build, changeset, scope_key=scope_key, dimmed=True)
    body, targets = build.build()
    section = PagerSection(
        identity=identity,
        title=day_title,
        kind="file",
        body=body,
        origin=PagerOrigin.FILE,
        targets=targets,
    )
    return section, tuple(folds)


def _feed_title(
    feed: dict[str, Any], scopes_label: str, *, window_label: str | None
) -> str:
    """Return the feed document title (the header summary)."""
    changesets = feed.get("changesets", ())
    count = len(list(changesets)) if isinstance(changesets, (list, tuple)) else 0
    noun = "changeset" if count == 1 else "changesets"
    title = f"▤ Memory changes · {scopes_label} · {count} {noun}"
    if window_label:
        title += f" · {window_label}"
    return title


def build_feed_document(
    feed: dict[str, Any],
    scopes_label: str,
    *,
    window_label: str | None = None,
    expanded_regen: frozenset[str] | Literal["all"] = frozenset(),
) -> _FeedDocumentResult:
    """Build the pager feed document for one ``memory_history_feed`` result.

    Changesets group by local day (newest first, wire order preserved);
    home changesets interleave with a ``⌂`` tag. Regen-only changesets
    collapse into a per-day count line unless their day is in
    *expanded_regen* (or it is ``"all"``).
    """
    raw_changesets = feed.get("changesets", ())
    changesets = [dict(item) for item in raw_changesets if isinstance(item, dict)]
    days: dict[str, dict[str, Any]] = {}
    for changeset in changesets:
        epoch = int(changeset.get("committer_time", 0) or 0)
        key = _day_key(epoch)
        group = days.get(key)
        if group is None:
            group = {"epoch": epoch, "title": _day_header(epoch), "items": []}
            days[key] = group
        group["items"].append(changeset)
        newest = int(group["epoch"] or 0)
        if epoch > newest:
            group["epoch"] = epoch
            group["title"] = _day_header(epoch)
    expand_all = expanded_regen == "all"
    sections: list[PagerSection] = []
    folds: list[_FeedFold] = []
    if not days:
        build = _BodyBuilder()
        build.text("(no memory changes in this window)", style=_FEED_DIM_STYLE)
        build.text("\n")
        body, targets = build.build()
        sections.append(
            PagerSection(
                identity=f"{FEED_SECTION_PREFIX}empty",
                title="Memory changes",
                kind="file",
                body=body,
                origin=PagerOrigin.FILE,
                targets=targets,
            )
        )
    for key, group in days.items():
        items = list(group["items"])
        expanded = expand_all or key in expanded_regen
        section, section_folds = _build_feed_section(
            key, str(group["title"]), items, regen_expanded=expanded
        )
        sections.append(section)
        folds.extend(section_folds)
    document = PagerDocument(
        sections=tuple(sections),
        title=_feed_title(feed, scopes_label, window_label=window_label),
        origin=PagerOrigin.FILE,
        expand_fold_fn=_make_feed_expander(days, expanded_regen),
    )
    return _FeedDocumentResult(document=document, folds=tuple(folds))


def _make_feed_expander(
    days: dict[str, dict[str, Any]],
    expanded_regen: frozenset[str] | Literal["all"],
) -> Callable[[str, int], PagerSection | None]:
    """Return the document fold hook that expands regen-only groups."""
    expanded: set[str] = set() if expanded_regen == "all" else set(expanded_regen)
    if expanded_regen == "all":
        expanded.update(days.keys())

    def _expand(section_identity: str, fold_index: int) -> PagerSection | None:
        if not section_identity.startswith(FEED_SECTION_PREFIX):
            return None
        day_key = section_identity.removeprefix(FEED_SECTION_PREFIX)
        group = days.get(day_key)
        if group is None or fold_index != 0:
            return None
        if day_key in expanded:
            return None
        expanded.add(day_key)
        section, _ = _build_feed_section(
            day_key, str(group["title"]), list(group["items"]), regen_expanded=True
        )
        return section

    return _expand


def resolve_feed_subject(
    service: Any,
    scopes_by_key: dict[str, Any],
    ref: str,
) -> Any | None:
    """Open a feed subject row's ``subject@version`` in the diff view.

    Returns a :class:`~sase.pager.targets.LinkTarget` carrying the
    diff-view document (the pager follow path pushes the trail entry),
    or ``None`` when *ref* is not a feed-subject target.
    """
    from sase.pager.targets import LinkTarget, LinkTargetKind

    subject = parse_feed_subject_target(ref)
    if subject is None:
        return None
    scope = scopes_by_key.get(subject.scope_key)
    if scope is None:
        return None
    from sase.memory.history.pager_provider import build_history_document

    try:
        resolved = build_history_document(
            scope=scope,
            subject=subject.selector,
            initial_revision=subject.revision,
            view="diff",
            service=service,
        )
    except Exception:
        return None
    return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=resolved)


__all__ = [
    "FEED_PROVENANCE_KIND",
    "FEED_SECTION_PREFIX",
    "FEED_SUBJECT_KIND",
    "build_feed_document",
    "parse_feed_subject_target",
    "resolve_feed_subject",
]
