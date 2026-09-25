"""Jump-map sections, document carrier, and panel sink plumbing."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.models.sase_agent_neighbors import (
    LaneNeighborRow,
    SaseAgentNeighborProjection,
)
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
    AgentHeaderRenderable,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import (
    find_member_jump_map,
    find_member_roster,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
    detached_roster_text,
    member_status_style,
    merged_member_jump_map,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    make_agent_session,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _MetadataNavigationApp,
)

NOW = datetime(2026, 7, 18, 15, 0, 0)


def _entry(
    index: int,
    *,
    label: str | None = None,
    status: str = "RUNNING",
    bucket: str | None = None,
    dismissed: bool = False,
) -> MemberRosterEntry:
    name = f"research.member-{index}"
    return MemberRosterEntry(
        identity=(AgentType.RUNNING, name, f"suffix-{index}"),
        presented_name=name,
        label=label if label is not None else f".member-{index}",
        kind="agent",
        status=status,
        effective_bucket=bucket,
        model="gpt-5",
        duration="1m",
        is_dismissed=dismissed,
        target_role="dismissed" if dismissed else None,
    )


def _render(
    entries: tuple[MemberRosterEntry, ...],
    *,
    title: str = "CLAN MEMBERS",
    accent: str = "#D75FFF",
    numbering: MemberJumpNumbering | None = None,
    entry_limit: int | None = None,
) -> tuple[Text, MemberJumpMap]:
    text = Text()
    jump_map = append_member_roster(
        text,
        container_identity=(AgentType.RUNNING, "clan:research", "generation"),
        entries=entries,
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=numbering,
        entry_limit=entry_limit,
        hidden_tail_label="members",
        hidden_tail_hint="zz / za to show more",
    )
    return text, jump_map


def test_targets_carry_labels_and_buckets_with_section() -> None:
    entries = (
        _entry(0, status="DONE"),
        _entry(1, status="RUNNING", bucket="Running"),
        _entry(2, status="QUESTION", dismissed=True),
    )
    _text, jump_map = _render(entries)
    assert [target.label for target in jump_map.targets] == [
        ".member-0",
        ".member-1",
        ".member-2",
    ]
    assert [target.status_bucket for target in jump_map.targets] == [
        "Done",
        "Running",
        "Stopped",
    ]
    assert [target.role for target in jump_map.targets] == [
        "member",
        "member",
        "dismissed",
    ]
    (section,) = jump_map.sections
    assert section.title == "CLAN MEMBERS"
    assert section.accent == "#D75FFF"
    assert section.numbered_count == 3
    assert not hasattr(section, "hidden_count")
    assert not hasattr(section, "hidden_hint")
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def test_member_status_style_matches_roster() -> None:
    assert member_status_style("Done") == "bold #5FD75F"
    assert member_status_style("Running") == "bold #FFD700"


def test_capacity_spent_section_reports_tail() -> None:
    entries = tuple(_entry(index) for index in range(8))
    numbering = MemberJumpNumbering(total=8, capacity=3)
    text, jump_map = _render(entries, numbering=numbering)
    assert [target.number for target in jump_map.targets] == ["0", "1", "2"]
    (section,) = jump_map.sections
    assert section.numbered_count == 0 + 3
    assert "… +5 more members (zz / za to show more)" in text.plain
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def test_fold_limit_tail_hint() -> None:
    entries = tuple(_entry(index) for index in range(10))
    text, jump_map = _render(entries, entry_limit=3)
    assert len(jump_map.targets) == 3
    (section,) = jump_map.sections
    assert section.numbered_count == 3
    assert "… +7 more members (zz / za to show more)" in text.plain


def test_merged_map_concatenates_sections_in_order() -> None:
    identity = (AgentType.RUNNING, "lane", None)
    agent_session_text = Text()
    agent_session_map = append_member_roster(
        agent_session_text,
        container_identity=identity,
        entries=tuple(_entry(index, label=f"--plan-{index}") for index in range(2)),
        title="SESSION SHELLS",
        accent="#00AFFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=5),
    )
    neighbors_text = Text()
    neighbors_map = append_member_roster(
        neighbors_text,
        container_identity=identity,
        entries=tuple(_entry(index + 2, label=f"n-{index}") for index in range(3)),
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=5),
    )
    # Exhaust the shared ladder manually: session took 0-1, neighbors continue.
    assert [t.number for t in agent_session_map.targets] == ["0", "1"]
    merged = merged_member_jump_map(identity, agent_session_map, neighbors_map)
    assert [s.title for s in merged.sections] == ["SESSION SHELLS", "NEIGHBORS"]
    assert sum(s.numbered_count for s in merged.sections) == len(merged.targets)


def test_agent_session_container_map_has_labels_and_sections(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    published: list[MemberJumpMap] = []
    _header, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    )
    assert len(published) == 1
    jump_map = published[0]
    assert jump_map.targets
    assert all(target.label for target in jump_map.targets)
    assert all(target.status_bucket for target in jump_map.targets)
    assert [s.title for s in jump_map.sections] == ["SESSION SHELLS"]
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def _neighbor_projection(lane: Agent) -> SaseAgentNeighborProjection:
    rows = []
    for index in range(4):
        neighbor = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"lane.neighbor{index}",
            project_file="/tmp/neighbors.sase",
            status="DONE" if index % 2 == 0 else "RUNNING",
            start_time=NOW - timedelta(minutes=5),
            run_start_time=NOW - timedelta(minutes=5),
            stop_time=NOW if index % 2 == 0 else None,
            raw_suffix=f"neighbor{index}",
            agent_name=f"lane.neighbor{index}",
            model="gpt-5",
        )
        rows.append(
            LaneNeighborRow(
                agent=neighbor,
                relation="neighbor",
                group_label="lane hood",
                label_prefix="lane",
                is_prospective=False,
                is_dismissed=(index == 3),
            )
        )
    return SaseAgentNeighborProjection(
        lane_identity=lane.identity,
        rows=tuple(rows),
        suppressed_lane_member_count=0,
    )


def test_neighbors_with_dismissed_entry_sections() -> None:
    lane = make_agent(agent_name="lane")
    projection = _neighbor_projection(lane)
    published: list[MemberJumpMap] = []
    _header, _ = build_header_text(
        lane,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
        lane_neighbors=projection,
        member_jump_map_publisher=published.append,
    )
    assert len(published) == 1
    jump_map = published[0]
    assert [s.title for s in jump_map.sections] == ["NEIGHBORS"]
    dismissed = [t for t in jump_map.targets if t.role == "dismissed"]
    assert len(dismissed) == 1
    assert dismissed[0].label
    assert dismissed[0].status_bucket is not None
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def test_clan_map_sections() -> None:
    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
        make_clan_agent(
            "research.second",
            status="FAILED",
            start=datetime(2026, 7, 17, 12, 1, 0),
            stop=datetime(2026, 7, 17, 12, 1, 45),
        ),
    ]
    from sase.ace.tui.models._agent_tree import project_clan_tree

    container = project_clan_tree(members)[0]
    published: list[MemberJumpMap] = []
    build_clan_detail_text(
        container,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    )
    assert len(published) == 1
    jump_map = published[0]
    assert [s.title for s in jump_map.sections] == ["CLAN MEMBERS"]
    assert all(t.label for t in jump_map.targets)
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def test_tribe_full_map_sections() -> None:
    snapshot = make_tribe_snapshot()
    published: list[MemberJumpMap] = []
    build_tribe_detail_text(
        snapshot,
        member_jump_map_publisher=published.append,
    )
    assert len(published) == 1
    jump_map = published[0]
    assert [s.title for s in jump_map.sections] == ["TRIBE MEMBERS"]
    assert all(t.label for t in jump_map.targets)
    assert sum(s.numbered_count for s in jump_map.sections) == len(jump_map.targets)


def test_detached_header_attaches_same_object_it_publishes(
    tmp_path: Path,
) -> None:
    root, _child = make_agent_session(tmp_path)
    published: list[MemberJumpMap] = []
    document, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
        detach_identity=True,
    )
    assert isinstance(document, AgentHeaderRenderable)
    assert len(published) == 1
    assert find_member_jump_map(document) is published[0]
    assert find_member_jump_map(Group(document, Text("tail\n"))) is published[0]


def test_detached_header_attaches_without_publisher(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    document, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert isinstance(document, AgentHeaderRenderable)
    assert find_member_jump_map(document) is not None


def test_detached_clan_attaches_same_object_it_publishes() -> None:
    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
    ]
    from sase.ace.tui.models._agent_tree import project_clan_tree

    container = project_clan_tree(members)[0]
    published: list[MemberJumpMap] = []
    document = build_clan_detail_text(
        container,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
        detach_identity=True,
    )
    assert isinstance(document, AgentHeaderRenderable)
    assert len(published) == 1
    assert find_member_jump_map(document) is published[0]


def test_no_map_for_hint_documents_clan_without_members_or_plain_nodes(
    tmp_path: Path,
) -> None:
    root, _child = make_agent_session(tmp_path)
    state = HeaderHintState(1, {}, None, {})
    hint_document, _ = build_header_text(
        root,
        hint_state=state,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert find_member_jump_map(hint_document) is None

    snapshot = make_tribe_snapshot()
    cheap_document = build_tribe_detail_text(snapshot, cheap=True, detach_identity=True)
    assert find_member_jump_map(cheap_document) is None

    solo = make_agent(agent_name="solo")
    plain_document, _ = build_header_text(solo, cheap=True, detach_identity=True)
    assert find_member_jump_map(plain_document) is None
    assert find_member_jump_map(Text("No agent selected")) is None


def test_non_detached_documents_carry_no_map(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    plain, _ = build_header_text(root, cheap=True, lane_fold_level=FoldLevel.COLLAPSED)
    assert find_member_jump_map(plain) is None
    snapshot = make_tribe_snapshot()
    assert find_member_jump_map(build_tribe_detail_text(snapshot)) is None


def _assert_no_roster_in_body(body_plain: str) -> None:
    for token in (
        "❖ SESSION SHELLS",
        "❖ NEIGHBORS",
        "❖ CLAN MEMBERS",
        "❖ TRIBE MEMBERS",
    ):
        assert token not in body_plain
    # Numbered roster rows carry a chip like ` 0 ` with surrounding spaces.
    for line in body_plain.splitlines():
        assert "bold black on" not in line


def test_detached_roster_text_trims_blank_lines() -> None:
    sample = Text("\n\ncontent\nline\n\n")
    sample.append("styled", style="bold")
    trimmed = detached_roster_text(sample)
    assert trimmed is not None
    assert not trimmed.plain.startswith("\n")
    assert not trimmed.plain.endswith("\n")
    assert "content" in trimmed.plain
    assert detached_roster_text(Text("\n\n   \n")) is None


def test_detached_documents_move_rosters_out_of_body(tmp_path: Path) -> None:
    from sase.ace.tui.models._agent_tree import project_clan_tree

    root, child = make_agent_session(tmp_path)
    # Session container.
    container_doc, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert isinstance(container_doc, AgentHeaderRenderable)
    _assert_no_roster_in_body(container_doc.plain)
    container_roster = find_member_roster(container_doc)
    assert container_roster is not None
    assert "❖ SESSION SHELLS" in container_roster.plain
    assert not container_roster.plain.startswith("\n")
    assert not container_roster.plain.endswith("\n")

    # Session member shell.
    shell_doc, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert isinstance(shell_doc, AgentHeaderRenderable)
    _assert_no_roster_in_body(shell_doc.plain)
    shell_roster = find_member_roster(shell_doc)
    assert shell_roster is not None
    assert "❖ SESSION SHELLS" in shell_roster.plain

    # Agent with neighbors, including dismissed and suppressed-sibling tail.
    lane = make_agent(agent_name="lane")
    projection = _neighbor_projection(lane)
    from sase.ace.tui.models.sase_agent_neighbors import (
        SaseAgentNeighborProjection,
    )

    suppressed = SaseAgentNeighborProjection(
        lane_identity=projection.lane_identity,
        rows=projection.rows,
        suppressed_lane_member_count=2,
    )
    neighbor_doc, _ = build_header_text(
        lane,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
        lane_neighbors=suppressed,
        detach_identity=True,
    )
    assert isinstance(neighbor_doc, AgentHeaderRenderable)
    _assert_no_roster_in_body(neighbor_doc.plain)
    neighbor_roster = find_member_roster(neighbor_doc)
    assert neighbor_roster is not None
    assert "❖ NEIGHBORS" in neighbor_roster.plain
    assert "⊘" in neighbor_roster.plain
    assert "also listed under SESSION SHELLS" in neighbor_roster.plain

    collapsed_doc, _ = build_header_text(
        lane,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        lane_neighbors=projection,
        detach_identity=True,
    )
    assert isinstance(collapsed_doc, AgentHeaderRenderable)
    collapsed_roster = find_member_roster(collapsed_doc)
    assert collapsed_roster is not None
    assert "zz to show more" not in collapsed_roster.plain
    assert "more neighbors" not in collapsed_roster.plain

    # Clan.
    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
    ]
    container = project_clan_tree(members)[0]
    clan_doc = build_clan_detail_text(
        container, fold_level=FoldLevel.COLLAPSED, detach_identity=True
    )
    assert isinstance(clan_doc, AgentHeaderRenderable)
    _assert_no_roster_in_body(clan_doc.plain)
    clan_roster = find_member_roster(clan_doc)
    assert clan_roster is not None
    assert "❖ CLAN MEMBERS" in clan_roster.plain

    # Full tribe.
    snapshot = make_tribe_snapshot()
    tribe_doc = build_tribe_detail_text(snapshot, detach_identity=True)
    assert isinstance(tribe_doc, AgentHeaderRenderable)
    _assert_no_roster_in_body(tribe_doc.plain)
    tribe_roster = find_member_roster(tribe_doc)
    assert tribe_roster is not None
    assert "❖ TRIBE MEMBERS" in tribe_roster.plain

    # Chip spans survive the detach.
    assert any("bold black on" in str(span.style) for span in tribe_roster.spans)


def test_detached_roster_matches_inline_document(tmp_path: Path) -> None:
    from sase.ace.tui.models._agent_tree import project_clan_tree

    root, _child = make_agent_session(tmp_path)
    inline, _ = build_header_text(root, cheap=True, lane_fold_level=FoldLevel.COLLAPSED)
    detached, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert isinstance(detached, AgentHeaderRenderable)
    roster = find_member_roster(detached)
    assert roster is not None
    assert roster.plain in inline.plain

    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
    ]
    container = project_clan_tree(members)[0]
    inline_clan = build_clan_detail_text(container, fold_level=FoldLevel.COLLAPSED)
    detached_clan = build_clan_detail_text(
        container, fold_level=FoldLevel.COLLAPSED, detach_identity=True
    )
    assert isinstance(detached_clan, AgentHeaderRenderable)
    clan_roster = find_member_roster(detached_clan)
    assert clan_roster is not None
    assert clan_roster.plain in inline_clan.plain


def test_hint_mode_carries_no_map_or_roster(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    state = HeaderHintState(1, {}, None, {})
    hint_document, _ = build_header_text(
        root,
        hint_state=state,
        lane_fold_level=FoldLevel.COLLAPSED,
        detach_identity=True,
    )
    assert find_member_jump_map(hint_document) is None
    assert find_member_roster(hint_document) is None
    assert isinstance(hint_document, AgentHeaderRenderable)
    _assert_no_roster_in_body(hint_document.plain)


def test_tribe_cheap_carries_no_roster() -> None:
    snapshot = make_tribe_snapshot()
    cheap_document = build_tribe_detail_text(snapshot, cheap=True, detach_identity=True)
    assert find_member_jump_map(cheap_document) is None
    assert find_member_roster(cheap_document) is None


async def test_panel_sink_receives_jump_map_before_digest_return() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(60, 20)):
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        received: list[tuple[MemberJumpMap | None, Text | None]] = []
        panel.attach_member_jump_map_sink(
            lambda jump_map, roster: received.append((jump_map, roster))
        )

        agent = make_agent(agent_name="solo")
        plain, _ = build_header_text(agent, cheap=True, detach_identity=True)
        panel.update(plain)
        assert len(received) == 1
        assert received[0] == (None, None)

        panel.update(plain)
        assert len(received) == 2
        assert received[1] == (None, None)

        panel.attach_member_jump_map_sink(None)


async def test_panel_sink_receives_roster_and_repaints_on_roster_only_change() -> None:
    lane = make_agent(agent_name="lane")
    projection = _neighbor_projection(lane)
    assert projection.rows
    first_document, _ = build_header_text(
        lane,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
        lane_neighbors=projection,
        detach_identity=True,
    )
    assert isinstance(first_document, AgentHeaderRenderable)
    first_roster = find_member_roster(first_document)
    assert first_roster is not None
    assert "❖ NEIGHBORS" in first_roster.plain

    app = _MetadataNavigationApp()
    async with app.run_test(size=(60, 20)):
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        received: list[tuple[MemberJumpMap | None, Text | None]] = []
        panel.attach_member_jump_map_sink(
            lambda jump_map, roster: received.append((jump_map, roster))
        )
        panel.update(first_document)
        assert received and received[0][0] is not None
        assert received[0][1] is not None

        # A roster-only change must still reach the panel even when the body
        # digest is unchanged: same body text, different roster text.
        from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
            AgentHeaderRenderable as Carrier,
        )
        from sase.ace.tui.widgets.prompt_panel._identity_header import (
            find_identity_header,
        )

        assert isinstance(first_document, Carrier)
        assert first_document.member_jump_map is not None
        second_roster = Text(first_roster.plain.replace("RUNNING", "FAILED"))
        second_document = Carrier(
            Text(first_document.plain),
            (),
            identity_header=find_identity_header(first_document),
            member_jump_map=first_document.member_jump_map,
            member_roster=second_roster,
        )
        panel.update(second_document)
        assert len(received) == 2
        assert received[1][1] is not None
        assert received[1][1].plain != received[0][1].plain  # type: ignore[index]

        inline = panel.inline_document_renderable()
        assert isinstance(inline, Group)
        from io import StringIO

        from rich.console import Console

        output = StringIO()
        Console(file=output, width=60, color_system=None).print(inline, end="")
        assert "❖ NEIGHBORS" in output.getvalue()

        panel.attach_member_jump_map_sink(None)
