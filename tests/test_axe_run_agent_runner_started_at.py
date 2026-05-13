"""Tests for runner run_started_at recording."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    RUNNER,
    base_patches,
    exec_result,
    run_main,
)


class TestRunStartedAtRecording:
    def test_no_wait_runner_records_run_started_at_before_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        seen_run_started_at: list[str] = []

        def run_loop(ctx: Any, _prompt: str) -> Any:
            meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
            run_started_at = meta.get("run_started_at")
            assert isinstance(run_started_at, str)
            assert run_started_at == ctx.agent_meta["run_started_at"]
            seen_run_started_at.append(run_started_at)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        assert len(seen_run_started_at) == 1

    def test_error_before_execution_does_not_record_run_started_at(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        run_loop = MagicMock()
        patches[f"{RUNNER}.resolve_agent_refs_in_prompt"] = MagicMock(
            side_effect=RuntimeError("bad agent ref")
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        run_loop.assert_not_called()
        meta_path = artifacts_dir / "agent_meta.json"
        if meta_path.exists():
            assert "run_started_at" not in json.loads(meta_path.read_text())

    def test_killed_while_waiting_does_not_record_run_started_at(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(wait_duration=1.0)
        )
        patches[f"{RUNNER}.wait_for_dependencies"] = MagicMock(
            side_effect=SystemExit(128 + 15)
        )
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock()

        run_main(patches, tmp_path)

        patches[f"{RUNNER}.run_execution_loop"].assert_not_called()
        meta_path = artifacts_dir / "agent_meta.json"
        if meta_path.exists():
            assert "run_started_at" not in json.loads(meta_path.read_text())

    def test_record_run_started_at_preserves_existing_timestamp(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import record_run_started_at

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"pid": 1, "run_started_at": "2026-05-12T12:00:00+00:00"})
        )
        agent_meta = {"pid": 1}

        recorded = record_run_started_at(str(artifacts_dir), agent_meta)

        assert recorded == "2026-05-12T12:00:00+00:00"
        assert agent_meta["run_started_at"] == "2026-05-12T12:00:00+00:00"
        assert json.loads(meta_path.read_text())["run_started_at"] == (
            "2026-05-12T12:00:00+00:00"
        )

    def test_runner_passes_recorded_run_started_at_to_runtime_formatter(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        record_run_started_at = MagicMock(return_value="2026-05-12T12:00:00+00:00")
        format_runtime = MagicMock(return_value="4m32s")
        notify = MagicMock()
        patches[f"{RUNNER}.record_run_started_at"] = record_run_started_at
        patches[f"{RUNNER}.format_agent_run_runtime"] = format_runtime
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(
            return_value=exec_result(artifacts_dir)
        )
        patches[f"{RUNNER}.send_completion_notification"] = notify
        patches[f"{RUNNER}.all_steps_hidden"] = MagicMock(return_value=False)

        run_main(patches, tmp_path)

        format_runtime.assert_called_once()
        assert format_runtime.call_args.kwargs["launch_timestamp_suffix"] == (
            "20260316_120000"
        )
        assert format_runtime.call_args.kwargs["run_started_at"] == (
            "2026-05-12T12:00:00+00:00"
        )
        notify.assert_called_once()
        assert notify.call_args.kwargs["runtime"] == "4m32s"
