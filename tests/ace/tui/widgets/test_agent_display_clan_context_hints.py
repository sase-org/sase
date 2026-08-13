"""Structured SASE CONTEXT hints in clan detail panels."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.models._agent_clan_sections import (
    ClanContextEntry,
    ClanContextLane,
    ClanDiskMemberSnapshot,
)
from sase.ace.tui.models.agent_associated_plan import BeadSummary
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from sase.ace.tui.widgets.prompt_panel._agent_clan_disk_aggregation import (
    aggregate_clan_context_lanes,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_sections import (
    append_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
    HeaderHintState,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from tests.ace.tui.widgets._agent_display_clan_helpers import rich_clan_snapshot
from tests.ace.tui.widgets._agent_display_plan_helpers import plan_summary

# Split so the pyscripts path linter does not read the skill name as a
# reference to a ``tools/`` directory, matching the clan display helpers.
_SASE_BEADS_SKILL = "sase" + "_beads"


def _memory_read(resolved_path: str) -> MemoryReadDisplayEvent:
    return MemoryReadDisplayEvent(
        event=MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="read-1",
            timestamp="2026-08-01T12:00:00+00:00",
            project="sase",
            cwd="/tmp",
            canonical_path="tui_perf.md",
            resolved_path=resolved_path,
            agent_name="research.one",
            agent_source="test",
            artifacts_dir=None,
            reason="test",
            byte_count=10,
            frontmatter_stripped=False,
        )
    )


def _context_lanes(tmp_path: Path) -> tuple[ClanContextLane, ...]:
    linked_workspace = tmp_path / "linked"
    plan_path = tmp_path / "plans" / "epic.md"
    bead_plan_path = tmp_path / "plans" / "bead.md"
    artifact_path = tmp_path / "artifacts" / "report.md"
    memory_path = tmp_path / "memory" / "tui_perf.md"
    return (
        ClanContextLane(
            "PLAN",
            (
                ClanContextEntry(
                    key="plan",
                    label="plan:epic.md",
                    member_labels=(".one",),
                    values=(plan_summary(actual_path=str(plan_path)),),
                ),
            ),
        ),
        ClanContextLane(
            "BEAD",
            (
                ClanContextEntry(
                    key="sase-demo.1",
                    label="sase-demo.1",
                    member_labels=(".one",),
                    values=(
                        BeadSummary(
                            id="sase-demo.1",
                            phase_title="Context hints",
                            description=None,
                            actual_plan_path=str(bead_plan_path),
                            display_plan_path="plan:bead.md",
                            plan_exists=True,
                            plan_readable=True,
                            epic_title="Demo",
                            size="small",
                        ),
                    ),
                ),
            ),
        ),
        ClanContextLane(
            "ARTIFACTS",
            (
                ClanContextEntry(
                    key="artifact",
                    label="report.md",
                    member_labels=(".one",),
                    values=(ArtifactFilePath("report.md", str(artifact_path)),),
                ),
                ClanContextEntry(
                    key="primary-delta",
                    label="src/main.py",
                    member_labels=(".one",),
                    values=(DeltaEntry(path="src/main.py", change_type="M"),),
                ),
                ClanContextEntry(
                    key="linked-delta",
                    label="sase-core/src/lib.rs",
                    member_labels=(".one",),
                    values=(
                        LinkedDeltaGroup(
                            repo_name="sase-core",
                            workspace_dir=str(linked_workspace),
                            entries=(DeltaEntry(path="src/lib.rs", change_type="M"),),
                        ),
                    ),
                ),
            ),
        ),
        ClanContextLane(
            "MEMORY",
            (
                ClanContextEntry(
                    key="memory",
                    label="tui_perf.md",
                    member_labels=(".one",),
                    values=(_memory_read(str(memory_path)),),
                ),
            ),
        ),
        ClanContextLane(
            "SKILLS",
            (
                ClanContextEntry(
                    key=_SASE_BEADS_SKILL,
                    label=_SASE_BEADS_SKILL,
                    member_labels=(".one",),
                    values=(_SASE_BEADS_SKILL,),
                ),
            ),
        ),
        ClanContextLane(
            "WORKSPACES",
            (
                ClanContextEntry(
                    key="workspace",
                    label="sase-core",
                    member_labels=(".one",),
                    values=(str(linked_workspace),),
                ),
            ),
        ),
    )


def test_fully_expanded_context_uses_typed_exact_path_hints(tmp_path: Path) -> None:
    text = Text()
    state = HeaderHintState(1, {}, None, {})

    append_context_section(
        text,
        _context_lanes(tmp_path),
        level=FoldLevel.FULLY_EXPANDED,
        count_known=True,
        hint_state=state,
        member_workspaces={".one": str(tmp_path / "primary")},
    )

    assert state.hint_mappings == {
        1: str(tmp_path / "plans" / "epic.md"),
        2: str(tmp_path / "plans" / "bead.md"),
        3: str(tmp_path / "artifacts" / "report.md"),
        4: str(tmp_path / "primary" / "src" / "main.py"),
        5: str(tmp_path / "linked" / "src" / "lib.rs"),
        6: str(tmp_path / "memory" / "tui_perf.md"),
    }
    assert text.plain.count("[") == 6
    assert "• [1] plan:epic.md" in text.plain
    assert f"• {_SASE_BEADS_SKILL}" in text.plain
    assert "• sase-core" in text.plain


def test_expanded_context_digest_does_not_register_hints(tmp_path: Path) -> None:
    text = Text()
    state = HeaderHintState(4, {}, None, {})

    append_context_section(
        text,
        _context_lanes(tmp_path),
        level=FoldLevel.EXPANDED,
        count_known=True,
        hint_state=state,
        member_workspaces={".one": str(tmp_path / "primary")},
    )

    assert state.hint_counter == 4
    assert state.hint_mappings == {}
    assert "[4]" not in text.plain


def test_context_entry_registers_only_first_resolved_value(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    lanes = (
        ClanContextLane(
            "ARTIFACTS",
            (
                ClanContextEntry(
                    key="shared",
                    label="shared.md",
                    member_labels=(".one", ".two"),
                    values=(
                        ArtifactFilePath("first.md", str(first)),
                        ArtifactFilePath("second.md", str(second)),
                    ),
                ),
            ),
        ),
    )
    text = Text()
    state = HeaderHintState(1, {}, None, {})

    append_context_section(
        text,
        lanes,
        level=FoldLevel.FULLY_EXPANDED,
        count_known=True,
        hint_state=state,
    )

    assert state.hint_mappings == {1: str(first)}
    assert text.plain.count("[1]") == 1


def test_linked_delta_aggregation_preserves_owning_workspace(tmp_path: Path) -> None:
    container, snapshot = rich_clan_snapshot()
    member = container.runtime_children[0]
    linked_workspace = tmp_path / "linked"
    linked_group = LinkedDeltaGroup(
        repo_name="sase-core",
        workspace_dir=str(linked_workspace),
        entries=(DeltaEntry(path="src/lib.rs", change_type="M"),),
    )
    disk_member = ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=".one",
        loaded_sections=frozenset({"context"}),
        context=DetailHeaderSummary(linked_delta_groups=(linked_group,)),
    )

    lanes = aggregate_clan_context_lanes(snapshot.in_memory, (disk_member,))
    artifacts = next(lane for lane in lanes if lane.label == "ARTIFACTS")
    linked_value = artifacts.entries[0].values[0]

    assert isinstance(linked_value, LinkedDeltaGroup)
    assert linked_value.workspace_dir == str(linked_workspace)
    assert linked_value.entries[0].path == "src/lib.rs"
