"""Launch-boundary coverage for local continuation provenance."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.axe.run_agent_runner import _admit_and_launch
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.continuation_capture import (
    persist_agent_delta,
    persist_monitor_result,
    record_prepared_prompt_capture,
)
from sase.macro.workflow_executor import WorkflowExecutor
from sase.macro.workflow_models import Workflow, WorkflowStep
from tests._prettier_fakes import fake_prettier_missing
from tests.test_fork_workflow import _load_fork_workflow


_AUTHORED_LIMIT_BYTES = 262_144
_CHAIN_LENGTH = 20
_LOCAL_BODY = "L" * 15_000


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _publish_monitor(artifacts_dir: Path, *, parent_node_id: str) -> str:
    artifacts_dir.mkdir(parents=True)
    meta: dict[str, object] = {
        "name": f"builder--mon-{artifacts_dir.name}",
        "monitor_id": f"mon-{artifacts_dir.name}",
        "monitor_command": "just check",
        "monitor_execution_argv": ["just", "check"],
        "monitor_cwd": str(artifacts_dir.parent),
        "monitor_next_output": "none",
        "monitor_state": "completed",
        "monitor_next_action": "continue the work",
        "run_started_at": "2026-11-12T12:00:00Z",
        "workspace_dir": str(artifacts_dir.parent),
        "workspace_num": 1,
        "continuation_parent_node_ids": [parent_node_id],
        "project_name": "proj",
    }
    published = persist_monitor_result(
        artifacts_dir=artifacts_dir,
        meta=meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        stopped_at="2026-11-12T12:00:01Z",
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


def _node_record(artifacts_dir: Path, node_id: str) -> dict[str, object]:
    records = list((artifacts_dir / "continuation" / "nodes").glob("*.json"))
    for path in records:
        node = _read_json(path)
        if node.get("node_id") == node_id:
            return node
    raise AssertionError(f"node {node_id!r} not found in {artifacts_dir}")


def test_twenty_launch_agent_monitor_cycles_keep_only_local_authored_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Exercise real deferred fork expansion and the anonymous prompt prepare path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    fake_prettier_missing(monkeypatch)
    artifacts_root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run"
    artifacts_root.mkdir(parents=True)
    seed_artifacts = artifacts_root / "20261111000000"
    seed_artifacts.mkdir()
    seed_transcript = tmp_path / "seed-builder.md"
    seed_transcript.write_text(
        "## Prompt\n\nSeed builder request\n\n## Response\n\nSeed answer\n",
        encoding="utf-8",
    )
    _write_json(seed_artifacts / "agent_meta.json", {"name": "builder"})
    _write_json(
        seed_artifacts / "done.json",
        {"outcome": "completed", "response_path": str(seed_transcript)},
    )

    previous_monitor_node: str | None = None
    agent_nodes: list[str] = []
    monitor_nodes: list[str] = []
    prompt_sizes: list[int] = []

    for index in range(_CHAIN_LENGTH):
        timestamp = f"20261112{index:06d}"
        agent_dir = artifacts_root / timestamp
        agent_dir.mkdir()
        parent_ids = [previous_monitor_node] if previous_monitor_node else []
        meta: dict[str, object] = {
            "name": "builder",
            "project_name": "proj",
            "workspace_dir": str(tmp_path),
            "workspace_num": 1,
            "continuation_parent_node_ids": parent_ids,
        }
        _write_json(agent_dir / "agent_meta.json", meta)

        authored = (
            "#fork:builder\n"
            + _LOCAL_BODY
            + "\n## Prompt\nheading-looking local data"
            + "\n## Response\nanswer-looking local data"
        )
        runner_state = RunnerRunState(
            cl_name="builder",
            project_file=str(tmp_path / "project.sase"),
            prompt_file="",
            output_path=str(tmp_path / "output.log"),
            workflow_name="tmp_builder",
            timestamp=timestamp,
            update_target="",
            is_home_mode=False,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            project_name="proj",
            artifacts_timestamp=timestamp,
            artifacts_dir=str(agent_dir),
            prompt=authored,
        )
        bootstrap = SimpleNamespace(
            info=SimpleNamespace(
                hold=None,
                local_macros={},
                wait_runners=(),
                queue_capacity_multiplier=1,
                wait_priority=None,
                queue_weight=None,
                queue_weight_explicit=False,
            ),
            agent_meta=meta,
        )

        def launch_preparation(
            state: RunnerRunState,
            _bootstrap: object,
            *,
            loop_index: int = index,
            loop_timestamp: str = timestamp,
            loop_agent_dir: Path = agent_dir,
            loop_meta: dict[str, object] = meta,
            loop_authored: str = authored,
        ) -> None:
            workflow = Workflow(
                name="tmp_builder",
                steps=[WorkflowStep(name="main", agent=state.prompt)],
            )
            executor = WorkflowExecutor(
                workflow,
                {},
                str(loop_agent_dir),
                authored_local_request=state.authored_local_request,
                continuation_segments=tuple(state.launch_continuation_segments),
            )
            prepared = executor._prepare_prompt_step(workflow.steps[0])
            prompt_sizes.append(len(prepared.expanded_prompt.encode("utf-8")))
            record_prepared_prompt_capture(
                loop_agent_dir,
                authored_local_request=prepared.authored_local_request,
                materialized_prompt=prepared.expanded_prompt,
                segments=prepared.continuation_segments,
            )
            context = AgentExecContext(
                cl_name="builder",
                project_file=str(tmp_path / "project.sase"),
                workspace_dir=str(tmp_path),
                output_path=str(tmp_path / "output.log"),
                workspace_num=1,
                timestamp=loop_timestamp,
                update_target="",
                project_name="proj",
                is_home_mode=False,
                artifacts_dir=str(loop_agent_dir),
                artifacts_timestamp=loop_timestamp,
                vcs_tag=None,
                agent_name="builder",
                agent_model=None,
                agent_llm_provider=None,
                agent_vcs_provider=None,
                agent_hidden=False,
                agent_meta=loop_meta,
                local_macros={},
                authored_local_request=prepared.authored_local_request,
                launch_continuation_segments=tuple(state.launch_continuation_segments),
            )
            loop_state = LoopState(
                current_prompt=prepared.expanded_prompt,
                current_role_suffix="",
                current_artifacts_dir=str(loop_agent_dir),
                loop_outcome="completed",
                sdd_spec_path=None,
                original_prompt=loop_authored,
                authored_local_request=prepared.authored_local_request,
                continuation_segments=prepared.continuation_segments,
            )
            published = persist_agent_delta(
                context,
                loop_state,
                status="completed",
                final_response=f"response {loop_index}",
            )
            agent_nodes.append(published.node_id)

            chat_path = tmp_path / f"{loop_timestamp}.md"
            chat_path.write_text(
                f"## Prompt\n\n{prepared.expanded_prompt}\n\n"
                f"## Response\n\nresponse {loop_index}\n",
                encoding="utf-8",
            )
            _write_json(
                loop_agent_dir / "done.json",
                {"outcome": "completed", "response_path": str(chat_path)},
            )

        def admit_slot(*_args, claim, **_kwargs):
            claim()
            return "2026-11-12T12:00:00Z"

        with (
            patch(
                "sase.macro.loader.get_all_workflows",
                return_value={"fork": _load_fork_workflow()},
            ),
            patch("sase.axe.run_agent_runner.wait_for_runner_slot", admit_slot),
            patch("sase.axe.run_agent_runner.record_run_started_at"),
            patch("sase.axe.run_agent_runner.bump_spawn_telemetry"),
            patch("sase.axe.run_agent_runner.launch_agent_run", launch_preparation),
        ):
            _admit_and_launch(runner_state, bootstrap)

        prepared_payload = _read_json(
            agent_dir / "continuation" / "prepared_prompt.json"
        )
        delta_path = next(
            (agent_dir / "continuation" / "records" / "agent_delta").glob("*.json")
        )
        delta = _read_json(delta_path)
        assert prepared_payload["authored_local_request"] == authored
        assert delta["authored_local_request"] == authored
        assert len(authored.encode("utf-8")) < _AUTHORED_LIMIT_BYTES
        prepared_segments = prepared_payload["materialized_local_prompt_segments"]
        assert isinstance(prepared_segments, list)
        assert any(
            isinstance(segment, dict) and segment.get("provenance") == "injected_parent"
            for segment in prepared_segments
        )
        assert any(
            isinstance(segment, dict)
            and segment.get("provenance") == "local_authored"
            and segment.get("utf8_bytes") == len(authored.encode("utf-8"))
            for segment in prepared_segments
        )

        monitor_dir = artifacts_root / f"mon-{timestamp}"
        previous_monitor_node = _publish_monitor(
            monitor_dir, parent_node_id=agent_nodes[-1]
        )
        monitor_nodes.append(previous_monitor_node)

    assert len(agent_nodes) == _CHAIN_LENGTH
    assert len(monitor_nodes) == _CHAIN_LENGTH
    assert max(prompt_sizes) > _AUTHORED_LIMIT_BYTES

    # Each launch is parented on the exact prior monitor result, while each
    # monitor result is parented on its starter agent delta.
    for index, node_id in enumerate(agent_nodes):
        node = _node_record(artifacts_root / f"20261112{index:06d}", node_id)
        expected = [monitor_nodes[index - 1]] if index else []
        assert node["parent_ids"] == expected
    for index, node_id in enumerate(monitor_nodes):
        node = _node_record(artifacts_root / f"mon-20261112{index:06d}", node_id)
        assert node["parent_ids"] == [agent_nodes[index]]
