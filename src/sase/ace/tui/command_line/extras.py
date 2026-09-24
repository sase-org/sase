"""Empty state, doc peek, history search, and marked rows for the ``:`` panel.

This is the completion-extras phase (``sase-17x.10``) of the Command Line
epic. Everything here is Textual-free and synchronous so the panel and the
tests share the same code path:

- empty state: RECENT history rows plus derived ``FOR <selection>`` rows,
  shown when the input line is empty;
- doc peek: a right-hand help card for the highlighted subcommand or
  option, shown only on wide terminals;
- ``ctrl+r`` history search: fuzzy history ranking through the shared Rust
  matcher;
- marked rows: a first ``‹N marked›`` row that fills variadic slots;
- provider health: the ``⚠ <kind> unavailable`` footer note.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _local_now() -> datetime:
    """Return now in the configured zone, falling back to the system zone."""
    try:
        from sase.core.time import get_timezone, system_timezone
    except Exception:  # noqa: BLE001 - Rust binding may be missing.
        return datetime.now(UTC)
    try:
        return datetime.now(get_timezone())
    except Exception:  # noqa: BLE001 - bad configured zone; use system zone.
        return datetime.now(system_timezone())


#: Minimum terminal width (columns) for the doc-peek card. Narrower
#: terminals collapse the help into the signature row.
DOC_PEEK_MIN_WIDTH = 140

#: Maximum RECENT rows in the empty state.
EMPTY_STATE_RECENT_LIMIT = 5

#: Maximum derived ``FOR <selection>`` rows in the empty state.
FOR_SELECTION_LIMIT = 5

#: Cap on help-tree nodes visited while deriving ``FOR`` rows.
_LEAF_WALK_NODE_CAP = 5000

#: Positional ``nargs`` shapes that accept more than one value.
_VARIADIC_NARGS = frozenset({"+", "*", "..."})

#: Completion-item badges the doc peek treats as a subcommand row.
_SUBCOMMAND_BADGES = frozenset({"cmd", "group"})

__all__ = [
    "DOC_PEEK_MIN_WIDTH",
    "EMPTY_STATE_RECENT_LIMIT",
    "FOR_SELECTION_LIMIT",
    "doc_peek_for_highlight",
    "doc_peek_visible",
    "empty_state_hint",
    "empty_state_rows",
    "marked_insert_text",
    "marked_values_for_kind",
    "provider_unavailable_note",
    "rank_history_entries",
    "relative_age",
    "selected_entity_kind",
    "slot_is_variadic",
]


@dataclass(frozen=True, slots=True)
class _EmptyStateRow:
    """One selectable row in the empty-state popup."""

    #: Text inserted into the input when the row is accepted (never run).
    insert_text: str
    #: Row label shown in the popup.
    display: str
    #: Trailing detail (relative age, exit mark, or derivation note).
    description: str = ""
    #: Popup badge column (``"recent"`` or ``"suggest"``).
    badge: str = ""

    def to_item(self) -> dict[str, Any]:
        """Render as a completion-popup item dict."""
        return {
            "insert_text": self.insert_text,
            "display": self.display,
            "description": self.description,
            "badge": self.badge,
            "source": "history",
            "match_runs": [],
            "selected": False,
        }


def relative_age(last_used: str, *, now: datetime | None = None) -> str:
    """Format a history ``last_used`` stamp as ``"2h ago"``; ``""`` if unknown."""
    stamp = (last_used or "").strip()
    moment: datetime | None = None
    if stamp:
        try:
            moment = datetime.strptime(stamp, "%y%m%d_%H%M%S")
        except ValueError:
            moment = None
        if moment is None:
            try:
                moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                moment = None
    if moment is None:
        return ""
    reference = now or _local_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=reference.tzinfo)
    elapsed = int((reference - moment).total_seconds())
    if elapsed < 0:
        return "just now"
    if elapsed < 60:
        return f"{elapsed}s ago"
    if elapsed < 3600:
        return f"{elapsed // 60}m ago"
    if elapsed < 86400:
        return f"{elapsed // 3600}h ago"
    return f"{elapsed // 86400}d ago"


def _exit_mark(last_exit: int | None) -> str:
    if last_exit is None:
        return ""
    if last_exit == 0:
        return "✓"
    return f"✗ {last_exit}"


def _recent_rows(
    entries: list[Any], *, limit: int = EMPTY_STATE_RECENT_LIMIT
) -> list[_EmptyStateRow]:
    """Return the newest history entries as empty-state RECENT rows."""
    rows: list[_EmptyStateRow] = []
    for entry in entries[: max(0, limit)]:
        line = str(getattr(entry, "line", "") or "")
        if not line.strip():
            continue
        age = relative_age(str(getattr(entry, "last_used", "") or ""))
        mark = _exit_mark(getattr(entry, "last_exit", None))
        detail = "  ".join(part for part in (age, mark) if part)
        rows.append(
            _EmptyStateRow(
                insert_text=line, display=line, description=detail, badge="recent"
            )
        )
    return rows


def selected_entity_kind(app: Any) -> str | None:
    """Return the selected entity's value kind (``"agent"``/``"patch"``).

    Reads through ``extract_command_context`` so the panel and the
    palette agree on what "selected" means; every step is defensive.
    Axe items are agent sessions, so they map to ``"agent"``.
    """
    try:
        from sase.ace.tui.commands.context import extract_command_context

        context = extract_command_context(app)
    except Exception:  # noqa: BLE001 - selection is best effort.
        return None
    if getattr(context, "agent", None) is not None:
        return "agent"
    if getattr(context, "patch", None) is not None:
        return "patch"
    if getattr(context, "axe_item", None) is not None:
        return "agent"
    return None


def _first_required_positional_kind(help_view: dict[str, Any] | None) -> str | None:
    """Return the first required positional's value kind in *help_view*."""
    if not help_view:
        return None
    for positional in help_view.get("positionals") or []:
        if not positional.get("required"):
            continue
        kind = positional.get("value_kind")
        return str(kind) if kind else None
    return None


def _iter_leaf_paths(
    help_lookup: Callable[[list[str]], dict[str, Any] | None],
) -> list[list[str]]:
    """Walk the help tree breadth-first; return paths with no subcommands."""
    root = help_lookup([])
    if not root:
        return []
    leaves: list[list[str]] = []
    queue: list[list[str]] = [
        [str(child.get("name", ""))]
        for child in root.get("children") or []
        if str(child.get("name", ""))
    ]
    visited: set[tuple[str, ...]] = set()
    while queue and len(visited) < _LEAF_WALK_NODE_CAP:
        path = queue.pop(0)
        key = tuple(path)
        if key in visited:
            continue
        visited.add(key)
        try:
            view = help_lookup(path)
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            continue
        if not view:
            continue
        children = [str(child.get("name", "")) for child in view.get("children") or []]
        children = [name for name in children if name]
        if not children:
            leaves.append(path)
        else:
            queue.extend(path + [name] for name in children)
    return leaves


def _leaf_usage(path: list[str], entries: list[Any]) -> int:
    command = " ".join(path)
    prefix = command + " "
    count = 0
    for entry in entries:
        line = str(getattr(entry, "line", "") or "")
        if line == command or line.startswith(prefix):
            count += 1
    return count


def _for_selection_rows(
    help_lookup: Callable[[list[str]], dict[str, Any] | None],
    selected_kind: str | None,
    selected_value: str | None,
    entries: list[Any],
    *,
    limit: int = FOR_SELECTION_LIMIT,
) -> list[_EmptyStateRow]:
    """Derive ``FOR <selection>`` rows: leaves taking the selected kind.

    Lists leaf commands whose first required positional's kind matches
    *selected_kind*, ranked by history usage (most-used first, path order
    breaks ties). Returns ``[]`` without a selection or a value.
    """
    if not selected_kind or not (selected_value or "").strip():
        return []
    try:
        leaves = _iter_leaf_paths(help_lookup)
    except Exception:  # noqa: BLE001 - derivation never breaks the panel.
        return []
    ranked: list[tuple[int, list[str]]] = []
    for path in leaves:
        try:
            view = help_lookup(path)
        except Exception:  # noqa: BLE001 - one bad node skips one leaf.
            continue
        if _first_required_positional_kind(view) != selected_kind:
            continue
        ranked.append((_leaf_usage(path, entries), path))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    rows = [
        _EmptyStateRow(
            insert_text=f"{' '.join(path)} {selected_value}",
            display=f"{' '.join(path)} {selected_value}",
            badge="suggest",
        )
        for _, path in ranked[: max(0, limit)]
    ]
    return rows


def empty_state_rows(
    help_lookup: Callable[[list[str]], dict[str, Any] | None],
    entries: list[Any],
    *,
    selected_kind: str | None,
    selected_value: str | None,
) -> list[_EmptyStateRow]:
    """Return the full empty-state row list: RECENT first, then FOR rows."""
    return _recent_rows(entries) + _for_selection_rows(
        help_lookup, selected_kind, selected_value, entries
    )


def empty_state_hint(command_count: int | None = None) -> str:
    """Return the hint row shown with the empty state."""
    if command_count is None:
        return "type to search · ⇥ complete · ; Command Palette"
    return f"{command_count} commands · type to search · ⇥ complete · ; Command Palette"


def doc_peek_visible(width: int | None) -> bool:
    """Return True when *width* fits the right-hand doc-peek card."""
    if width is None:
        return False
    try:
        return int(width) >= DOC_PEEK_MIN_WIDTH
    except (TypeError, ValueError):
        return False


def _doc_peek_text(
    help_view: dict[str, Any] | None,
    *,
    name: str,
    option_strings: list[str] | None = None,
) -> str:
    """Render the doc-peek card: summary, usage, arguments, choices, defaults."""
    if not help_view:
        return ""
    lines: list[str] = [name]
    summary = str(help_view.get("summary", "") or "")
    if summary:
        lines.append(summary)
    usage = str(help_view.get("usage", "") or "")
    if usage:
        lines.append(usage)
    if option_strings is not None:
        wanted = {item.rstrip("=") for item in option_strings}
        options = [
            option
            for option in help_view.get("options") or []
            if wanted.intersection(
                str(item).rstrip("=") for item in option.get("strings", [])
            )
        ]
        for option in options:
            lines.append(_option_detail(option))
    else:
        for positional in help_view.get("positionals") or []:
            parts = [str(positional.get("metavar", "") or positional.get("dest", ""))]
            choices = positional.get("choices") or []
            if choices:
                parts.append("choices: " + ", ".join(str(c) for c in choices))
            if positional.get("required"):
                parts.append("required")
            lines.append(" ".join(part for part in parts if part))
        for option in help_view.get("options") or []:
            lines.append(_option_detail(option))
        children = [str(c.get("name", "")) for c in help_view.get("children") or []]
        children = [name for name in children if name]
        if children:
            lines.append("subcommands: " + ", ".join(children[:12]))
    return "\n".join(line for line in lines if line)


def _option_detail(option: dict[str, Any]) -> str:
    strings = [str(item) for item in option.get("strings", [])]
    label = ", ".join(strings) if strings else str(option.get("dest", ""))
    parts = [label]
    summary = str(option.get("summary", "") or "")
    if summary:
        parts.append(f"— {summary}")
    choices = option.get("choices") or []
    if choices:
        parts.append("choices: " + ", ".join(str(choice) for choice in choices))
    default = option.get("default")
    if default is not None:
        parts.append(f"default: {default}")
    return " ".join(parts)


def doc_peek_for_highlight(
    *,
    completion_kind: str,
    highlighted: dict[str, Any] | None,
    path: list[str],
    help_lookup: Callable[[list[str]], dict[str, Any] | None],
) -> str:
    """Return the doc-peek card for the highlighted row, or ``""``.

    Only subcommand rows (badges ``cmd``/``group``) and option rows in an
    ``option_name`` slot produce a card; value rows collapse into the
    signature row.
    """
    if not highlighted:
        return ""
    if completion_kind == "subcommand" or str(highlighted.get("badge", "")) in (
        _SUBCOMMAND_BADGES
    ):
        display = str(highlighted.get("display", "") or "").strip()
        if not display:
            return ""
        try:
            parent = help_lookup(list(path))
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            return ""
        canonical = display
        for child in (parent or {}).get("children") or []:
            names = [str(child.get("name", ""))] + [
                str(alias) for alias in child.get("aliases", [])
            ]
            if display in names:
                canonical = str(child.get("name", ""))
                break
        try:
            view = help_lookup([*path, canonical])
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            return ""
        return _doc_peek_text(view, name=f"{' '.join([*path, canonical])}".strip())
    if completion_kind == "option_name":
        token = str(highlighted.get("insert_text", "") or "").strip()
        if not token.startswith("-"):
            return ""
        try:
            view = help_lookup(list(path))
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            return ""
        if not view:
            return ""
        for option in view.get("options") or []:
            strings = [str(item) for item in option.get("strings", [])]
            if token in strings or token.rstrip("=") in [
                item.rstrip("=") for item in strings
            ]:
                return _doc_peek_text(view, name=token, option_strings=strings)
    return ""


@dataclass
class _RankedHistoryEntry:
    """One history entry ranked by the ``ctrl+r`` fuzzy search."""

    line: str
    match_runs: list[list[int]] = field(default_factory=list)


def rank_history_entries(query: str, entries: list[Any]) -> list[_RankedHistoryEntry]:
    """Rank history lines against *query* with the shared Rust fuzzy matcher.

    Entries that do not fuzzy-match are dropped; ties break by recency
    (entries are newest-first).
    """
    from sase.core.fuzzy_facade import fuzzy_match, fuzzy_sort_key

    needle = (query or "").strip()
    if not needle:
        return [
            _RankedHistoryEntry(line=str(getattr(e, "line", "") or ""))
            for e in entries
            if str(getattr(e, "line", "") or "").strip()
        ]
    seen: set[str] = set()
    scored: list[tuple[tuple[int, int, int, str, str], _RankedHistoryEntry]] = []
    for entry in entries:
        line = str(getattr(entry, "line", "") or "")
        if not line.strip() or line in seen:
            continue
        seen.add(line)
        try:
            match = fuzzy_match(needle, line)
        except Exception:  # noqa: BLE001 - ranking never breaks the panel.
            continue
        if match is None:
            continue
        scored.append(
            (
                fuzzy_sort_key(match, line),
                _RankedHistoryEntry(
                    line=line,
                    match_runs=[[s, e] for s, e in match.runs],
                ),
            )
        )
    scored.sort(key=lambda item: item[0])
    return [ranked for _, ranked in scored]


def slot_is_variadic(
    slot: dict[str, Any] | None,
    help_lookup: Callable[[list[str]], dict[str, Any] | None],
    path: list[str],
) -> bool:
    """Return True when the active slot accepts more than one value."""
    if not slot:
        return False
    kind = str(slot.get("kind", "") or "")
    dest = str(slot.get("dest", "") or "")
    try:
        view = help_lookup(list(path))
    except Exception:  # noqa: BLE001 - help lookup is best effort.
        return False
    if not view:
        return False
    if kind == "option_value" and dest:
        for option in view.get("options") or []:
            if str(option.get("dest", "")) == dest:
                return bool(option.get("repeatable"))
        return False
    if kind in ("positional", "remainder"):
        positionals = view.get("positionals") or []
        if kind == "remainder":
            return True
        target = None
        if dest:
            target = next(
                (p for p in positionals if str(p.get("dest", "")) == dest), None
            )
        else:
            target = next(
                (
                    p
                    for p in positionals
                    if str(p.get("nargs", "") or "") in _VARIADIC_NARGS
                    or p.get("is_remainder")
                ),
                None,
            )
        if target is None:
            return False
        return str(target.get("nargs", "") or "") in _VARIADIC_NARGS or bool(
            target.get("is_remainder")
        )
    return False


#: Pane keys holding user-marked rows, by command-line value kind.
_MARKED_PANE_BY_KIND = {
    "agent": "agents",
    "patch": "patches",
    "bead": "beads",
}


def marked_values_for_kind(app: Any, value_kind: str | None) -> list[str]:
    """Return the TUI-marked entity values for *value_kind*, if any."""
    pane_id = _MARKED_PANE_BY_KIND.get(str(value_kind or ""))
    if pane_id is None:
        return []
    try:
        marks = getattr(app, "_artifacts_marked_targets", {}).get(pane_id, set())
    except Exception:  # noqa: BLE001 - marks are best effort.
        return []
    values: list[str] = []
    try:
        targets = list(marks)
    except TypeError:
        return []
    for target in targets:
        if getattr(target, "pane_id", pane_id) != pane_id:
            continue
        parts = getattr(target, "parts", ())
        if parts and str(parts[0]) and str(parts[0]) not in values:
            values.append(str(parts[0]))
    return sorted(values)


def marked_insert_text(values: list[str]) -> str:
    """Quote-join marked values into one slot-filling insert (trailing space)."""
    quoted = " ".join(
        value if _is_bare_word(value) else shlex.quote(value) for value in values
    )
    return f"{quoted} " if quoted else ""


def _is_bare_word(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in "-_./:@" for char in value)


def provider_unavailable_note(value_kind: str | None) -> str:
    """Return the subtle footer note for an empty or failed provider."""
    return f"⚠ {value_kind or 'value'} unavailable"
