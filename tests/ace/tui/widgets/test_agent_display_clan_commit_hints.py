"""Commit aggregation and hints in agent-clan detail panels."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._agent_clan_sections import (
    ClanDiskMemberSnapshot,
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_clan_disk_aggregation import (
    aggregate_clan_context_lanes,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent


def _commit_clan(tmp_path: Path):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_diff = tmp_path / "first.diff"
    second_diff = tmp_path / "second.diff"
    sha = "abcdef1234567890abcdef1234567890abcdef12"
    first = make_clan_agent(
        "research.one",
        status="DONE",
        start=datetime(2026, 8, 1, 12, 0, 0),
    )
    first.workspace_dir = str(first_workspace)
    first.step_output = {
        "meta_commits": [
            {
                "message": "feat: clan commit hints\n\nFirst body",
                "sha": sha,
                "cwd": str(first_workspace),
                "diff_path": str(first_diff),
            }
        ]
    }
    second = make_clan_agent(
        "research.two",
        status="DONE",
        start=datetime(2026, 8, 1, 12, 1, 0),
    )
    second.workspace_dir = str(second_workspace)
    second.step_output = {
        "meta_commits": [
            {
                "message": "feat: clan commit hints\n\nSecond body",
                "sha": sha,
                "cwd": str(second_workspace),
                "diff_path": str(second_diff),
            }
        ]
    }
    return project_clan_tree([first, second])[0], first, second


def test_member_commits_dedupe_by_sha_and_keep_both_attributions(
    tmp_path: Path,
) -> None:
    container, first, second = _commit_clan(tmp_path)
    in_memory = aggregate_clan_in_memory(container)
    disk_members = tuple(
        ClanDiskMemberSnapshot(
            member_identity=member.identity,
            member_label=label,
            loaded_sections=frozenset({"context"}),
        )
        for member, label in ((first, ".one"), (second, ".two"))
    )

    lanes = aggregate_clan_context_lanes(
        in_memory,
        disk_members,
        member_rows=(first, second),
    )

    commits = next(lane for lane in lanes if lane.label == "COMMITS")
    assert len(commits.entries) == 1
    entry = commits.entries[0]
    assert entry.key == "abcdef1234567890abcdef1234567890abcdef12"
    assert entry.label == "abcdef123456 feat: clan commit hints"
    assert entry.member_labels == (".one", ".two")
    assert entry.count == 2
    assert len(entry.values) == 2


def test_minimal_context_renders_commit_hints_before_disk_enrichment(
    tmp_path: Path,
) -> None:
    container, _first, _second = _commit_clan(tmp_path)
    snapshot = ClanSectionSnapshot(in_memory=aggregate_clan_in_memory(container))
    state = HeaderHintState(3, {}, None, {})

    text = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
        hint_state=state,
    )

    assert "COMMITS\n  • [3] abcdef123456 feat: clan commit hints ×2" in text.plain
    assert state.hint_mappings == {}
    assert list(state.commit_views) == [3]
    spec = state.commit_views[3]
    assert spec.cwd == str(tmp_path / "first")
    assert spec.diff_path == str(tmp_path / "first.diff")


def test_commit_digest_does_not_register_hints_until_fully_expanded(
    tmp_path: Path,
) -> None:
    container, _first, _second = _commit_clan(tmp_path)
    snapshot = ClanSectionSnapshot(in_memory=aggregate_clan_in_memory(container))
    state = HeaderHintState(1, {}, None, {})

    text = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.EXPANDED,
        hint_state=state,
    )

    assert "COMMITS · abcdef123456 feat: clan commit hints" in text.plain
    assert state.commit_views == {}
    assert state.hint_counter == 1
