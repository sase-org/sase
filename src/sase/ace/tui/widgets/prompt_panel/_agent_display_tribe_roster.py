"""Member-roster adaptation for tribe detail documents."""

from __future__ import annotations

from rich.text import Text

from ...models.agent_tribe_summary import AgentTribeSummarySnapshot
from ._agent_display_tribe_common import FIELD_LABEL_STYLE, TRIBE_IDENTITY_COLOR
from ._member_roster import (
    MEMBER_ENTRY_CURSOR_GLYPH,
    MEMBER_ENTRY_CURSOR_STYLE,
    MemberRosterChild,
    MemberRosterEntry,
    MemberRosterStatusCounts,
)


def tribe_roster_entries(
    snapshot: AgentTribeSummarySnapshot,
) -> tuple[MemberRosterEntry, ...]:
    entries: list[MemberRosterEntry] = []
    for unit in snapshot.units:
        counts = unit.status_counts
        entries.append(
            MemberRosterEntry(
                identity=unit.identity,
                presented_name=unit.presented_name,
                label=unit.label,
                kind=unit.kind,
                status=unit.status,
                effective_bucket=unit.status_bucket,
                model=unit.model,
                duration=unit.duration,
                digest=unit.digest,
                children=tuple(
                    MemberRosterChild(
                        label=child.label,
                        kind=child.kind,
                        status=child.status,
                        effective_bucket=child.effective_bucket,
                        model=child.model,
                        duration=child.duration,
                        digest=child.digest,
                        is_marked=child.is_marked,
                        is_unread=child.is_unread,
                    )
                    for child in unit.children
                ),
                status_counts=(
                    MemberRosterStatusCounts(
                        stopped=counts.stopped,
                        running=counts.running,
                        queued=counts.queued,
                        waiting=counts.waiting,
                        failed=counts.failed,
                        unread=counts.unread,
                        done=counts.done,
                    )
                    if counts is not None
                    else None
                ),
                is_marked=unit.is_marked,
                is_unread=unit.is_unread,
                is_entry_target=(
                    snapshot.entry_target is not None
                    and unit.identity == snapshot.entry_target.unit_identity
                ),
            )
        )
    return tuple(entries)


def entry_target_heading_suffix(snapshot: AgentTribeSummarySnapshot) -> Text | None:
    """Build the panel-entry affordance for an expanded tribe roster."""
    target = snapshot.entry_target
    if snapshot.panel_collapsed or target is None:
        return None
    suffix = Text()
    suffix.append(" · ", style="dim")
    suffix.append(target.key_label, style=FIELD_LABEL_STYLE)
    suffix.append(" ")
    suffix.append(
        MEMBER_ENTRY_CURSOR_GLYPH + " ",
        style=MEMBER_ENTRY_CURSOR_STYLE,
    )
    suffix.append(target.label, style=f"bold {TRIBE_IDENTITY_COLOR}")
    return suffix
