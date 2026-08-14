"""Ordering and readiness tests for the SASE CONTEXT prompt-panel section."""

from __future__ import annotations

from itertools import product

import pytest
from rich.text import Text

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    CONTEXT_LANE_ORDER,
    append_agent_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from tests.ace.tui.widgets._agent_context_helpers import (
    EXPECTED_CONTEXT_LANE_ORDER,
    bead_section,
    memory_event,
    pin_context_timezone,
    plan_section,
    skill_event,
    workspace_event,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_context_timezone(monkeypatch)


def test_context_lane_order_contract_holds_for_every_presence_combination() -> None:
    assert CONTEXT_LANE_ORDER == EXPECTED_CONTEXT_LANE_ORDER
    for presence in product((False, True), repeat=len(EXPECTED_CONTEXT_LANE_ORDER)):
        enabled = dict(zip(EXPECTED_CONTEXT_LANE_ORDER, presence, strict=True))
        text = Text()
        append_agent_context_section(
            text,
            bead_section=bead_section() if enabled["BEAD"] else None,
            plan_section=plan_section() if enabled["PLAN"] else None,
            memory_reads=(memory_event(),) if enabled["MEMORY"] else (),
            skill_uses=(skill_event(),) if enabled["SKILLS"] else (),
            opened_workspaces=((workspace_event(),) if enabled["WORKSPACES"] else ()),
            artifact_file_paths=(
                [ArtifactFilePath("result.txt", "/tmp/result.txt")]
                if enabled["ARTIFACTS"]
                else None
            ),
        )

        rendered_labels = [
            line.removeprefix("▸ ").split(" ·", maxsplit=1)[0]
            for line in text.plain.splitlines()
            if line.startswith("▸ ")
        ]
        expected_labels = [
            label for label in EXPECTED_CONTEXT_LANE_ORDER if enabled[label]
        ]
        assert rendered_labels == expected_labels
        if enabled["PLAN"]:
            assert rendered_labels[0] == "PLAN"
        if enabled["BEAD"]:
            assert rendered_labels.index("BEAD") == (1 if enabled["PLAN"] else 0)
        if enabled["ARTIFACTS"]:
            expected_index = int(enabled["BEAD"]) + int(enabled["PLAN"])
            assert rendered_labels.index("ARTIFACTS") == expected_index


def test_ready_lanes_none_omits_unresolved_lanes_like_before_streaming() -> None:
    """``ready_lanes=None`` (the default) keeps the pre-streaming contract."""
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(memory_event(),),
        ready_lanes=None,
    )

    assert "▸ MEMORY" in text.plain
    assert "resolving…" not in text.plain
    assert "▸ SKILLS" not in text.plain


def test_unresolved_lanes_render_dim_pending_affordance_not_real_content() -> None:
    """A lane absent from ``ready_lanes`` shows a pending row, not its data.

    Bead sase-l6.4: distinguishes "still resolving" from "resolved empty" so
    streamed lanes never silently disappear before they land.
    """
    text = Text()
    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
        artifact_file_paths=[ArtifactFilePath("result.txt", "/tmp/result.txt")],
        ready_lanes=frozenset(),
    )

    plain = text.plain
    for label in EXPECTED_CONTEXT_LANE_ORDER:
        assert f"▸ {label} · resolving…\n" in plain, label
    # None of the real, already-loaded data leaks into a pending row.
    assert "sase-42.3" not in plain
    assert "Plan lane" not in plain
    assert "generated_skills.md" not in plain
    assert "sase_plan" not in plain
    assert "sase-core" not in plain
    assert "result.txt" not in plain


def test_mixed_readiness_keeps_stable_order_and_only_pending_rows_stay_dim() -> None:
    """A partially-resolved summary renders ready lanes for real, in order."""
    text = Text()
    append_agent_context_section(
        text,
        bead_section=bead_section(),
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        ready_lanes=frozenset({"plan-bead", "memory"}),
    )

    plain = text.plain
    assert "▸ BEAD · ↳ phase sase-42.3\n" in plain
    assert "generated_skills.md" in plain
    assert "▸ SKILLS · resolving…\n" in plain
    assert "sase_plan" not in plain
    assert "▸ WORKSPACES · resolving…\n" in plain
    # PLAN has nothing to show yet (plan-bead is ready but no plan_section
    # was passed) -- a ready-but-empty lane still renders nothing, matching
    # "resolved to nothing" rather than "still pending".
    assert "▸ PLAN" not in plain
    assert plain.index("▸ BEAD") < plain.index("▸ MEMORY")
    assert plain.index("▸ MEMORY") < plain.index("▸ SKILLS")
    assert plain.index("▸ SKILLS") < plain.index("▸ WORKSPACES")


def test_pending_lane_does_not_consume_a_hint_number() -> None:
    """A dim pending row is non-interactive: it must not claim a hint slot."""
    text = Text()
    hint_state = HeaderHintState(
        hint_counter=1,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )

    append_agent_context_section(
        text,
        plan_section=plan_section(),
        hint_state=hint_state,
        ready_lanes=frozenset(),
    )

    assert "▸ PLAN · resolving…\n" in text.plain
    assert hint_state.hint_counter == 1
    assert hint_state.hint_mappings == {}


def test_context_lanes_render_in_parent_context_order() -> None:
    text = Text()
    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
        artifact_file_paths=[ArtifactFilePath("result.txt", "/tmp/result.txt")],
    )

    plain = text.plain
    assert plain.index("SASE CONTEXT\n") < plain.index("▸ PLAN")
    assert plain.index("▸ PLAN") < plain.index("▸ BEAD")
    assert plain.index("▸ BEAD") < plain.index("▸ ARTIFACTS")
    assert plain.index("▸ ARTIFACTS") < plain.index("▸ MEMORY")
    assert plain.index("▸ MEMORY") < plain.index("▸ SKILLS")
    assert plain.index("▸ SKILLS") < plain.index("▸ WORKSPACES")
    assert "needed generated skill rules" in plain
    assert "needed an implementation plan" in plain
    assert "needed to inspect core boundary" in plain


def test_context_hint_numbers_follow_display_order() -> None:
    text = Text()
    hint_state = HeaderHintState(
        hint_counter=1,
        hint_mappings={},
        workspace_dir="/tmp/workspace",
        tool_call_reports={},
    )
    agent = make_agent(
        workspace_dir="/tmp/workspace",
        step_output={
            "meta_commits": [
                {
                    "message": "feat: ordered hints",
                    "sha": "abcdef1234567890",
                }
            ]
        },
    )

    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        agent=agent,
        delta_entries=[DeltaEntry(path="src/output.py", change_type="M")],
        artifact_file_paths=[
            ArtifactFilePath("reports/result.md", "/tmp/reports/result.md"),
        ],
        memory_reads=(memory_event(),),
        hint_state=hint_state,
    )

    plain = text.plain
    expected_sequence = (
        "Path: [1]",
        "Epic Plan: [2]",
        "[3] abcdef123456",
        "[4] src/output.py",
        "[5] reports/result.md",
        "[6] generated_skills.md",
    )
    positions = [plain.index(item) for item in expected_sequence]
    assert positions == sorted(positions)
    assert plain.index("▸ PLAN") < plain.index("Path: [1]")
    assert plain.index("Path: [1]") < plain.index("▸ BEAD")
    assert plain.index("▸ BEAD") < plain.index("Epic Plan: [2]")
    assert plain.index("[3] abcdef123456") < plain.index("[4] src/output.py")
    assert plain.index("[4] src/output.py") < plain.index("[5] reports/result.md")
    assert plain.index("[5] reports/result.md") < plain.index("[6] generated_skills.md")
    assert hint_state.hint_mappings == {
        1: "/tmp/workspace/sase/repos/plans/plan.md",
        2: "/tmp/workspace/sase/repos/plans/epic.md",
        4: "/tmp/workspace/src/output.py",
        5: "/tmp/reports/result.md",
        6: "/tmp/test/memory/generated_skills.md",
    }
    assert list(hint_state.commit_views) == [3]
    assert hint_state.hint_counter == 7
