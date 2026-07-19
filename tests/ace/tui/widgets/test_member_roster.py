"""Shared numbered member-roster rendering."""

from __future__ import annotations

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
    MemberRosterChild,
    MemberRosterEntry,
    append_member_roster,
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
    section_ids: list[str] = []
    for span in text.spans:
        style = span.style
        if not isinstance(style, RichStyle) or not style.meta:
            continue
        section_id = style.meta.get(SECTION_MARKER_META_KEY)
        if isinstance(section_id, str) and section_id not in section_ids:
            section_ids.append(section_id)

    assert section_ids == [
        "members",
        "member:research.member-0",
        "member:research.member-1",
    ]
