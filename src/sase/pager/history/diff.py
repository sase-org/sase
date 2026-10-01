"""Word-diff body builder for the pager history diff view.

Pure and Textual-free: given a core prose comparison plus the target
body, this module renders the ``=`` diff view as one Rich
:class:`~rich.text.Text` — inline word insertions and struck-through
deletions, a frontmatter semantic block, and folds of unchanged runs
that expand in place from a jump-label target.

Line numbers below are 1-based target-body lines. The composed
diff-body lines (frontmatter block, fold labels, removal markers)
shift positions, so this module also returns change lines in
*diff-body* coordinates for ``[``/``]`` navigation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.pager.document import AttachedTarget

#: Lines of unchanged context kept on each side of a change.
DIFF_CONTEXT_LINES = 3

#: Attached-target kind for fold labels; activation expands the fold.
FOLD_TARGET_KIND = "history-fold"

#: Visible token inside each fold label that carries the jump label.
FOLD_TOKEN = "expand"

#: Theme-agnostic word styles (success for inserts, struck error for deletes).
INSERT_STYLE = "bold green"
DELETE_STYLE = "strike red"
FOLD_STYLE = "dim"
SECTION_STYLE = "dim"
REMOVAL_STYLE = "red"
FRONTMATTER_PROMOTE_STYLE = "magenta"
FRONTMATTER_ENTRY_STYLE = ""

_DELETE_KINDS = frozenset({"delete", "remove", "replace"})
_INSERT_KINDS = frozenset({"insert", "add"})


@dataclass(frozen=True, slots=True)
class _DiffFold:
    """One collapsed run of unchanged target lines."""

    index: int
    start_line: int
    end_line: int

    @property
    def hidden_count(self) -> int:
        """Return the number of unchanged lines this fold hides."""
        return max(0, self.end_line - self.start_line + 1)


@dataclass(slots=True)
class _DiffBody:
    """One rendered diff view plus its navigation metadata."""

    text: Text
    folds: tuple[_DiffFold, ...] = ()
    fold_targets: tuple[AttachedTarget, ...] = ()
    change_lines: tuple[int, ...] = ()
    unified_diff: str = ""
    empty: bool = False


def _comparison_of(comparison: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(comparison, dict):
        return {}
    return comparison


def unified_diff_for_comparison(comparison: dict[str, Any] | None) -> str:
    """Return the unified diff text carried by *comparison*, if any."""
    inner = _comparison_of(comparison)
    return str(inner.get("unified_diff", "") or "")


def _frontmatter_block(comparison: dict[str, Any] | None) -> Text:
    """Render the frontmatter semantic block for *comparison*."""
    inner = _comparison_of(comparison)
    raw = inner.get("frontmatter")
    frontmatter = raw if isinstance(raw, dict) else {}
    block = Text()
    type_change = frontmatter.get("type_change")
    if type_change == "promoted":
        block.append(
            "⇧ type: reference → core — now loaded by every agent\n",
            style=FRONTMATTER_PROMOTE_STYLE,
        )
    elif type_change == "demoted":
        block.append(
            "⇩ type: core → reference — no longer loaded by every agent\n",
            style=FRONTMATTER_PROMOTE_STYLE,
        )
    entries = frontmatter.get("entries", ())
    if isinstance(entries, dict):
        entries = (entries,)
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "") or "")
        before = str(entry.get("before", "") or "")
        after = str(entry.get("after", "") or "")
        if not key:
            continue
        block.append(f"▣ {key}: {before} → {after}\n", style=FRONTMATTER_ENTRY_STYLE)
    return block


def _word_ops_by_line(comparison: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    ops = comparison.get("word_ops", ())
    if not isinstance(ops, (list, tuple)):
        return grouped
    for entry in ops:
        if not isinstance(entry, dict):
            continue
        try:
            lineno = int(entry.get("target_line", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lineno <= 0:
            continue
        line_ops = entry.get("ops", ())
        if not isinstance(line_ops, (list, tuple)):
            continue
        kept = [op for op in line_ops if isinstance(op, dict)]
        if kept:
            grouped.setdefault(lineno, []).extend(kept)
    return grouped


def _hunk_ranges(comparison: dict[str, Any]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    hunks = comparison.get("hunks", ())
    if not isinstance(hunks, (list, tuple)):
        return ranges
    for hunk in hunks:
        if not isinstance(hunk, dict):
            continue
        try:
            start = int(hunk.get("target_start", 0) or 0)
            end = int(hunk.get("target_end", 0) or 0)
        except (TypeError, ValueError):
            continue
        if start > 0 and end > start:
            ranges.append((start, end))
    return ranges


def _removal_anchors(comparison: dict[str, Any]) -> list[tuple[int, int]]:
    anchors: list[tuple[int, int]] = []
    raw = comparison.get("removal_anchors", ())
    if not isinstance(raw, (list, tuple)):
        return anchors
    for anchor in raw:
        if isinstance(anchor, dict):
            try:
                after = int(anchor.get("after_target_line", 0) or 0)
                removed = int(anchor.get("removed_count", 0) or 0)
            except (TypeError, ValueError):
                continue
        else:
            try:
                after = max(int(anchor), 0)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            removed = 0
        anchors.append((max(after, 0), max(removed, 0)))
    return sorted(anchors)


def _hunk_section_paths(comparison: dict[str, Any]) -> dict[int, list[str]]:
    paths: dict[int, list[str]] = {}
    hunks = comparison.get("hunks", ())
    if not isinstance(hunks, (list, tuple)):
        return paths
    for hunk in hunks:
        if not isinstance(hunk, dict):
            continue
        try:
            start = int(hunk.get("target_start", 0) or 0)
        except (TypeError, ValueError):
            continue
        sections = hunk.get("section_path", ())
        if isinstance(sections, str):
            sections = (sections,)
        if start > 0 and isinstance(sections, (list, tuple)) and sections:
            paths[start] = [str(section) for section in sections]
    return paths


def _render_word_line(
    ops: list[dict[str, Any]],
    line: str,
    *,
    insert_style: str | None = INSERT_STYLE,
    delete_style: str | None = DELETE_STYLE,
) -> Text:
    """Render one target line's word ops inline against *line*.

    Gaps between word tokens keep the target line's original spacing;
    delete spans carry their own removed text at their anchor position.
    Code fences need no special case: core already compares fence bodies
    line by line, so fence edits arrive here as ordinary line ops.
    """
    ordered = sorted(
        ops,
        key=lambda op: (
            _safe_int(op.get("start", 0)),
            _safe_int(op.get("end", 0)),
        ),
    )
    rendered = Text()
    if not line:
        for op in ordered:
            _append_op(rendered, op, "", 0, 0, insert_style, delete_style)
        return rendered
    cursor = 0
    for op in ordered:
        kind = str(op.get("kind", "equal") or "equal").lower()
        text = str(op.get("text", "") or "")
        start = min(_safe_int(op.get("start", 0)), len(line))
        end = min(_safe_int(op.get("end", 0)), len(line))
        if start > cursor:
            rendered.append(line[cursor:start])
        if kind in _INSERT_KINDS:
            rendered.append(text, style=insert_style)
        elif kind in _DELETE_KINDS:
            rendered.append(text, style=delete_style)
        else:
            rendered.append(text or line[start:end])
        cursor = max(cursor, end)
    if cursor < len(line):
        rendered.append(line[cursor:])
    return rendered


def _append_op(
    rendered: Text,
    op: dict[str, Any],
    line: str,
    cursor: int,
    line_length: int,
    insert_style: str | None,
    delete_style: str | None,
) -> None:
    kind = str(op.get("kind", "equal") or "equal").lower()
    text = str(op.get("text", "") or "")
    if kind in _INSERT_KINDS:
        rendered.append(text, style=insert_style)
    elif kind in _DELETE_KINDS:
        rendered.append(text, style=delete_style)
    else:
        rendered.append(text)


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def read_view_change_lines(comparison: dict[str, Any] | None) -> tuple[int, ...]:
    """Return 1-based target lines ``[``/``]`` should visit in read view.

    Changed lines come from word ops; removal anchors contribute the
    line following the deletion (clamped to the anchor line itself when
    the deletion trails the body).
    """
    inner = _comparison_of(comparison)
    lines: set[int] = set()
    for lineno in _word_ops_by_line(inner):
        lines.add(lineno)
    for mark in _line_marks(inner):
        lines.add(mark)
    anchors = _removal_anchors(inner)
    for after, _removed in anchors:
        lines.add(after if after <= 0 else after + 1)
    return tuple(sorted(line for line in lines if line > 0))


def _line_marks(comparison: dict[str, Any]) -> set[int]:
    marks: set[int] = set()
    raw = comparison.get("line_marks", ())
    if not isinstance(raw, (list, tuple)):
        return marks
    for mark in raw:
        if isinstance(mark, dict):
            lineno = _safe_int(mark.get("target_line", 0))
        else:
            lineno = _safe_int(mark)
        if lineno > 0:
            marks.add(lineno)
    return marks


def build_diff_body(
    comparison: dict[str, Any] | None,
    target_body: str,
    *,
    expanded: frozenset[int] | set[int] = frozenset(),
) -> _DiffBody:
    """Build the diff-view body for one version comparison.

    Changed target lines render with inline word ops; removal anchors
    render a red marker row; unchanged runs longer than twice the
    context collapse into ``┄ N unchanged lines · expand ┄`` fold
    labels (3 lines of context stay visible on each side). *expanded*
    holds fold indices that render in full instead.
    """
    inner = _comparison_of(comparison)
    unified = unified_diff_for_comparison(inner)
    ops_by_line = _word_ops_by_line(inner)
    anchors = _removal_anchors(inner)
    anchor_lines = {after for after, _removed in anchors}
    changed: set[int] = set(ops_by_line)
    for start, end in _hunk_ranges(inner):
        changed.update(range(start, end))
    target_lines = target_body.splitlines()
    total = len(target_lines)
    if not changed and not anchors:
        fallback = Text()
        block = _frontmatter_block(inner)
        if block.plain:
            fallback.append_text(block)
        if unified:
            fallback.append(unified if unified.endswith("\n") else unified + "\n")
        else:
            fallback.append("(no changes)\n", style=FOLD_STYLE)
        return _DiffBody(text=fallback, unified_diff=unified, empty=True)

    visible: set[int] = set()
    for lineno in changed | anchor_lines:
        for delta in range(-DIFF_CONTEXT_LINES, DIFF_CONTEXT_LINES + 1):
            candidate = lineno + delta
            if 1 <= candidate <= total:
                visible.add(candidate)
    # Anchor-at-zero (leading deletions) pins the head of the body.
    if 0 in anchor_lines:
        for candidate in range(1, min(total, DIFF_CONTEXT_LINES) + 1):
            visible.add(candidate)

    section_paths = _hunk_section_paths(inner)
    body = Text()
    block = _frontmatter_block(inner)
    # Diff-body line counter: every appended "\n" line bumps it, so the
    # value right after an append is that line's 1-based number.
    body_lines = 0
    change_lines: list[int] = []
    folds: list[_DiffFold] = []
    targets: list[AttachedTarget] = []
    if block.plain:
        body.append_text(block)
        body_lines += len(block.plain.splitlines())
        change_lines.extend(range(1, body_lines + 1))

    lineno = 1
    fold_index = 0
    while lineno <= total:
        if lineno not in visible:
            run_start = lineno
            while lineno <= total and lineno not in visible:
                lineno += 1
            run_end = lineno - 1
            hidden = run_end - run_start + 1
            if fold_index in expanded:
                for hidden_line in range(run_start, run_end + 1):
                    _append_target_line(
                        body,
                        target_lines[hidden_line - 1],
                        ops_by_line.get(hidden_line),
                    )
                    body.append("\n")
                    body_lines += 1
            else:
                label = _fold_label_text(hidden) + "\n"
                label_start = len(body.plain)
                token_offset = label.index(FOLD_TOKEN)
                body.append(label, style=FOLD_STYLE)
                body_lines += 1
                targets.append(
                    AttachedTarget(
                        kind=FOLD_TARGET_KIND,
                        target=fold_index,
                        start=label_start + token_offset,
                        end=label_start + token_offset + len(FOLD_TOKEN),
                        text=FOLD_TOKEN,
                    )
                )
                folds.append(
                    _DiffFold(index=fold_index, start_line=run_start, end_line=run_end)
                )
            fold_index += 1
            continue
        for path in section_paths.get(lineno, ()):
            body.append(f"§ {path}\n", style=SECTION_STYLE)
            body_lines += 1
            change_lines.append(body_lines)
        ops = ops_by_line.get(lineno)
        if ops is not None:
            body.append_text(_render_word_line(ops, target_lines[lineno - 1]))
            body.append("\n")
            body_lines += 1
            change_lines.append(body_lines)
        else:
            body.append(target_lines[lineno - 1] + "\n")
            body_lines += 1
        for after, removed in anchors:
            if after == lineno:
                noun = "line" if removed == 1 else "lines"
                body.append(f"╴ {removed} {noun} removed\n", style=REMOVAL_STYLE)
                body_lines += 1
                change_lines.append(body_lines)
        lineno += 1
    return _DiffBody(
        text=body,
        folds=tuple(folds),
        fold_targets=tuple(targets),
        change_lines=tuple(change_lines),
        unified_diff=unified,
    )


def _append_target_line(
    body: Text, line: str, ops: list[dict[str, Any]] | None
) -> None:
    if ops:
        body.append_text(_render_word_line(ops, line))
    else:
        body.append(line)


def _fold_label_text(hidden_count: int) -> str:
    """Return the fold label for *hidden_count* unchanged lines."""
    noun = "line" if hidden_count == 1 else "lines"
    return f"┄┄ {hidden_count} unchanged {noun} · {FOLD_TOKEN} ┄┄"


def diff_endpoints(
    *,
    ordinal: int,
    visible_ordinals: tuple[int, ...] = (),
    dirty: bool = False,
    compare_base: int | None = None,
) -> tuple[int, int] | None:
    """Return the ``(base, target)`` comparison ordinals for a diff view.

    Committed versions compare against their parent (or an explicit
    *compare_base*, which the timeline picker sets in a later phase);
    ordinal 1 falls back to the empty-base comparison. A dirty ``now``
    compares the worktree (target 0) against the newest committed
    version; a clean ``now`` shows the newest version's own change.
    ``None`` means there is nothing to compare yet.
    """
    if ordinal > 0:
        if compare_base is not None:
            return (compare_base, ordinal)
        return (ordinal - 1, ordinal)
    if not visible_ordinals:
        return None
    newest = max(visible_ordinals)
    if dirty:
        return (newest, 0)
    return (newest - 1, newest)


__all__ = [
    "DIFF_CONTEXT_LINES",
    "DELETE_STYLE",
    "FOLD_TARGET_KIND",
    "FOLD_TOKEN",
    "INSERT_STYLE",
    "build_diff_body",
    "diff_endpoints",
    "read_view_change_lines",
    "unified_diff_for_comparison",
]
