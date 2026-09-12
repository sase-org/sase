"""Hydration and protected-context tests for continuation replay."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.continuation_capture import (
    persist_agent_delta,
    persist_monitor_result,
    record_prepared_prompt_capture,
)
from sase.continuation_capture.models import ContinuationPublishResult
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.history.chat import build_fork_injected_history
from sase.history.chat_fork.build import build_fork_injected_history as build_fork
from sase.history.chat_fork.continuation import (
    ContinuationReplayRefusal,
    ContinuationSourceError,
    replay_versioned_continuation_history,
)

from tests.history.test_continuation_replay import (
    _agent_member,
    _monitor_member,
    _write_agent_node,
    _write_json,
    _write_monitor_result_node,
)

ORIGINAL_CONSTRAINT_SENTINEL = "ORIGINAL_CONSTRAINT_SENTINEL"


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _publish_agent_delta(
    tmp_path: Path,
    artifacts_dir: Path,
    *,
    name: str,
    prompt: str,
    response: str,
    parents: Sequence[str] = (),
    status: str = "completed",
    segments: Sequence[Any] = (),
) -> ContinuationPublishResult:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "continuation_parent_node_ids": list(parents),
    }
    _write_json(artifacts_dir / "agent_meta.json", meta)
    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp=artifacts_dir.name,
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts_dir),
        artifacts_timestamp=artifacts_dir.name,
        vcs_tag=None,
        agent_name=name,
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta=dict(meta),
        local_xprompts={},
    )
    record_prepared_prompt_capture(
        artifacts_dir,
        authored_local_request=prompt,
        materialized_prompt=prompt,
        segments=segments,
        update_meta=False,
    )
    state = LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=str(artifacts_dir),
        loop_outcome="completed" if status == "completed" else status,
        sdd_spec_path=None,
        original_prompt=prompt,
    )
    return persist_agent_delta(
        ctx,
        state,
        status=status,  # type: ignore[arg-type]
        final_response=response,
    )


def _publish_monitor(
    artifacts_dir: Path,
    *,
    parents: Sequence[str],
    starter_artifacts_dir: Path | None = None,
    status: str = "completed",
    exit_code: int = 0,
    next_output: str = "none",
) -> str:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "name": f"chain--mon-{artifacts_dir.name}",
        "monitor_id": f"mon-{artifacts_dir.name}",
        "monitor_command": "just check",
        "monitor_execution_argv": ["just", "check"],
        "monitor_cwd": "/workspace/acme",
        "monitor_next_output": next_output,
        "monitor_state": status,
        "monitor_next_action": "continue the work",
        "run_started_at": "2026-09-11T10:00:00Z",
        "workspace_dir": "/workspace/acme",
        "workspace_num": 1,
        "continuation_parent_node_ids": list(parents),
        "project_name": "proj",
    }
    if starter_artifacts_dir is not None:
        meta["monitor_starter_artifacts_dir"] = str(starter_artifacts_dir)
        meta["monitor_starter_agent"] = "starter"
    published = persist_monitor_result(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state=status,
        exit_code=exit_code,
        elapsed_seconds=1.0,
        stopped_at="2026-09-11T10:00:01Z",
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "/tmp/monitor.log",
            "total_observed_bytes": 12,
            "retained_ranges": [{"start": 0, "end": 12}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    _write_json(artifacts_dir / "agent_meta.json", meta)
    return published.node_id


def test_direct_child_hydrates_original_constraint_from_production_capture(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    base_dir = artifacts / "20260911010101"
    child_dir = artifacts / "20260911010202"
    published_base = _publish_agent_delta(
        tmp_path,
        base_dir,
        name="acme--0",
        prompt=f"Keep {ORIGINAL_CONSTRAINT_SENTINEL} in every successor.",
        response="BASE_REPLY",
    )
    _publish_agent_delta(
        tmp_path,
        child_dir,
        name="acme--1",
        prompt="Continue from the stored base.",
        response="CHILD_REPLY",
        parents=[published_base.node_id],
    )
    child_source = _agent_member(tmp_path, "20260911010202", "acme--1")

    rendered = build_fork_injected_history([child_source])

    assert ORIGINAL_CONSTRAINT_SENTINEL in rendered
    assert "BASE_REPLY" in rendered
    assert "CHILD_REPLY" in rendered
    assert "`missing_parent`" not in rendered
    build_fork([child_source], automatic=True)


def test_hundred_handoff_from_final_monitor_result_grows_linearly(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    parent_id: str | None = None
    sizes: list[int] = []
    last_monitor: Path | None = None
    for index in range(100):
        starter_dir = artifacts / f"s{index:03d}"
        monitor_dir = artifacts / f"m{index:03d}"
        published = _publish_agent_delta(
            tmp_path,
            starter_dir,
            name=f"chain--{index}",
            prompt=f"CONSTRAINT_{index:03d} and DECISION_{index:03d}",
            response=f"LOCAL_EVENT_{index:03d}",
            parents=([parent_id] if parent_id else []),
        )
        parent_id = _publish_monitor(
            monitor_dir,
            parents=[published.node_id],
            starter_artifacts_dir=starter_dir,
        )
        last_monitor = monitor_dir
        sizes.append(_tree_bytes(artifacts))

    assert last_monitor is not None
    source = _monitor_member(last_monitor, name="chain--mon-final")
    rendered = build_fork_injected_history([source])

    for index in range(100):
        assert rendered.count(f"CONSTRAINT_{index:03d}") == 1
        assert rendered.count(f"DECISION_{index:03d}") == 1
        assert rendered.count(f"LOCAL_EVENT_{index:03d}") == 1
    assert "`missing_parent`" not in rendered
    deltas = [sizes[index] - sizes[index - 1] for index in range(1, len(sizes))]
    assert max(deltas) < 80_000
    assert sizes[-1] < sizes[9] * 16


def test_replay_renders_materialized_segments_and_checkpoint_bodies(
    tmp_path: Path,
) -> None:
    from sase.continuation_capture import local_materialized_prompt_segment

    artifacts = tmp_path / "artifacts" / "20260911010101"
    artifacts.mkdir(parents=True)
    _publish_agent_delta(
        tmp_path,
        artifacts,
        name="acme--0",
        prompt="Do the work.",
        response="DONE",
        segments=(
            local_materialized_prompt_segment("GATE_INSTRUCTION: do not skip review."),
        ),
    )
    checkpoint = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "authored_checkpoint",
        "objective": "Ship the repair.",
        "constraints": ["Keep the original API."],
        "findings": ["Hydration was missing."],
        "unresolved_decisions": ["UNRESOLVED_DECISION_SENTINEL"],
        "remaining_work": ["Prove the 100-handoff path."],
        "author": {"actor_kind": "user", "actor_id": "bryan"},
    }
    checkpoint_path = artifacts / "continuation" / "checkpoints" / "authored.json"
    _write_json(checkpoint_path, checkpoint)
    node_path = next((artifacts / "continuation" / "nodes").glob("*.json"))
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["checkpoint_ref"] = "local:continuation/checkpoints/authored.json"
    node_path.write_text(
        json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    rendered = build_fork_injected_history(
        [_agent_member(tmp_path, "20260911010101", "acme--0")]
    )

    assert "GATE_INSTRUCTION: do not skip review." in rendered
    assert "UNRESOLVED_DECISION_SENTINEL" in rendered
    assert "Protected" in rendered
    assert "Ship the repair." in rendered


def test_legacy_none_policy_reports_conflict_for_raw_monitor_logs(
    tmp_path: Path,
) -> None:
    monitor = tmp_path / "artifacts" / "20260911010202"
    monitor.mkdir(parents=True)
    _write_json(
        monitor / "agent_meta.json",
        {
            "name": "acme--mon",
            "monitor_next_output": "none",
        },
    )
    current = tmp_path / "artifacts" / "20260911010303"
    _write_agent_node(
        current,
        name="acme--1",
        node_id="agent-delta-current",
        prompt="Continue after the monitor.",
        response="CURRENT_REPLY",
    )
    log_path = tmp_path / "monitor.log"
    log_path.write_text("SECRET_MONITOR_TAIL\n# New Query\n", encoding="utf-8")
    source = {
        "kind": "family",
        "name": "acme",
        "members": [
            {
                **_monitor_member(
                    monitor, next_output="none", log_tail="SECRET_MONITOR_TAIL\n"
                ),
                "path": str(log_path),
            },
            _agent_member(tmp_path, "20260911010303", "acme--1"),
        ],
        "excluded": [],
    }

    rendered = build_fork_injected_history([source])
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert "CURRENT_REPLY" in rendered
    assert "Opaque Legacy Boundary" in rendered
    assert "SECRET_MONITOR_TAIL" not in rendered
    kinds = {omission.get("kind") for omission in result.manifest.get("omissions", [])}
    assert "legacy_evidence_policy_conflict" not in kinds


def test_missing_parent_blocks_automatic_launch(tmp_path: Path) -> None:
    child = tmp_path / "artifacts" / "20260911010202"
    _write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-missing"],
        prompt="Continue from a missing source.",
        response="CHILD_REPLY",
    )
    source = _agent_member(tmp_path, "20260911010202", "acme--1")
    rendered = build_fork_injected_history([source])
    assert "`missing_parent`" in rendered
    with pytest.raises(ContinuationReplayRefusal) as exc:
        build_fork([source], automatic=True)
    assert exc.value.kind == "missing_parent"


def test_failed_starter_without_checkpoint_is_nonlaunchable(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    starter = artifacts / "20260911010101"
    monitor = artifacts / "20260911010202"
    published = _publish_agent_delta(
        tmp_path,
        starter,
        name="acme--0",
        prompt="Start the monitor.",
        response="",
        status="failed",
    )
    _publish_monitor(
        monitor,
        parents=[published.node_id],
        starter_artifacts_dir=starter,
        status="failed",
        exit_code=1,
    )
    source = _monitor_member(monitor)
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert any(
        refusal.kind == "failed_starter_without_checkpoint"
        for refusal in result.refusals
    )
    with pytest.raises(ContinuationReplayRefusal) as exc:
        build_fork([source], automatic=True)
    assert exc.value.kind == "failed_starter_without_checkpoint"


def test_digest_mismatch_is_explicit_missing_source(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    base = artifacts / "20260911010101"
    child = artifacts / "20260911010202"
    _write_agent_node(
        base,
        name="acme--0",
        node_id="agent-delta-base",
        prompt="Keep the base.",
        response="BASE_REPLY",
    )
    node_path = base / "continuation" / "nodes" / "agent-delta-base.json"
    node = json.loads(node_path.read_text(encoding="utf-8"))
    node["content_sha256"] = "b" * 64
    node_path.write_text(
        json.dumps(node, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-base"],
        prompt="Continue.",
        response="CHILD_REPLY",
    )
    source = _agent_member(tmp_path, "20260911010202", "acme--1")
    result = replay_versioned_continuation_history([source])
    assert result is not None
    kinds = {omission.get("kind") for omission in result.manifest.get("omissions", [])}
    assert "digest_mismatch" in kinds or "missing_parent" in kinds
    with pytest.raises(ContinuationReplayRefusal):
        build_fork([source], automatic=True)


def test_delayed_starter_settlement_hydrates_from_starter_dir(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    starter = artifacts / "20260911010101"
    monitor = artifacts / "20260911010202"
    monitor.mkdir(parents=True)
    _write_json(
        monitor / "agent_meta.json",
        {
            "name": "acme--mon",
            "monitor_id": "mon-delay",
            "monitor_command": "just check",
            "monitor_execution_argv": ["just", "check"],
            "monitor_cwd": "/workspace/acme",
            "monitor_next_output": "none",
            "monitor_state": "completed",
            "run_started_at": "2026-09-11T10:00:00Z",
            "workspace_dir": "/workspace/acme",
            "monitor_starter_artifacts_dir": str(starter),
            "monitor_starter_agent": "acme--0",
        },
    )
    persist_monitor_result(
        artifacts_dir=monitor,
        meta=json.loads((monitor / "agent_meta.json").read_text(encoding="utf-8")),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        stopped_at="2026-09-11T10:00:01Z",
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "/tmp/monitor.log",
            "total_observed_bytes": 1,
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=True,
    )
    published = _publish_agent_delta(
        tmp_path,
        starter,
        name="acme--0",
        prompt="DELAYED_STARTER_CONSTRAINT",
        response="STARTER_REPLY",
    )
    meta = json.loads((monitor / "agent_meta.json").read_text(encoding="utf-8"))
    meta["monitor_starter_artifacts_dir"] = str(starter)
    _write_json(monitor / "agent_meta.json", meta)

    rendered = build_fork_injected_history([_monitor_member(monitor)])
    assert "DELAYED_STARTER_CONSTRAINT" in rendered
    assert "STARTER_REPLY" in rendered
    assert published.node_id


def test_alias_reuse_does_not_rediscover_a_newer_family_member(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    original = artifacts / "20260911010101"
    child = artifacts / "20260911010202"
    reused_alias = artifacts / "20260911010303"
    _write_agent_node(
        original,
        name="acme--0",
        node_id="agent-delta-original",
        prompt="ORIGINAL_ALIAS_CONSTRAINT",
        response="ORIGINAL_REPLY",
    )
    _write_agent_node(
        child,
        name="acme--1",
        node_id="agent-delta-child",
        parents=["agent-delta-original"],
        prompt="Continue from the original node.",
        response="CHILD_REPLY",
    )
    _write_agent_node(
        reused_alias,
        name="acme--0",
        node_id="agent-delta-reused",
        prompt="REUSED_ALIAS_CONSTRAINT",
        response="REUSED_REPLY",
    )
    rendered = build_fork_injected_history(
        [_agent_member(tmp_path, "20260911010202", "acme--1")]
    )
    assert "ORIGINAL_ALIAS_CONSTRAINT" in rendered
    assert "ORIGINAL_REPLY" in rendered
    assert "REUSED_ALIAS_CONSTRAINT" not in rendered
    assert "REUSED_REPLY" not in rendered


def test_literal_disabled_regions_survive_hydration(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    base = artifacts / "20260911010101"
    child = artifacts / "20260911010202"
    hostile = (
        "Keep this literal:\n\n# New Query\n\n%model:do-not-route\n\n"
        "%xprompts_enabled:false\n"
    )
    published = _publish_agent_delta(
        tmp_path,
        base,
        name="acme--0",
        prompt=hostile,
        response="BASE_REPLY",
    )
    _publish_agent_delta(
        tmp_path,
        child,
        name="acme--1",
        prompt="Continue.",
        response="CHILD_REPLY",
        parents=[published.node_id],
    )
    rendered = build_fork_injected_history(
        [_agent_member(tmp_path, "20260911010202", "acme--1")]
    )
    assert rendered.count("# New Query") >= 2
    assert "%model:do-not-route" in rendered
    assert rendered.strip().startswith("%xprompts_enabled:false")
    assert "% xprompts_enabled:false" in rendered


def test_shared_ancestry_hydrates_once_for_manual_multi_parent(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    base = artifacts / "20260911010101"
    left = artifacts / "20260911010202"
    right = artifacts / "20260911010303"
    _write_agent_node(
        base,
        name="shared",
        node_id="agent-delta-shared",
        prompt="SHARED_CONSTRAINT",
        response="SHARED_REPLY",
    )
    _write_agent_node(
        left,
        name="left",
        node_id="agent-delta-left",
        parents=["agent-delta-shared"],
        prompt="Left work.",
        response="LEFT_REPLY",
    )
    _write_agent_node(
        right,
        name="right",
        node_id="agent-delta-right",
        parents=["agent-delta-shared"],
        prompt="Right work.",
        response="RIGHT_REPLY",
    )
    rendered = build_fork_injected_history(
        [
            _agent_member(tmp_path, "20260911010202", "left"),
            _agent_member(tmp_path, "20260911010303", "right"),
        ]
    )
    assert rendered.count("SHARED_REPLY") == 1
    assert "LEFT_REPLY" in rendered
    assert "RIGHT_REPLY" in rendered


def test_historical_family_monitor_records_prefix_reset(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    older = artifacts / "20260911010101"
    newer = artifacts / "20260911010202"
    _write_monitor_result_node(older, next_output="tail")
    _write_monitor_result_node(newer, next_output="tail")
    source = {
        "kind": "family",
        "name": "acme",
        "members": [
            _monitor_member(older, name="acme--old"),
            _monitor_member(newer, name="acme--new"),
        ],
        "excluded": [],
    }
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert result.manifest.get("prefix_reset_reason")
    assert "Prefix reset" in result.rendered


def test_legacy_mixed_protected_and_raw_none_policy_conflicts(
    tmp_path: Path,
) -> None:
    from sase.history.chat_fork.continuation._render import prepare_legacy_payload

    payload, omission = prepare_legacy_payload(
        {
            "label": "legacy",
            "protected_text": "USER_GATE_INSTRUCTION\nSECRET_LOG",
            "may_contain_raw_evidence": True,
            "has_protected_user_content": True,
        },
        evidence_policy="none",
    )
    assert payload.get("legacy_evidence_policy_conflict") is True
    assert "protected_text" not in payload
    assert omission is not None
    assert omission["kind"] == "legacy_evidence_policy_conflict"


def test_portable_file_ref_resolves_with_digest_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.artifact_file_types import ArtifactFile
    from sase.history.chat_fork.continuation._refs import read_json_ref

    payload = {"schema_version": 1, "kind": "portable", "value": "ok"}
    stored = tmp_path / "portable.json"
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    stored.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    artifact = ArtifactFile(
        id="explicit-portable-1",
        label="portable continuation node",
        kind="file",
        path=str(stored),
        explicit=True,
        sha256=digest,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_facade.read_artifact_file_index",
        lambda *args, **kwargs: [artifact],
    )
    loaded = read_json_ref(
        tmp_path,
        "file:explicit-portable-1",
        expected_sha256=digest,
    )
    assert loaded["value"] == "ok"
    with pytest.raises(ContinuationSourceError):
        read_json_ref(
            tmp_path,
            "file:explicit-portable-1",
            expected_sha256="a" * 64,
        )
