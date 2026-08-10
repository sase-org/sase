"""Async clan enrichment, cache revision, and repaint tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.actions.agents._display_detail import DetailMixin
from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskMemberSnapshot,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    ClanTextEntry,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    build_clan_disk_snapshot,
    cache_clan_disk_snapshot,
    clear_clan_snapshot_loading,
    get_cached_clan_section_snapshot,
    mark_clan_snapshot_loading,
    prepare_clan_section_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    clan_disk_sections_for_fold_state,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._messages import ClanSectionSnapshotLoaded
from sase.scripts.sase_clan_summary_epic import _render_plan_summary
from sase.sdd.plan_display import PlanDisplay

_GENERATION = "20260718100000"


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
        assert heading not in cold
    assert cold.count("⋯ scanning member data…") == 1
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
    assert "⋯ scanning member data…" not in enriched
    assert panel.worker_runs == 1


def test_clan_snapshot_revision_changes_only_when_worker_result_merges() -> None:
    member = _agent("research.one")
    container = project_clan_tree([member])[0]
    panel = _ClanPanel()

    initial = prepare_clan_section_snapshot(panel, container)
    mark_clan_snapshot_loading(panel, container, {"replies"})
    loading = get_cached_clan_section_snapshot(panel, container)
    assert loading is not None
    clear_clan_snapshot_loading(panel, container)
    cleared = get_cached_clan_section_snapshot(panel, container)
    assert cleared is not None

    first = cache_clan_disk_snapshot(panel, container, _disk_for(initial))
    assert first is not None
    refreshed = prepare_clan_section_snapshot(panel, container)
    second = cache_clan_disk_snapshot(panel, container, _disk_for(refreshed))

    assert initial.revision == loading.revision == cleared.revision == 0
    assert first.revision == refreshed.revision == 1
    assert second is not None and second.revision == 2


def test_clan_worker_indexes_logical_plan_reference(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    member = _agent("research.one", workspace_dir=str(tmp_path), workspace_num=7)
    container = project_clan_tree([member])[0]
    container.clan_summary = "Plan: plans:202608/clan.md"
    in_memory = aggregate_clan_in_memory(container)
    disk = _disk_for(ClanSectionSnapshot(in_memory=in_memory))
    resolved = tmp_path / "plans" / "202608" / "clan.md"

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.parse_plan_reference",
        lambda value: SimpleNamespace(path=value.split(":", 1)[1]),
    )
    resolve = Mock(return_value=SimpleNamespace(resolved_path=resolved))
    monkeypatch.setattr("sase.sdd.plan_refs.resolve_plan_reference", resolve)

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"replies"},
    )

    assert enriched.hint_paths["plans:202608/clan.md"] == str(resolved)
    assert enriched.hint_paths["202608/clan.md"] == str(resolved)
    resolve.assert_called_once_with(
        "plans:202608/clan.md",
        workspace_dir=str(tmp_path),
        workspace_num=7,
    )


def test_clan_worker_indexes_markup_logical_plan_reference(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    member = _agent("research.one", workspace_dir=str(tmp_path), workspace_num=7)
    container = project_clan_tree([member])[0]
    container.clan_summary = _render_plan_summary(
        "sase-ej",
        PlanDisplay(
            title="Markup reference",
            goal="Render the plan reference as stored Rich markup.",
            authored_tier="tale",
            effective_tier="tale",
            actual_path=str(tmp_path / "plans" / "202608" / "markup.md"),
            display_path="plans:202608/markup.md",
            committed=True,
            exists=True,
            readable=True,
            frontmatter_readable=True,
            phase_availability="not-applicable",
            phases=(),
            validation_ok=True,
            size="small",
        ),
    )
    in_memory = aggregate_clan_in_memory(container)
    disk = _disk_for(ClanSectionSnapshot(in_memory=in_memory))
    resolved = tmp_path / "plans" / "202608" / "markup.md"

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.parse_plan_reference",
        lambda value: SimpleNamespace(path=value.split(":", 1)[1]),
    )
    resolve = Mock(return_value=SimpleNamespace(resolved_path=resolved))
    monkeypatch.setattr("sase.sdd.plan_refs.resolve_plan_reference", resolve)

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"replies"},
    )

    assert enriched.hint_paths["plans:202608/markup.md"] == str(resolved)
    assert enriched.hint_paths["202608/markup.md"] == str(resolved)
    resolve.assert_called_once_with(
        "plans:202608/markup.md",
        workspace_dir=str(tmp_path),
        workspace_num=7,
    )


def test_clan_worker_ignores_http_urls(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    member = _agent("research.one", workspace_dir=str(tmp_path), workspace_num=7)
    container = project_clan_tree([member])[0]
    container.clan_summary = (
        "Page: https://github.com/sase-org/sase--beads/blob/main/pages/sase-ej/"
        "README.md"
    )
    in_memory = aggregate_clan_in_memory(container)
    disk = _disk_for(ClanSectionSnapshot(in_memory=in_memory))
    parse = Mock()
    resolve = Mock()

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )
    monkeypatch.setattr("sase.sdd.plan_refs.parse_plan_reference", parse)
    monkeypatch.setattr("sase.sdd.plan_refs.resolve_plan_reference", resolve)

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"replies"},
    )

    assert enriched.hint_paths == {}
    parse.assert_not_called()
    resolve.assert_not_called()


def test_clan_worker_indexes_archived_prompt_reference_exactly(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    project_key = "gh_acme__demo"
    project_dir = sase_home / "projects" / project_key
    project_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    member = _agent(
        "research.one",
        project_file=str(project_dir / f"{project_key}.sase"),
        workspace_dir=str(workspace),
        workspace_num=7,
    )
    container = project_clan_tree([member])[0]
    container.clan_summary = "Path: plans:202608/x.md\nPrompt: prompts/202608/x.md"
    prompt_target = project_dir / "repos" / "agents" / "prompts" / "202608" / "x.md"
    prompt_target.parent.mkdir(parents=True)
    prompt_target.write_text("archived prompt\n", encoding="utf-8")
    in_memory = aggregate_clan_in_memory(container)
    disk = _disk_for(ClanSectionSnapshot(in_memory=in_memory))
    plan_target = tmp_path / "plans" / "202608" / "x.md"

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.parse_plan_reference",
        lambda value: SimpleNamespace(path=value.split(":", 1)[1]),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_reference",
        Mock(return_value=SimpleNamespace(resolved_path=plan_target)),
    )

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"replies"},
    )

    assert enriched.hint_paths["prompts/202608/x.md"] == str(prompt_target)
    assert enriched.hint_paths["202608/x.md"] == str(plan_target)
    assert "x.md" not in enriched.hint_paths


def test_clan_worker_leaves_missing_archived_prompt_unindexed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    project_key = "gh_acme__demo"
    project_dir = tmp_path / ".sase" / "projects" / project_key
    project_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    member = _agent(
        "research.one",
        project_file=str(project_dir / f"{project_key}.sase"),
        workspace_dir=str(workspace),
        workspace_num=7,
    )
    container = project_clan_tree([member])[0]
    container.clan_summary = "Prompt: prompts/202608/missing.md"
    in_memory = aggregate_clan_in_memory(container)
    disk = _disk_for(ClanSectionSnapshot(in_memory=in_memory))

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"replies"},
    )

    assert "prompts/202608/missing.md" not in enriched.hint_paths


def test_clan_worker_indexes_known_context_path_suffixes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    member = _agent("research.one", workspace_dir=str(tmp_path))
    container = project_clan_tree([member])[0]
    in_memory = aggregate_clan_in_memory(container)
    target = tmp_path / "artifacts" / "reports" / "findings.md"
    artifact = ArtifactFilePath(
        display_path="reports/findings.md",
        actual_path=str(target),
    )
    disk = ClanDiskSnapshot(
        loaded_sections=frozenset({"context"}),
        members=(),
        replies=(),
        prompts=(),
        context_lanes=(
            ClanContextLane(
                label="ARTIFACTS",
                entries=(
                    ClanContextEntry(
                        key=str(target),
                        label=artifact.display_path,
                        member_labels=(".one",),
                        values=(artifact,),
                    ),
                ),
            ),
        ),
        slow_tool_calls=(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: disk,
    )

    enriched = build_clan_disk_snapshot(
        object(),
        container,
        in_memory,
        sections={"context"},
    )

    assert enriched.hint_paths["reports/findings.md"] == str(target)
    assert "findings.md" not in enriched.hint_paths


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
