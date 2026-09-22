"""Agent-scoped touch listing for ``sase bead touched``.

The reduction itself lives in ``sase-core`` and is surfaced through
:mod:`sase.core.bead_touch_index_facade`; this module owns only the CLI
presentation: per-bead folding, newest-touch-first ordering, verb-chip
formatting, the shared glyph vocabulary, and the compact and JSON
renderings. Durable index rows merge with the legacy, no-longer-written
``bead_views.jsonl`` view log and audited ``bead:`` artifact reads so the
rows agree with the panel row for row for touched beads. ``read`` comes
from ``sase bead read`` / ``sase artifact read bead:`` with reasons.
Agents are refused at ``show``; ``viewed`` rows predate that guard. The
index is a derived cache, so a missing index lists nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.bead.cli_dep_render import resolve_color, styled
from sase.bead.touch_glyphs import TOUCH_VERB_ORDER, touch_glyph
from sase.bead_time_presentation import BEAD_TIME_CLI_STYLE, bead_age_label

TOUCH_VERBS = TOUCH_VERB_ORDER

TOUCH_VERB_SET = frozenset(TOUCH_VERBS)

_BEAD_ID_STYLE = "\x1b[1;36m"


def _touch_glyph(verbs: dict[str, int]) -> str:
    """Return the row's single strongest verb glyph via shared vocabulary."""
    return touch_glyph(verbs)


def _format_verb_chips(verbs: dict[str, int]) -> str:
    """Format verb counts as ``created · noted ×2`` in fixed verb order."""
    chips = []
    for verb in TOUCH_VERBS:
        count = verbs.get(verb, 0)
        if count <= 0:
            continue
        chips.append(f"{verb} ×{count}" if count > 1 else verb)
    return " · ".join(chips)


def _parse_order_moment(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _order_touches_newest_first(touches: list[Any]) -> list[Any]:
    """Order folded beads newest-touch-first, undated rows last."""

    def _rank(touch: Any) -> tuple[float, str]:
        moment = _parse_order_moment(getattr(touch, "last_at", "") or "")
        epoch = moment.timestamp() if moment is not None else float("-inf")
        return (-epoch, str(getattr(touch, "bead_id", "") or ""))

    return sorted(touches, key=_rank)


def _filter_touches_by_verbs(
    touches: list[Any], verbs: list[str] | tuple[str, ...]
) -> list[Any]:
    """Keep folded beads carrying at least one of *verbs*."""
    wanted = set(verbs)
    return [touch for touch in touches if wanted & set(touch.verbs)]


def _resolve_agent_names(agent: str, identity: Any) -> tuple[str, str]:
    """Return the ``(globalized, local)`` spellings of the queried agent."""
    from sase.core.agent_identity_facade import globalize_owned_agent_name

    raw = agent.strip()
    try:
        return globalize_owned_agent_name(raw, identity), raw
    except Exception:  # noqa: BLE001 - fall back to the raw spelling.
        return raw, raw


def _load_view_touches(
    *,
    globalized_name: str,
    local_name: str | None,
    identity: Any,
) -> list[Any]:
    """Return the agent's synthesized ``viewed`` rows, or ``[]`` on any miss."""
    try:
        from sase.bead.bead_views import (
            read_bead_view_events,
            view_touches_for_agent,
        )
        from sase.core.bead_touch_index_facade import resolve_touch_index_project

        project = resolve_touch_index_project(cwd=Path.cwd())
        if not project:
            return []
        events = read_bead_view_events(project=project)
    except Exception:  # noqa: BLE001 - views are best-effort enrichment.
        return []
    try:
        return list(
            view_touches_for_agent(
                events,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            )
        )
    except Exception:  # noqa: BLE001 - views never break the listing.
        return []


def _load_read_touches(
    *,
    globalized_name: str,
    local_name: str | None,
    identity: Any,
) -> list[Any]:
    """Fold the agent's audited ``bead:`` reads into ``read`` touch rows."""
    try:
        from sase.artifact_read_log import read_artifact_read_events
        from sase.core.bead_touch_index_facade import (
            BeadTouch,
            canonical_bead_touch_id,
            resolve_touch_index_project,
            touch_matches_agent,
        )

        project = resolve_touch_index_project(cwd=Path.cwd())
        if not project:
            return []
        events = read_artifact_read_events(project=project)
    except Exception:  # noqa: BLE001 - reads are best-effort enrichment.
        return []
    rows: list[Any] = []
    for event in events:
        try:
            ref = str(getattr(event, "ref", "") or "").strip()
            if not ref.startswith("bead:"):
                continue
            bead_id = canonical_bead_touch_id(ref)
            if not bead_id:
                continue
            if not touch_matches_agent(
                str(getattr(event, "agent_name", "") or ""),
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            ):
                continue
            timestamp = str(getattr(event, "timestamp", "") or "")
            rows.append(
                BeadTouch(
                    actor=str(getattr(event, "agent_name", "") or ""),
                    bead_id=bead_id,
                    verbs={"read": 1},
                    first_at=timestamp,
                    last_at=timestamp,
                    read_reasons=(str(getattr(event, "reason", "") or ""),),
                )
            )
        except Exception:  # noqa: BLE001 - one bad read row never breaks listing.
            continue
    return rows


def handle_bead_touched(args: argparse.Namespace) -> None:
    """List the beads one agent touched, newest touch first."""
    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.core.bead_touch_index_facade import (
        FoldedBeadTouch,
        fold_touches_per_bead,
        merge_view_touches,
        query_touches_for_agent,
        touch_index_path,
    )

    agent = str(getattr(args, "agent", "") or "").strip()
    if not agent:
        print("Error: agent name is required", file=sys.stderr)
        sys.exit(2)
    verbs = list(getattr(args, "verb", None) or [])
    unknown = [verb for verb in verbs if verb not in TOUCH_VERB_SET]
    if unknown:
        print(
            "Error: unknown verb(s): "
            + ", ".join(unknown)
            + f" (choose from: {', '.join(TOUCH_VERBS)})",
            file=sys.stderr,
        )
        sys.exit(2)
    limit = getattr(args, "limit", None)

    identity = AgentIdentitySnapshot.current()
    globalized_name, local_name = _resolve_agent_names(agent, identity)
    try:
        index_path = touch_index_path(cwd=Path.cwd())
    except Exception as exc:  # noqa: BLE001 - report unresolvable projects cleanly.
        print(f"sase bead touched: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        query = query_touches_for_agent(
            index_path,
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
        durable = list(query.touches)
        views = _load_view_touches(
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
        reads = _load_read_touches(
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
        combined = list(merge_view_touches(merge_view_touches(durable, views), reads))
        rows: list[FoldedBeadTouch] = fold_touches_per_bead(combined)
        generation = query.generation
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a read-only query never tracebacks.
        print(f"sase bead touched: {exc}", file=sys.stderr)
        sys.exit(1)

    rows = _order_touches_newest_first(rows)
    if verbs:
        rows = _filter_touches_by_verbs(rows, verbs)
    matched = len(rows)
    if limit:
        rows = rows[:limit]

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "agent": agent,
                    "generation": generation,
                    "total": matched,
                    "touches": [_touch_to_dict(touch) for touch in rows],
                },
                indent=2,
            )
        )
        return

    use_color = resolve_color("auto")
    if not rows:
        print(f"No beads touched by {agent}.")
        return
    for touch in rows:
        print(_render_touch_row(touch, use_color=use_color))
        reasons = list(getattr(touch, "read_reasons", ()) or ())
        if reasons:
            print(f"  ↳ {reasons[0]}")
    if limit and matched > len(rows):
        print(f"… +{matched - len(rows)} more")


def _touch_to_dict(touch: Any) -> dict[str, Any]:
    return {
        "bead_id": touch.bead_id,
        "title": touch.title,
        "issue_type": touch.issue_type,
        "status": touch.status,
        "verbs": dict(touch.verbs),
        "first_at": touch.first_at,
        "last_at": touch.last_at,
        "actors": list(touch.actors),
        "read_reasons": list(getattr(touch, "read_reasons", ()) or ()),
    }


def _render_touch_row(touch: Any, *, use_color: bool) -> str:
    verbs = dict(getattr(touch, "verbs", {}) or {})
    head = styled(f"{_touch_glyph(verbs)} {touch.bead_id}", _BEAD_ID_STYLE, use_color)
    chips = _format_verb_chips(verbs)
    parts = [head, chips] if chips else [head]
    title = str(getattr(touch, "title", "") or "")
    if title:
        parts.append(title)
    row = " · ".join(parts)
    age = bead_age_label(getattr(touch, "last_at", "") or "")
    if age:
        row += f"  {styled(f'⧖ {age}', BEAD_TIME_CLI_STYLE, use_color)}"
    return row


__all__ = [
    "TOUCH_VERBS",
    "TOUCH_VERB_SET",
    "handle_bead_touched",
]
