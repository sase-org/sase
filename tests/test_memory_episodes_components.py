from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sase.core.episode_facade import generate_v2_episode_id
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)
from sase.memory.episodes.components import (
    build_episode_component_plans,
    collect_episode_draft_for_component_plan,
)
from sase.memory.episodes.collector import EpisodeSelector


def test_artifact_component_key_and_episode_id_ignore_projects_root(
    tmp_path: Path,
) -> None:
    left_root = tmp_path / "left" / "projects"
    right_root = tmp_path / "right" / "projects"
    left_chat = _write_chat(tmp_path / "left" / "chats" / "root.md", "Root")
    right_chat = _write_chat(tmp_path / "right" / "chats" / "root.md", "Root")
    left_record = _make_record(
        left_root,
        "20260519120000",
        "root-agent",
        chat_path=left_chat,
    )
    right_record = _make_record(
        right_root,
        "20260519120000",
        "root-agent",
        chat_path=right_chat,
    )

    left_plans = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=left_root,
        scan=_scan(left_root, [left_record]),
        repo_root=tmp_path / "left",
        include_chat_catalog=False,
    )
    right_plans = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=right_root,
        scan=_scan(right_root, [right_record]),
        repo_root=tmp_path / "right",
        include_chat_catalog=False,
    )

    assert len(left_plans) == 1
    assert len(right_plans) == 1
    assert left_plans[0].component_key == (
        "component/artifact/proj/ace-run/20260519120000"
    )
    assert right_plans[0].component_key == left_plans[0].component_key
    assert str(left_root) not in left_plans[0].component_key
    assert str(right_root) not in right_plans[0].component_key
    assert generate_v2_episode_id("proj", left_plans[0].component_key) == (
        generate_v2_episode_id("proj", right_plans[0].component_key)
    )


def test_chat_only_component_key_and_episode_id_ignore_chat_root(
    tmp_path: Path,
) -> None:
    left_chat = _write_chat(
        tmp_path / "left" / "chats" / "solo-260519_120000.md",
        "Same transcript",
    )
    right_chat = _write_chat(
        tmp_path / "right" / "chats" / "solo-260519_120000.md",
        "Same transcript",
    )
    expected_digest = hashlib.sha256(left_chat.read_bytes()).hexdigest()[:16]

    left_plans = build_episode_component_plans(
        EpisodeSelector(project="proj", chat=str(left_chat)),
        projects_root=tmp_path / "left" / "projects",
        scan=_scan(tmp_path / "left" / "projects", []),
        repo_root=tmp_path / "left",
        include_chat_catalog=False,
    )
    right_plans = build_episode_component_plans(
        EpisodeSelector(project="proj", chat=str(right_chat)),
        projects_root=tmp_path / "right" / "projects",
        scan=_scan(tmp_path / "right" / "projects", []),
        repo_root=tmp_path / "right",
        include_chat_catalog=False,
    )

    assert len(left_plans) == 1
    assert len(right_plans) == 1
    assert left_plans[0].component_key == (
        f"component/chat/proj/solo-260519_120000.md/{expected_digest}"
    )
    assert right_plans[0].component_key == left_plans[0].component_key
    assert str(left_chat.parent) not in left_plans[0].component_key
    assert str(right_chat.parent) not in right_plans[0].component_key
    assert generate_v2_episode_id("proj", left_plans[0].component_key) == (
        generate_v2_episode_id("proj", right_plans[0].component_key)
    )


def test_project_scan_splits_unrelated_records_with_shared_weak_refs(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chats_dir = tmp_path / "chats"
    chats_dir.mkdir()
    chat_a = _write_chat(chats_dir / "a-260519_120000.md", "A")
    chat_b = _write_chat(chats_dir / "b-260519_121000.md", "B")
    chat_c = _write_chat(chats_dir / "c-260519_122000.md", "C")
    records = [
        _make_record(
            projects_root,
            "20260519120000",
            "agent-a",
            chat_path=chat_a,
            changespec="shared-cl",
            bead_id="sase-48.2",
            family="shared-family",
        ),
        _make_record(
            projects_root,
            "20260519121000",
            "agent-b",
            chat_path=chat_b,
            changespec="shared-cl",
            bead_id="sase-48.2",
            family="shared-family",
        ),
        _make_record(
            projects_root,
            "20260519122000",
            "agent-c",
            chat_path=chat_c,
            changespec="shared-cl",
            bead_id="sase-48.2",
            family="shared-family",
        ),
    ]
    scan = _scan(projects_root, records)

    plans_a = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
        include_chat_catalog=False,
    )
    plans_b = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
        include_chat_catalog=False,
    )

    assert [plan.to_json() for plan in plans_a] == [plan.to_json() for plan in plans_b]
    assert len(plans_a) == 3
    assert [len(plan.artifact_dirs) for plan in plans_a] == [1, 1, 1]
    assert [len(plan.chat_paths) for plan in plans_a] == [1, 1, 1]
    assert all(plan.weak_refs.changespec_names == ["shared-cl"] for plan in plans_a)
    assert all(plan.weak_refs.bead_ids == ["sase-48.2"] for plan in plans_a)
    assert all(plan.weak_refs.agent_families == ["shared-family"] for plan in plans_a)

    draft = collect_episode_draft_for_component_plan(
        plans_a[0],
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert draft.metadata["component_key"] == plans_a[0].component_key
    assert draft.metadata["agent_record_count"] == "1"
    assert {node.label for node in draft.nodes if node.kind == "agent_run"} == {
        "agent-a"
    }


def test_date_window_seed_pulls_out_of_window_strong_parent_and_fork(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chats_dir = tmp_path / "chats"
    chats_dir.mkdir()
    parent_chat = _write_chat(chats_dir / "parent-260518_090000.md", "Parent")
    child_chat = _write_chat(
        chats_dir / "child-260519_100000.md",
        f"#fork_by_chat:{parent_chat}\n\nChild",
    )
    parent = _make_record(
        projects_root,
        "20260518090000",
        "parent-agent",
        chat_path=parent_chat,
    )
    child = _make_record(
        projects_root,
        "20260519100000",
        "child-agent",
        chat_path=child_chat,
        parent_timestamp="20260518090000",
    )
    scan = _scan(projects_root, [parent, child])

    plans = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
        include_chat_catalog=False,
    )

    assert len(plans) == 1
    assert plans[0].root_timestamp == "20260518090000"
    assert {Path(path).name for path in plans[0].artifact_dirs} == {
        "20260518090000",
        "20260519100000",
    }
    assert {Path(path).name for path in plans[0].chat_paths} == {
        parent_chat.name,
        child_chat.name,
    }
    assert {edge.kind for edge in plans[0].strong_edges} >= {
        "parent_agent",
        "fork_by_chat",
        "record_chat",
    }


def test_component_collect_skips_same_record_retry_root_self_loop(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chats_dir = tmp_path / "chats"
    chats_dir.mkdir()
    chat = _write_chat(chats_dir / "retry-root-260519_120000.md", "Retry root")
    record = _make_record(
        projects_root,
        "20260519120000",
        "retry-root",
        chat_path=chat,
        retry_chain_root_timestamp="20260519120000",
    )
    scan = _scan(projects_root, [record])
    plans = build_episode_component_plans(
        EpisodeSelector(project="proj", since="2026-05-19", until="2026-05-19"),
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
        include_chat_catalog=False,
    )
    assert len(plans) == 1

    draft = collect_episode_draft_for_component_plan(
        plans[0],
        projects_root=projects_root,
        scan=scan,
        repo_root=tmp_path,
    )

    assert not any(
        edge.kind == "retry_root" and edge.from_node_id == edge.to_node_id
        for edge in draft.edges
    )
    assert not any(edge.from_node_id == edge.to_node_id for edge in draft.edges)


def _write_chat(path: Path, prompt: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"## Prompt\n\n{prompt}\n\n## Response\n\nDone.\n",
        encoding="utf-8",
    )
    return path


def _make_record(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    chat_path: Path,
    changespec: str | None = None,
    bead_id: str | None = None,
    family: str | None = None,
    parent_timestamp: str | None = None,
    retry_chain_root_timestamp: str | None = None,
) -> AgentArtifactRecordWire:
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    meta_data = {
        "name": name,
        "chat_path": str(chat_path),
        "changespec_name": changespec,
        "phase_bead_id": bead_id,
        "agent_family": family,
        "parent_timestamp": parent_timestamp,
        "retry_chain_root_timestamp": retry_chain_root_timestamp,
    }
    done_data = {
        "name": name,
        "outcome": "completed",
        "finished_at": 1.0,
        "response_path": str(chat_path),
    }
    _write_json(artifact_dir / "agent_meta.json", meta_data)
    _write_json(artifact_dir / "done.json", done_data)
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(projects_root / "proj"),
        project_file=str(projects_root / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            changespec_name=changespec,
            phase_bead_id=bead_id,
            agent_family=family,
            parent_timestamp=parent_timestamp,
            retry_chain_root_timestamp=retry_chain_root_timestamp,
        ),
        done=DoneMarkerWire(
            outcome="completed",
            finished_at=1.0,
            name=name,
            response_path=str(chat_path),
        ),
        prompt_steps=[],
        has_done_marker=True,
    )


def _scan(
    projects_root: Path,
    records: list[AgentArtifactRecordWire],
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


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
