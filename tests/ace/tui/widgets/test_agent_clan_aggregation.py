"""Disk-backed clan aggregation, caching, and worker tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.agents._display_detail import DetailMixin
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskMemberSnapshot,
    ClanDiskSnapshot,
    ClanTextEntry,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    _aggregate_clan_context_lanes,
    _aggregate_clan_slow_tool_calls,
    _ClanDiskContentCache,
    _load_clan_disk_member_snapshot,
    get_cached_clan_section_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    clan_disk_sections_for_fold_state,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._messages import ClanSectionSnapshotLoaded
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent

_GENERATION = "20260718100000"
_SASE_BEADS_SKILL = "sase" + "_beads"


def _agent(name: str, *, minute: int = 0, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": datetime(2026, 7, 18, 10, minute),
        "stop_time": datetime(2026, 7, 18, 10, minute + 1),
        "raw_suffix": f"row-{minute}-{name}",
        "agent_name": name,
        "agent_clan": "research",
        "agent_clan_generation": _GENERATION,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _member_snapshot(
    member: Agent,
    label: str,
    *,
    context: DetailHeaderSummary | None = None,
    sources: tuple[SlowToolSource, ...] | None = None,
) -> ClanDiskMemberSnapshot:
    return ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=label,
        loaded_sections=frozenset({"context", "slow-tool-calls"}),
        context=context,
        slow_tool_sources=sources,
    )


def test_member_cache_hits_same_mtime_token_and_expands_section_union(
    monkeypatch: Any,
) -> None:
    member = _agent("research.one")
    cache = _ClanDiskContentCache()
    calls: list[frozenset[str]] = []
    token = [1]
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "_clan_member_source_token",
        lambda _member: ("stable", token[0]),
    )

    def loader(
        member_arg: Agent,
        label: str,
        sections: frozenset[Any],
    ) -> ClanDiskMemberSnapshot:
        calls.append(frozenset(sections))
        return ClanDiskMemberSnapshot(
            member_identity=member_arg.identity,
            member_label=label,
            loaded_sections=sections,
        )

    first = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )
    second = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )
    expanded = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"context"}),
        loader=loader,
    )
    token[0] = 2
    invalidated = cache.load(
        member,
        member_label=".one",
        sections=frozenset({"replies"}),
        loader=loader,
    )

    assert first is second
    assert calls == [
        frozenset({"replies"}),
        frozenset({"replies", "context"}),
        frozenset({"replies"}),
    ]
    assert expanded.loaded_sections == frozenset({"replies", "context"})
    assert invalidated is not expanded


def test_member_loader_reuses_reply_and_prompt_precedence(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "\n#research first segment\n",
        encoding="utf-8",
    )
    (artifacts / "01_prompt.md").write_text(
        "\nExpanded prompt body\n",
        encoding="utf-8",
    )
    response = artifacts / "response.md"
    response.write_text("\nFinal member conclusion\nsecond line\n", encoding="utf-8")
    member = _agent(
        "research.one",
        artifacts_dir=str(artifacts),
        response_path=str(response),
    )

    snapshot = _load_clan_disk_member_snapshot(
        member,
        ".one",
        frozenset({"replies", "prompts"}),
    )

    assert [(entry.kind, entry.preview) for entry in snapshot.replies] == [
        ("AGENT REPLY", "Final member conclusion")
    ]
    assert [(entry.kind, entry.preview) for entry in snapshot.prompts] == [
        ("AGENT XPROMPT", "#research first segment"),
        ("AGENT PROMPT", "Expanded prompt body"),
    ]


def test_context_lanes_dedupe_in_declared_order_and_count_uses() -> None:
    first = _agent(
        "research.first",
        epic_bead_id="sase-6u",
        plan_path="/tmp/plan.md",
        workspace_num=4,
    )
    second = _agent(
        "research.second",
        minute=2,
        epic_bead_id="sase-6u",
        plan_path="/tmp/plan.md",
        workspace_num=4,
    )
    container = project_clan_tree([second, first])[0]
    in_memory = aggregate_clan_in_memory(container)
    memory_event = MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="read-1",
        timestamp="2026-07-18T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        canonical_path="tui_perf.md",
        resolved_path="/tmp/tui_perf.md",
        agent_name="research.first",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        byte_count=10,
        frontmatter_stripped=False,
    )
    skill_event = SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id="skill-1",
        timestamp="2026-07-18T10:00:00+00:00",
        project="demo",
        cwd="/tmp",
        skill_name=_SASE_BEADS_SKILL,
        agent_name="research.first",
        agent_source="test",
        artifacts_dir="/tmp/artifacts",
        reason="test",
        runtime="codex",
    )

    def summary(suffix: str) -> DetailHeaderSummary:
        return DetailHeaderSummary(
            artifact_file_paths=[
                ArtifactFilePath(
                    display_path="report.md",
                    actual_path="/tmp/report.md",
                )
            ],
            memory_reads=(MemoryReadDisplayEvent(event=memory_event),),
            skill_uses=(SkillUseDisplayEvent(event=skill_event),),
            opened_workspaces=(
                OpenedWorkspaceDisplayEvent(
                    name="sase-core",
                    workspace_dir="/tmp/sase-core",
                    reason=suffix,
                    opened_at="2026-07-18T10:00:00+00:00",
                ),
            ),
        )

    members = (
        _member_snapshot(first, ".first", context=summary("first")),
        _member_snapshot(second, ".second", context=summary("second")),
    )
    lanes = _aggregate_clan_context_lanes(in_memory, members)

    assert [lane.label for lane in lanes] == [
        "BEAD",
        "PLAN",
        "ARTIFACTS",
        "MEMORY",
        "SKILLS",
        "WORKSPACES",
    ]
    by_label = {lane.label: lane for lane in lanes}
    assert len(by_label["ARTIFACTS"].entries) == 1
    assert by_label["ARTIFACTS"].entries[0].member_labels == (
        ".first",
        ".second",
    )
    assert by_label["MEMORY"].entries[0].count == 2
    assert by_label["SKILLS"].entries[0].label == _SASE_BEADS_SKILL
    assert by_label["SKILLS"].entries[0].count == 2
    # The in-memory workspace number and disk-backed opened repo remain
    # distinct, while duplicate opened repo paths collapse across members.
    assert [entry.label for entry in by_label["WORKSPACES"].entries] == [
        "workspace 4",
        "sase-core",
    ]


def test_slow_calls_are_deduped_and_ranked_by_duration() -> None:
    first = _agent("research.first")
    second = _agent("research.second", minute=2)
    shorter = ToolCallEntry(
        recorded_at="2026-07-18T10:00:00+00:00",
        runtime="codex",
        event="PostToolUse",
        status="success",
        tool_name="Read",
        tool_use_id="call-1",
        duration_ms=25_000,
        artifact_dir="/tmp/first",
        line_number=1,
    )
    longer = ToolCallEntry(
        recorded_at="2026-07-18T10:01:00+00:00",
        runtime="codex",
        event="PostToolUse",
        status="success",
        tool_name="Bash",
        tool_use_id="call-2",
        duration_ms=40_000,
        artifact_dir="/tmp/first",
        line_number=2,
    )
    source = SlowToolSource(
        label=None,
        entries=(shorter, longer),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )
    duplicate_source = SlowToolSource(
        label=None,
        entries=(shorter,),
        agent_is_active=False,
        end_reference=None,
        palette_index=0,
    )
    members = (
        _member_snapshot(first, ".first", sources=(source,)),
        _member_snapshot(second, ".second", sources=(duplicate_source,)),
    )

    calls = _aggregate_clan_slow_tool_calls(
        members,
        now=datetime(2026, 7, 18, 10, 2, tzinfo=UTC),
        threshold_ms=20_000,
    )

    assert [entry.call.entry.tool_use_id for entry in calls] == ["call-2", "call-1"]
    assert [entry.member_label for entry in calls] == [".first", ".first"]


class _FakeWorker:
    def __init__(self) -> None:
        self.is_running = True
        self.result: object | None = None
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class _ClanPanel(AgentDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []
        self.messages: list[object] = []
        self.worker = _FakeWorker()
        self.worker_fn: Callable[[], object] | None = None
        self.worker_runs = 0

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)

    def post_message(self, message: object) -> None:
        self.messages.append(message)

    def run_worker(self, fn: Callable[[], object], *, thread: bool) -> _FakeWorker:
        assert thread
        self.worker_runs += 1
        self.worker_fn = fn
        self.worker = _FakeWorker()
        return self.worker


def _disk_for(snapshot: Any) -> ClanDiskSnapshot:
    members = tuple(
        ClanDiskMemberSnapshot(
            member_identity=member.identity,
            member_label=member.label,
            loaded_sections=frozenset({"replies"}),
            replies=(
                ClanTextEntry(
                    member_identity=member.identity,
                    member_label=member.label,
                    kind="AGENT REPLY",
                    preview="done",
                    body="done",
                ),
            ),
        )
        for member in snapshot.in_memory.members
    )
    return ClanDiskSnapshot(
        loaded_sections=frozenset({"replies"}),
        members=members,
        replies=tuple(reply for member in members for reply in member.replies),
        prompts=(),
        context_lanes=(),
        slow_tool_calls=(),
    )


def test_collapsed_presence_discovery_enriches_and_reuses_member_artifacts(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "#review representative segment\n",
        encoding="utf-8",
    )
    (artifacts / "01_prompt.md").write_text(
        "Inspect the clan summary contract.\n",
        encoding="utf-8",
    )
    response = artifacts / "response.md"
    response.write_text("Representative reply.\n", encoding="utf-8")
    member = _agent(
        "research.one",
        artifacts_dir=str(artifacts),
        response_path=str(response),
    )
    container = project_clan_tree([member])[0]
    panel = _ClanPanel()
    panel.set_agent_detail_render_context(
        generation=3,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda identity, *_args: identity == container.identity,
    )
    panel.set_clan_disk_sections_required(
        clan_disk_sections_for_fold_state(FoldLevel.COLLAPSED)
    )

    panel.update_display(container)

    cold = cast(Text, panel.captured[-1]).plain
    for heading in ("REPLIES", "SASE CONTEXT", "SLOW TOOL CALLS", "PROMPTS"):
        assert f"▸ {heading}" in cold
    assert "▸ REPLIES ·" not in cold
    assert panel.worker_runs == 1
    assert panel.worker_fn is not None

    panel.worker.result = panel.worker_fn()
    panel._apply_clan_section_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )
    panel.update_display(container)

    cached = get_cached_clan_section_snapshot(panel, container)
    assert cached is not None and cached.disk is not None
    assert cached.disk.loaded_sections == CLAN_DISK_SECTIONS
    assert [entry.preview for entry in cached.disk.replies] == ["Representative reply."]
    assert [entry.preview for entry in cached.disk.prompts] == [
        "#review representative segment",
        "Inspect the clan summary contract.",
    ]
    enriched = cast(Text, panel.captured[-1]).plain
    assert "▸ REPLIES · 1" in enriched
    assert "▸ PROMPTS · 2" in enriched
    assert "SLOW TOOL CALLS" not in enriched
    assert panel.worker_runs == 1


def test_clan_worker_coalesces_and_discards_stale_selection(
    monkeypatch: Any,
) -> None:
    member = _agent("research.one")
    container = project_clan_tree([member])[0]
    panel = _ClanPanel()
    current = False
    panel.set_agent_detail_render_context(
        generation=3,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda *_args: current,
    )
    panel.set_clan_disk_sections_required({"replies"})

    def build(
        _widget: object,
        _agent: Agent,
        in_memory: object,
        **_kwargs: object,
    ) -> ClanDiskSnapshot:
        snapshot = get_cached_clan_section_snapshot(panel, container)
        assert snapshot is not None
        assert in_memory == snapshot.in_memory
        return _disk_for(snapshot)

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_clan_disk_snapshot",
        build,
    )

    panel.update_display(container)
    first_worker = panel.worker
    assert panel.worker_fn is not None
    panel.update_display(container)
    assert panel.worker is first_worker
    assert not first_worker.cancelled

    first_worker.result = panel.worker_fn()
    panel._apply_clan_section_enrichment_result(
        cast(Worker[Any], first_worker),
        WorkerState.SUCCESS,
    )

    cached = get_cached_clan_section_snapshot(panel, container)
    assert cached is not None
    assert cached.disk is None
    assert cached.loading_sections == frozenset()
    assert panel.messages == []


def test_current_clan_worker_caches_and_posts_completion_message(
    monkeypatch: Any,
) -> None:
    member = _agent("research.one")
    container = project_clan_tree([member])[0]
    panel = _ClanPanel()
    panel.set_agent_detail_render_context(
        generation=3,
        attempt_view_mode="merged",
        attempt_pinned_number=None,
        is_current=lambda identity, *_args: identity == container.identity,
    )
    panel.set_clan_disk_sections_required({"replies"})

    def build(*_args: object, **_kwargs: object) -> ClanDiskSnapshot:
        snapshot = get_cached_clan_section_snapshot(panel, container)
        assert snapshot is not None
        return _disk_for(snapshot)

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_async."
        "build_clan_disk_snapshot",
        build,
    )

    panel.update_display(container)
    assert panel.worker_fn is not None
    panel.worker.result = panel.worker_fn()
    panel._apply_clan_section_enrichment_result(
        cast(Worker[Any], panel.worker),
        WorkerState.SUCCESS,
    )

    cached = get_cached_clan_section_snapshot(panel, container)
    assert cached is not None and cached.disk is not None
    assert cached.disk.replies[0].preview == "done"
    assert len(panel.messages) == 1
    assert isinstance(panel.messages[0], ClanSectionSnapshotLoaded)


class _Debouncer:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def schedule(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _DetailHarness(DetailMixin):
    def __init__(self, selected: Agent) -> None:
        self.selected = selected
        self._agent_detail_debouncer = _Debouncer()  # type: ignore[assignment]

    def _get_selected_agent(self) -> Agent:
        return self.selected

    def _fire_debounced_detail_update(self) -> None:
        pass


def test_clan_completion_repaint_uses_existing_detail_debouncer() -> None:
    member = _agent("research.one")
    container = project_clan_tree([member])[0]
    harness = _DetailHarness(container)
    message = ClanSectionSnapshotLoaded(container.identity)

    harness.on_clan_section_snapshot_loaded(message)

    debouncer = cast(_Debouncer, harness._agent_detail_debouncer)
    assert debouncer.callbacks == [harness._fire_debounced_detail_update]
