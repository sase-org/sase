from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.continuation_capture._storage import (
    RequiredPortableCaptureError,
    attach_portable_locator,
)
from sase.history.chat_fork.continuation._refs import read_json_ref
from sase.history.chat_fork.continuation._util import ContinuationSourceError

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_required_checkpoint_registration_failure_is_not_success(
    tmp_path: Path,
) -> None:
    from sase.continuation_capture import (
        canonicalize_authored_checkpoint,
        persist_authored_checkpoint,
    )

    authored = canonicalize_authored_checkpoint(
        {"objective": "Keep the parent", "constraints": ["literal"]}
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with patch(
        "sase.core.artifact_file_facade.store_explicit_artifact_file",
        side_effect=OSError("injected index failure"),
    ):
        with pytest.raises(
            RequiredPortableCaptureError, match="injected index failure"
        ):
            persist_authored_checkpoint(artifacts, authored)
    stored = artifacts / "continuation" / "checkpoints"
    assert any(stored.glob("authored-*.json"))
    locators = artifacts / "continuation" / "portable_locators.json"
    assert not locators.exists()


def test_portable_locator_hydrates_after_local_files_are_absent(
    tmp_path: Path,
) -> None:
    from sase.axe.run_agent_exec import LoopState
    from sase.continuation_capture import persist_agent_delta
    from sase.continuation_capture import persist_monitor_result
    from sase.continuation_capture import record_prepared_prompt_capture

    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    starter = Path(ctx.artifacts_dir)
    record_prepared_prompt_capture(
        starter,
        authored_local_request="Continue",
        materialized_prompt="Continue",
        update_meta=False,
    )
    state = LoopState(
        current_prompt="Continue",
        current_role_suffix="",
        current_artifacts_dir=str(starter),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Continue",
    )
    with (
        patch("sase.core.continuation_facade.validate_agent_delta"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        published = persist_agent_delta(ctx, state, status="completed")

    monitor = tmp_path / "monitor"
    monitor.mkdir()
    meta = {
        "monitor_id": "m1",
        "name": "acme--mon",
        "monitor_command": "true",
        "monitor_cwd": str(tmp_path),
        "run_started_at": "2026-09-12T00:00:00Z",
        "monitor_next_action": "finish it",
        "monitor_starter_agent": "acme",
        "monitor_starter_artifacts_dir": str(starter),
        "continuation_parent_node_ids": [published.node_id],
        "workspace_dir": str(tmp_path),
        "workspace_num": 1,
    }
    with (
        patch("sase.core.continuation_facade.validate_monitor_result"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        persist_monitor_result(
            artifacts_dir=monitor,
            meta=meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.0,
            stopped_at="2026-09-12T00:00:01Z",
            diagnostic_manifest=None,
            retained_log={"log_ref": "local:log", "complete": True},
            project_name="proj",
            update_meta=False,
        )

    delta_ref = published.agent_delta_ref
    local_delta = (
        starter / "continuation" / delta_ref.removeprefix("local:continuation/")
    )
    assert local_delta.is_file()
    expected = _json(local_delta)
    local_delta.unlink()
    loaded = read_json_ref(monitor, delta_ref)
    assert loaded["authored_local_request"] == expected["authored_local_request"]
    with pytest.raises(ContinuationSourceError):
        read_json_ref(monitor, "local:continuation/missing.json")


def test_optional_debug_capture_failure_does_not_fail_persist(
    tmp_path: Path,
) -> None:
    path = tmp_path / "debug.txt"
    path.write_text("debug", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with patch(
        "sase.core.artifact_file_facade.store_explicit_artifact_file",
        side_effect=OSError("optional index down"),
    ):
        assert (
            attach_portable_locator(
                artifacts,
                "local:continuation/text/debug.txt",
                path,
                label="debug-transcript",
            )
            is None
        )
