"""Shared numbered member-roster rendering."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from rich.style import Style as RichStyle
from rich.text import Text

from sase.ace.tui.models._agent_clan_sections import ClanMemberDigest
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MEMBER_ROSTER_LIMIT,
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterChild,
    MemberRosterEntry,
    append_member_roster,
    merged_member_jump_map,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)

_ACCENT = "#D75FFF"


def _identity(index: int) -> tuple[AgentType, str, str | None]:
    return (AgentType.RUNNING, f"research.member-{index}", f"suffix-{index}")


def _entry(
    index: int,
    *,
    digest: ClanMemberDigest | None = None,
    children: tuple[MemberRosterChild, ...] = (),
) -> MemberRosterEntry:
    return MemberRosterEntry(
        identity=_identity(index),
        presented_name=f"research.member-{index}",
        label=f".member-{index}",
        kind="agent",
        status="RUNNING",
        model="gpt-5",
        duration="1m",
        digest=digest,
        children=children,
    )


def _render(count: int) -> tuple[Text, MemberJumpMap]:
    text = Text()
    jump_map = append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "clan:research", "generation"),
        entries=tuple(_entry(index) for index in range(count)),
        title="CLAN MEMBERS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
    )
    return text, jump_map


def _section_ids(text: Text) -> list[str]:
    section_ids: list[str] = []
    for span in text.spans:
        style = span.style
        if not isinstance(style, RichStyle) or not style.meta:
            continue
        section_id = style.meta.get(SECTION_MARKER_META_KEY)
        if isinstance(section_id, str) and section_id not in section_ids:
            section_ids.append(section_id)
    return section_ids


@pytest.mark.parametrize(
    ("count", "first_number", "last_number"),
    (
        (1, "0", "0"),
        (10, "0", "9"),
        (11, "00", "10"),
        (100, "00", "99"),
    ),
)
def test_numbering_regimes_and_jump_targets(
    count: int,
    first_number: str,
    last_number: str,
) -> None:
    text, jump_map = _render(count)

    assert f"▸ ❖ CLAN MEMBERS · {count}\n" in text.plain
    assert f" {first_number}  .member-0" in text.plain
    assert f" {last_number}  .member-{count - 1}" in text.plain
    assert tuple(target.number for target in jump_map.targets) == tuple(
        f"{index:0{1 if count <= 10 else 2}d}" for index in range(count)
    )
    assert tuple(target.member_identity for target in jump_map.targets) == tuple(
        _identity(index) for index in range(count)
    )
    assert all(target.kind == "agent" for target in jump_map.targets)
    assert "not numbered" not in text.plain


def test_roster_truncates_after_one_hundred_numbered_members() -> None:
    text, jump_map = _render(150)

    assert len(jump_map.targets) == MEMBER_ROSTER_LIMIT
    assert jump_map.targets[-1].number == "99"
    assert " 99  .member-99" in text.plain
    assert ".member-100" not in text.plain
    assert "… +50 more members (not numbered)\n" in text.plain


def test_empty_roster_omits_heading_and_publishes_no_targets() -> None:
    text, jump_map = _render(0)

    assert text.plain == ""
    assert jump_map.targets == ()


def test_effective_bucket_overrides_raw_status_glyph() -> None:
    entry = MemberRosterEntry(
        identity=_identity(0),
        presented_name="research.member-0",
        label=".member-0",
        kind="agent",
        status="TALE APPROVED",
        effective_bucket="Done",
        model="gpt-5",
        duration="1m",
    )
    text = Text()

    append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "clan:research", "generation"),
        entries=(entry,),
        title="CLAN MEMBERS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
    )

    assert "✓ TALE APPROVED" in text.plain


def test_member_override_inherits_roster_then_overrides_it() -> None:
    digest = ClanMemberDigest(
        identity=_identity(0),
        label=".member-0",
        status="RUNNING",
        model="gpt-5",
        family_depth=0,
        family_name=None,
        activity="reviewing patch",
        waiting=("for peer",),
        retry=("1/3",),
        workspace_num=7,
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        run_start_time=datetime(2026, 7, 18, 12, 1, 0),
        stop_time=None,
        attempt_count=2,
    )
    child_digest = ClanMemberDigest(
        identity=_identity(1),
        label="--code",
        status="RUNNING",
        model="gpt-5",
        family_depth=1,
        family_name="research.member-0",
        activity="writing tests",
        waiting=(),
        retry=(),
        workspace_num=8,
        start_time=None,
        run_start_time=None,
        stop_time=None,
        attempt_count=1,
    )
    child = MemberRosterChild(
        label="--code",
        kind="agent",
        status="RUNNING",
        model="gpt-5",
        duration="30s",
        digest=child_digest,
    )
    entry = _entry(0, digest=digest, children=(child,))
    anchor_id = f"member:{entry.presented_name}"

    def render(overrides: dict[str, FoldLevel]) -> str:
        text = Text()
        append_member_roster(
            text,
            container_identity=(AgentType.RUNNING, "clan:research", "generation"),
            entries=(entry,),
            title="CLAN MEMBERS",
            accent=_ACCENT,
            panel_level=FoldLevel.COLLAPSED,
            section_fold_overrides=overrides,
        )
        return text.plain

    inherited_expanded = render({"members": FoldLevel.EXPANDED})
    member_collapsed = render(
        {"members": FoldLevel.EXPANDED, anchor_id: FoldLevel.COLLAPSED}
    )
    member_expanded = render({anchor_id: FoldLevel.EXPANDED})
    member_full = render({anchor_id: FoldLevel.FULLY_EXPANDED})

    assert "reviewing patch" in inherited_expanded
    assert "writing tests" in inherited_expanded
    assert "reviewing patch" not in member_collapsed
    assert "writing tests" not in member_collapsed
    assert "reviewing patch · wait for peer · retry 1/3" in member_expanded
    assert "ws 7" not in member_expanded
    assert "ws 7" in member_full
    assert "start 2026-07-18 12:00:00" in member_full
    assert "2 attempts" in member_full
    assert "ws 8" in member_full


def test_roster_and_each_numbered_entry_publish_section_anchors() -> None:
    text, _jump_map = _render(2)

    assert _section_ids(text) == [
        "members",
        "member:research.member-0",
        "member:research.member-1",
    ]


@pytest.mark.parametrize(
    ("counts", "expected_numbers"),
    (
        ((2, 3), ("0", "1", "2", "3", "4")),
        ((5, 6), tuple(f"{index:02d}" for index in range(11))),
    ),
)
def test_shared_numbering_is_contiguous_across_rosters(
    counts: tuple[int, int],
    expected_numbers: tuple[str, ...],
) -> None:
    numbering = MemberJumpNumbering(total=sum(counts))
    maps: list[MemberJumpMap] = []
    texts: list[Text] = []
    entry_offset = 0

    for count in counts:
        text = Text()
        maps.append(
            append_member_roster(
                text,
                container_identity=(
                    AgentType.RUNNING,
                    "family:research",
                    "generation",
                ),
                entries=tuple(
                    _entry(index) for index in range(entry_offset, entry_offset + count)
                ),
                title="MEMBERS",
                accent=_ACCENT,
                panel_level=FoldLevel.COLLAPSED,
                numbering=numbering,
            )
        )
        texts.append(text)
        entry_offset += count

    actual_numbers = tuple(
        target.number for jump_map in maps for target in jump_map.targets
    )
    assert actual_numbers == expected_numbers
    rendered = texts[0].plain + texts[1].plain
    assert all(f" {number}  " in rendered for number in actual_numbers)


def test_entry_limit_keeps_total_heading_and_emits_configured_tails() -> None:
    text = Text()

    jump_map = append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "agent:research", "generation"),
        entries=tuple(_entry(index) for index in range(5)),
        title="NEIGHBORS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
        entry_limit=2,
        hidden_tail_label="neighbors",
        hidden_tail_hint="zz / za to show more",
        extra_tail="… +3 also listed under FAMILY SHELLS",
    )

    assert "▸ ❖ NEIGHBORS · 5\n" in text.plain
    assert ".member-0" in text.plain
    assert ".member-1" in text.plain
    assert ".member-2" not in text.plain
    assert tuple(target.number for target in jump_map.targets) == ("0", "1")
    assert "… +3 more neighbors (zz / za to show more)\n" in text.plain
    assert "… +3 also listed under FAMILY SHELLS\n" in text.plain


def test_group_labels_render_once_per_run_without_section_markers() -> None:
    entries = (
        replace(_entry(index), group_label=group)
        for index, group in enumerate(
            ("ancestors", "ancestors", "research hood", "research hood")
        )
    )
    text = Text()

    append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "agent:research", "generation"),
        entries=tuple(entries),
        title="NEIGHBORS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
    )

    assert text.plain.count("  ancestors\n") == 1
    assert text.plain.count("  research hood\n") == 1
    assert _section_ids(text) == [
        "members",
        "member:research.member-0",
        "member:research.member-1",
        "member:research.member-2",
        "member:research.member-3",
    ]


def test_dismissed_entry_is_always_annotated_and_overrides_target_role() -> None:
    base = _entry(0)
    entry = MemberRosterEntry(
        identity=base.identity,
        presented_name=base.presented_name,
        label=base.label,
        kind=base.kind,
        status=base.status,
        model=base.model,
        duration=base.duration,
        is_dismissed=True,
        target_role="dismissed",
    )
    text = Text()

    jump_map = append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "agent:research", "generation"),
        entries=(entry,),
        title="NEIGHBORS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
        target_role="neighbor",
    )

    assert "⊘ .member-0" in text.plain
    assert text.plain.endswith(" · dismissed\n")
    assert jump_map.targets[0].role == "dismissed"


def test_merged_member_jump_map_preserves_order_and_ignores_none() -> None:
    container_identity = (AgentType.RUNNING, "agent:research", "generation")
    first = append_member_roster(
        Text(),
        container_identity=container_identity,
        entries=(_entry(0),),
        title="MEMBERS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
    )
    second = append_member_roster(
        Text(),
        container_identity=container_identity,
        entries=(_entry(1),),
        title="NEIGHBORS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
        target_role="neighbor",
    )

    merged = merged_member_jump_map(container_identity, first, None, second)

    assert tuple(target.member_identity for target in merged.targets) == (
        _identity(0),
        _identity(1),
    )
    assert tuple(target.role for target in merged.targets) == ("member", "neighbor")


def test_merged_member_jump_map_rejects_a_different_container() -> None:
    jump_map = _render(1)[1]

    with pytest.raises(ValueError, match="different containers"):
        merged_member_jump_map(
            (AgentType.RUNNING, "agent:other", "generation"),
            jump_map,
        )


def test_numbering_capacity_exhaustion_stops_rendering_without_raising() -> None:
    text = Text()

    jump_map = append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "agent:research", "generation"),
        entries=tuple(_entry(index) for index in range(3)),
        title="NEIGHBORS",
        accent=_ACCENT,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=3, capacity=2),
    )

    assert tuple(target.number for target in jump_map.targets) == ("0", "1")
    assert ".member-2" not in text.plain
    assert "… +1 more members (not numbered)\n" in text.plain
