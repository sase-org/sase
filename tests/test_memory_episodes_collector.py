from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.memory.episodes.chat_parse import CHAT_EXCERPT_MAX_CHARS
from sase.memory.episodes.collector import EpisodeSelector, collect_episode_draft


def test_collect_episode_draft_follows_deterministic_source_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    projects_root = home / ".sase" / "projects"
    chats_dir = home / ".sase" / "chats" / "202605"
    chats_dir.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    _write_bead_store(repo_root)

    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n\nBuild source graph collector.\n", encoding="utf-8")
    missing_diff = tmp_path / "deleted.diff"

    planner_chat = chats_dir / "planner-260526_120000.md"
    coder_chat = chats_dir / "coder-260526_121000.md"
    retry_chat = chats_dir / "retry-260526_122000.md"
    planner_chat.write_text(
        "# Chat History - run (planner)\n\n"
        "**Timestamp** 2026-05-26 12:00:00 UTC\n\n"
        "## Linked Chats\n\n"
        f"- 1. code - `{coder_chat}`\n\n"
        "**Plan:** {plan_path}\n\n"
        "## Plan Feedback\n\n"
        "### Round 1\n> tighten the graph\n\n"
        "## Questions & Answers\n\n"
        "### Q1: include retries?\n**Selected:** yes\n\n"
        "## Prompt\n\n"
        "Plan the collector.\n\n"
        "## Response\n\n"
        "Planner response.\n",
        encoding="utf-8",
    )
    coder_chat.write_text(
        "## Prompt\n\n"
        f"#fork_by_chat:{planner_chat} {'implement ' * 80}\n\n"
        "## Response\n\n"
        "Initial implementation failed.\n",
        encoding="utf-8",
    )
    retry_chat.write_text(
        "## Prompt\n\nRetry the implementation.\n\n## Response\n\nRetry succeeded.\n",
        encoding="utf-8",
    )

    records = [
        _make_record(
            projects_root,
            "20260526120000",
            "planner",
            meta={
                "agent_family": "episode-family",
                "role_suffix": "-plan",
                "changespec_name": "episode-cl",
                "phase_bead_id": "sase-45.2",
                "plan_path": str(plan_path),
                "chat_path": str(planner_chat),
                "feedback_submitted_at": ["2026-05-26T12:02:00Z"],
                "questions_submitted_at": ["2026-05-26T12:03:00Z"],
            },
            done={
                "outcome": "completed",
                "finished_at": 1.0,
                "response_path": str(planner_chat),
                "plan_path": str(plan_path),
            },
            extra_files={
                "plan_feedback.jsonl": json.dumps({"round": 0, "feedback": "tighten"})
                + "\n",
                "qa_log.jsonl": json.dumps(
                    {"answers": [{"question": "include retries?", "selected": ["yes"]}]}
                )
                + "\n",
            },
        ),
        _make_record(
            projects_root,
            "20260526121000",
            "coder",
            meta={
                "agent_family": "episode-family",
                "role_suffix": "-code",
                "parent_timestamp": "20260526120000",
                "changespec_name": "episode-cl",
                "phase_bead_id": "sase-45.2",
                "chat_path": str(coder_chat),
            },
            done={
                "outcome": "failed",
                "finished_at": 2.0,
                "response_path": str(coder_chat),
                "diff_path": str(missing_diff),
                "retried_as_timestamp": "20260526122000",
                "retry_chain_root_timestamp": "20260526121000",
            },
        ),
        _make_record(
            projects_root,
            "20260526122000",
            "retry",
            meta={
                "agent_family": "episode-family",
                "role_suffix": "-code",
                "parent_timestamp": "20260526121000",
                "retry_of_timestamp": "20260526121000",
                "retry_chain_root_timestamp": "20260526121000",
                "changespec_name": "episode-cl",
                "phase_bead_id": "sase-45.2",
                "chat_path": str(retry_chat),
            },
            done={
                "outcome": "completed",
                "finished_at": 3.0,
                "response_path": str(retry_chat),
            },
        ),
    ]
    _write_changespec(
        projects_root / "proj" / "proj.sase",
        chat_path=retry_chat,
        diff_path=missing_diff,
        plan_path=plan_path,
    )
    scan = _scan(projects_root, records)

    selector = EpisodeSelector(agent="planner")
    draft_a = collect_episode_draft(
        selector,
        projects_root=projects_root,
        scan=scan,
        repo_root=repo_root,
    )
    draft_b = collect_episode_draft(
        selector,
        projects_root=projects_root,
        scan=scan,
        repo_root=repo_root,
    )

    assert draft_a.to_json() == draft_b.to_json()
    assert draft_a.project == "proj"
    assert draft_a.metadata["agent_record_count"] == "3"
    assert draft_a.metadata["chat_count"] == "3"
    assert draft_a.metadata["changespec_count"] == "1"

    node_kinds = {node.kind for node in draft_a.nodes}
    assert {
        "agent_run",
        "chat",
        "chat_turn",
        "changespec",
        "commit",
        "bead",
        "feedback",
        "question",
        "plan",
    }.issubset(node_kinds)
    edge_kinds = {edge.kind for edge in draft_a.edges}
    assert {
        "agent_family",
        "parent_agent",
        "retry_of",
        "retried_as",
        "linked_chat",
        "fork_by_chat",
        "changespec_chat",
        "bead",
    }.issubset(edge_kinds)

    sources_by_path = {source.path: source for source in draft_a.sources}
    assert sources_by_path[str(missing_diff.resolve())].exists is False
    assert sources_by_path[str(plan_path.resolve())].kind == "plan"
    assert (
        sources_by_path[str((repo_root / "sdd/beads/issues.jsonl").resolve())].kind
        == "bead"
    )
    assert any(
        source.path.endswith("plan_feedback.jsonl") for source in draft_a.sources
    )
    assert any(source.path.endswith("qa_log.jsonl") for source in draft_a.sources)
    assert any(
        turn.prompt_excerpt is not None
        and len(turn.prompt_excerpt) <= CHAT_EXCERPT_MAX_CHARS
        for turn in draft_a.chat_turns
    )

    episode = draft_a.to_episode_wire(title="Collected", summary="Stable")
    assert episode.episode_id.startswith("ep-")
    assert episode.root_source_id == draft_a.root_source_id


def test_project_scan_bounds_transitive_records_but_explicit_agent_does_not(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old_record = _make_record(
        projects_root,
        "20260509010130",
        "old-agent",
        meta={
            "agent_family": "episode-family",
            "changespec_name": "episode-cl",
        },
        done={"outcome": "completed", "finished_at": 1.0},
    )
    window_record = _make_record(
        projects_root,
        "20260519120000",
        "window-agent",
        meta={
            "agent_family": "episode-family",
            "changespec_name": "episode-cl",
        },
        done={"outcome": "completed", "finished_at": 2.0},
    )
    scan = _scan(projects_root, [old_record, window_record])

    project_draft = collect_episode_draft(
        EpisodeSelector(
            project="proj",
            since="2026-05-19",
            until="2026-05-20",
        ),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert project_draft.selector_kind == "project_scan"
    assert project_draft.metadata["agent_record_count"] == "1"
    assert {node.label for node in project_draft.nodes if node.kind == "agent_run"} == {
        "window-agent"
    }
    assert any("20260519120000" in source.path for source in project_draft.sources)
    assert not any("20260509010130" in source.path for source in project_draft.sources)

    explicit_draft = collect_episode_draft(
        EpisodeSelector(
            agent="window-agent",
            since="2026-05-19",
            until="2026-05-20",
        ),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert explicit_draft.selector_kind == "agent"
    assert explicit_draft.metadata["agent_record_count"] == "2"
    assert {
        node.label for node in explicit_draft.nodes if node.kind == "agent_run"
    } == {"old-agent", "window-agent"}


def test_collect_episode_draft_can_start_from_changespec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    projects_root = home / ".sase" / "projects"
    chat_path = home / ".sase" / "chats" / "202605" / "commit-260526_130000.md"
    chat_path.parent.mkdir(parents=True)
    chat_path.write_text(
        "## Prompt\n\nCommit prompt.\n\n## Response\n\nCommit response.\n",
        encoding="utf-8",
    )
    diff_path = tmp_path / "change.diff"
    diff_path.write_text("diff --git a/a b/a\n", encoding="utf-8")
    _write_changespec(
        projects_root / "proj" / "proj.sase",
        chat_path=chat_path,
        diff_path=diff_path,
        plan_path=None,
    )
    scan = _scan(projects_root, [])

    draft = collect_episode_draft(
        EpisodeSelector(changespec="episode-cl"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert draft.selector_kind == "changespec"
    assert {node.kind for node in draft.nodes} >= {"changespec", "commit", "chat"}
    assert {edge.kind for edge in draft.edges} >= {
        "changespec_commit",
        "changespec_chat",
    }
    assert any(source.path == str(chat_path.resolve()) for source in draft.sources)


def test_collect_episode_draft_prefers_episode_trace_hints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    projects_root = home / ".sase" / "projects"
    chats_dir = home / ".sase" / "chats" / "202605"
    chats_dir.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    _write_bead_store(repo_root)

    legacy_chat = chats_dir / "legacy-260526_120000.md"
    trace_chat = chats_dir / "trace-260526_121000.md"
    legacy_chat.write_text(
        "## Prompt\n\nLegacy.\n\n## Response\n\nLegacy response.\n",
        encoding="utf-8",
    )
    trace_chat.write_text(
        "## Prompt\n\nTrace.\n\n## Response\n\nTrace response.\n",
        encoding="utf-8",
    )
    legacy_plan = tmp_path / "legacy-plan.md"
    trace_plan = tmp_path / "trace-plan.md"
    legacy_plan.write_text("# Legacy\n", encoding="utf-8")
    trace_plan.write_text("# Trace\n", encoding="utf-8")

    record = _make_record(
        projects_root,
        "20260526120000",
        "legacy-agent",
        meta={
            "agent_family": "legacy-family",
            "role_suffix": "-plan",
            "changespec_name": "legacy-cl",
            "phase_bead_id": "legacy-bead",
            "plan_path": str(legacy_plan),
            "chat_path": str(legacy_chat),
        },
        done={
            "outcome": "completed",
            "finished_at": 1.0,
            "response_path": str(legacy_chat),
            "plan_path": str(legacy_plan),
        },
    )
    trace_path = Path(record.artifact_dir) / "episode_trace.json"
    _write_json(
        trace_path,
        {
            "schema_version": 1,
            "artifact_timestamp": "20260526120000",
            "agent_name": "trace-agent",
            "agent_family": "trace-family",
            "role_suffix": "-code",
            "chat_path": str(trace_chat),
            "plan_path": str(trace_plan),
            "changespec_names": ["trace-cl"],
            "bead_ids": ["sase-45.2"],
        },
    )
    scan = _scan(projects_root, [record])

    draft = collect_episode_draft(
        EpisodeSelector(agent="trace-agent"),
        projects_root=projects_root,
        scan=scan,
        repo_root=repo_root,
    )

    sources_by_path = {source.path: source for source in draft.sources}
    assert str(trace_chat.resolve()) in sources_by_path
    assert sources_by_path[str(trace_plan.resolve())].kind == "plan"
    assert sources_by_path[str(trace_path.resolve())].id == draft.root_source_id
    assert any(node.label == "trace-agent" for node in draft.nodes)
    assert any(node.label == "trace-cl" for node in draft.nodes)
    assert any(node.label == "sase-45.2" for node in draft.nodes)


def test_collect_episode_draft_falls_back_when_episode_trace_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    projects_root = home / ".sase" / "projects"
    chat_path = home / ".sase" / "chats" / "202605" / "fallback-260526_120000.md"
    chat_path.parent.mkdir(parents=True)
    chat_path.write_text(
        "## Prompt\n\nFallback.\n\n## Response\n\nFallback response.\n",
        encoding="utf-8",
    )
    record = _make_record(
        projects_root,
        "20260526120000",
        "fallback-agent",
        meta={"chat_path": str(chat_path)},
        done={
            "outcome": "completed",
            "finished_at": 1.0,
            "response_path": str(chat_path),
        },
    )
    scan = _scan(projects_root, [record])

    draft = collect_episode_draft(
        EpisodeSelector(agent="fallback-agent"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert any(source.path == str(chat_path.resolve()) for source in draft.sources)
    assert not any(
        source.path.endswith("episode_trace.json") for source in draft.sources
    )


def _make_record(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    meta: dict[str, object],
    done: dict[str, object],
    extra_files: dict[str, str] | None = None,
) -> AgentArtifactRecordWire:
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    meta_data: dict[str, object] = {"name": name, **meta}
    done_data: dict[str, object] = {"name": name, **done}
    _write_json(artifact_dir / "agent_meta.json", meta_data)
    _write_json(artifact_dir / "done.json", done_data)
    for file_name, content in (extra_files or {}).items():
        (artifact_dir / file_name).write_text(content, encoding="utf-8")
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(projects_root / "proj"),
        project_file=str(projects_root / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            agent_family=_str(meta.get("agent_family")),
            role_suffix=_str(meta.get("role_suffix")),
            parent_timestamp=_str(meta.get("parent_timestamp")),
            retry_of_timestamp=_str(meta.get("retry_of_timestamp")),
            retry_chain_root_timestamp=_str(meta.get("retry_chain_root_timestamp")),
            changespec_name=_str(meta.get("changespec_name")),
            phase_bead_id=_str(meta.get("phase_bead_id")),
            plan_path=_str(meta.get("plan_path")),
            feedback_submitted_at=_str_list(meta.get("feedback_submitted_at")),
            questions_submitted_at=_str_list(meta.get("questions_submitted_at")),
        ),
        done=DoneMarkerWire(
            outcome=_str(done.get("outcome")),
            finished_at=float(done["finished_at"]),
            name=name,
            plan_path=_str(done.get("plan_path")),
            diff_path=_str(done.get("diff_path")),
            response_path=_str(done.get("response_path")),
            retried_as_timestamp=_str(done.get("retried_as_timestamp")),
            retry_chain_root_timestamp=_str(done.get("retry_chain_root_timestamp")),
        ),
        prompt_steps=[],
        has_done_marker=True,
    )


def _scan(
    projects_root: Path, records: list[AgentArtifactRecordWire]
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(
            projects_visited=1,
            artifact_dirs_visited=len(records),
            marker_files_parsed=len(records) * 2,
        ),
        records=records,
    )


def _write_changespec(
    path: Path,
    *,
    chat_path: Path,
    diff_path: Path,
    plan_path: Path | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plan_line = f"      | PLAN: {plan_path}\n" if plan_path is not None else ""
    path.write_text(
        "## ChangeSpec\n"
        "NAME: episode-cl\n"
        "DESCRIPTION:\n"
        "  Episode collector work.\n"
        "STATUS: WIP\n"
        "COMMITS:\n"
        "  (1) collect graph\n"
        f"      | CHAT: {chat_path}\n"
        f"      | DIFF: {diff_path}\n"
        f"{plan_line}"
        "TIMESTAMPS:\n"
        "  260526_120000 STATUS WIP -> Draft\n",
        encoding="utf-8",
    )


def _write_bead_store(repo_root: Path) -> None:
    stream_dir = repo_root / "sdd" / "beads" / "events" / "streams"
    stream_dir.mkdir(parents=True)
    issues = repo_root / "sdd" / "beads" / "issues.jsonl"
    issues.parent.mkdir(parents=True, exist_ok=True)
    issues.write_text(
        json.dumps({"id": "sase-45.2", "title": "Phase 2"}) + "\n",
        encoding="utf-8",
    )
    (stream_dir / "sase-45.jsonl").write_text(
        json.dumps({"issue_id": "sase-45.2"}) + "\n",
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
