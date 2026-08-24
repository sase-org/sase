"""Structured chop launch-failure and lifecycle coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_admission_store import RECEIPT_FILENAME, admission_dir
from sase.agent.launch_request_types import DIRECT_TYPED_LAUNCH_KIND
from sase.axe.chop_agents import (
    _record_chop_agent_launch,
    get_chop_agent_records,
)
from sase.axe._chop_lifecycle_completion import agent_completion
from sase.axe.chop_lifecycle import finalize_launched_chop_runs
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import (
    ChopRunEntry,
    chop_run_log_path,
    finish_chop_run,
    read_chop_run,
    start_chop_run,
)
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.notification_gates.paths import REQUEST_FILENAME

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _result_script(tmp_path: Path, name: str, document: dict[str, object]) -> None:
    payload = json.dumps(document)
    make_script(
        tmp_path,
        name,
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )


def _config(tmp_path: Path) -> AxeConfig:
    return AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])


def _launched_entry(
    run_id: str,
    *,
    pid: int,
    launches: list[dict[str, object]] | None = None,
    script_duration_ms: int | None = None,
    typed_admission: dict[str, object] | None = None,
) -> ChopRunEntry:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name="docs",
        chop_name="docs",
        started_at="2026-07-18T12:00:00+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    launch_rows = [{"pid": pid}] if launches is None else launches
    finish_chop_run(
        "docs",
        "docs",
        run_id,
        status="launched",
        finished_at=None,
        duration_ms=1,
        exit_code=0,
        agent_pid=pid,
        launches=launch_rows,
        typed_admission=typed_admission,
        script_duration_ms=script_duration_ms,
    )
    return entry


def _record_agent(
    run_id: str,
    *,
    pid: int,
    timestamp: str = "260718_120000",
    admission_logical_id: str = "",
    admission_fingerprint: str = "",
    proposal_index: int | None = None,
    proposal_id: str = "",
) -> object:
    return _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="docs",
        run_id=run_id,
        pid=pid,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120000",
        cl_name="sase",
        timestamp=timestamp,
        prompt="refresh",
        admission_logical_id=admission_logical_id,
        admission_fingerprint=admission_fingerprint,
        proposal_index=proposal_index,
        proposal_id=proposal_id,
    )


def _typed_bundle(
    tmp_path: Path,
    *,
    logical_id: str,
    outcome: str,
    dedupe_key: str = "",
) -> tuple[Path, dict[str, object]]:
    bundle = tmp_path / f"bundle-{logical_id}"
    metadata = {
        logical_id: {
            "lumberjack_name": "docs",
            "chop_name": "docs",
            "run_id": "run-typed",
            "logical_id": logical_id,
            "source_order": 0,
            "proposal_index": 0,
            "proposal_id": "refresh",
            "agent_name": "refresh",
            "clan": "toobig-0",
            "member_id": "refresh",
            "workspace": "git:sase",
            "dedupe_key": dedupe_key,
            "wait_on": None,
            "wait_name": None,
            "env": {},
        }
    }
    payload: dict[str, object] = {
        "request_id": f"req-{logical_id}",
        "source_surface": "axe_chop",
        "plan_digest": "digest",
        "typed_plan": {
            "schema_version": 1,
            "launch_kind": "axe_chop",
            "selected_project": "sase",
            "content_digest": "digest",
            "units": [],
            "approval_preview": [],
            "diagnostics": [],
        },
        "unit_dispatch_metadata": metadata,
        "dispatch": {"cwd": str(tmp_path), "prompt": "prompt"},
    }
    bundle.mkdir(parents=True)
    (bundle / REQUEST_FILENAME).write_text(
        json.dumps(
            {
                "kind": DIRECT_TYPED_LAUNCH_KIND,
                "request_id": f"req-{logical_id}",
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    root = admission_dir(bundle)
    root.mkdir(parents=True)
    (root / RECEIPT_FILENAME).write_text(
        json.dumps(
            {
                "complete": True,
                "summary": {
                    "total": 1,
                    "eligible": 1 if outcome == "launched" else 0,
                    "launched": 1 if outcome == "launched" else 0,
                    "skipped": 1 if outcome == "skipped" else 0,
                    "condition_errors": 1 if outcome == "condition_error" else 0,
                    "launch_errors": 1 if outcome == "launch_error" else 0,
                },
                "units": [{"logical_id": logical_id, "outcome": outcome}],
            }
        ),
        encoding="utf-8",
    )
    typed_admission = {
        "request_id": f"req-{logical_id}",
        "bundle_dir": str(bundle),
        "plan_digest": "digest",
        "source_surface": "axe_chop",
        "units": [
            {
                "logical_id": logical_id,
                "source_order": 0,
                "proposal_index": 0,
                "proposal_id": "refresh",
                "dedupe_key": dedupe_key,
            }
        ],
    }
    return bundle, typed_admission


def test_launch_failure_releases_only_unlaunched_once_per_keys(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:refresh",
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:polish",
                },
            ],
        },
    )
    calls = 0

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        nonlocal calls
        del prompt, extra_env
        calls += 1
        if calls == 2:
            raise RuntimeError("launcher unavailable")
        return SimpleNamespace(
            pid=100,
            agent_name="actual.refresh",
            timestamp="260718_120000",
        )

    chop = ChopConfig(name="docs", description="")
    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=chop,
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert entry.launches == list(outcome.launches)
    assert entry.launches[0]["dedupe_key"] == "docs:refresh"
    assert entry.launches[0]["artifacts_timestamp"] == "20260718120000"

    reproposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:refresh",
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:polish",
                },
            ]
        },
    )
    once_per = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=reproposed,
        persist=False,
    )
    assert once_per.accepted_indices == (1,)
    assert once_per.decisions[0]["outcome"] == "duplicate"
    assert once_per.decisions[1]["outcome"] == "accept"

    _record_agent(outcome.run_id, pid=100, timestamp="260718_120000")
    failed_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    failed_artifacts.mkdir(parents=True)
    (failed_artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    finalized = read_chop_run("docs", "docs", outcome.run_id)
    assert finalized is not None
    assert finalized.status == "action_failed"
    assert finalized.error is not None
    assert "proposal launch failed: launcher unavailable" in finalized.error

    retried = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=reproposed,
        persist=False,
    )
    assert retried.accepted_indices == (0, 1)


def test_lifecycle_finalizes_completed_agents_and_clears_registry(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000000"
    _launched_entry(run_id, pid=321)
    _record_agent(run_id, pid=321)
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    assert get_chop_agent_records("docs", chop_name="docs", run_id=run_id) == []


def test_lifecycle_reconstructs_typed_admission_launch_from_registry(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120020_000000"
    _bundle, typed_admission = _typed_bundle(
        tmp_path,
        logical_id="unit-1",
        outcome="launched",
        dedupe_key="docs:refresh",
    )
    _launched_entry(
        run_id,
        pid=0,
        launches=[],
        typed_admission=typed_admission,
    )
    _record_agent(
        run_id,
        pid=777,
        admission_logical_id="unit-1",
        admission_fingerprint="fp-1",
        proposal_index=0,
        proposal_id="refresh",
    )
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "typed admission completed: 1 launched, 0 skipped" in output
    assert get_chop_agent_records("docs", chop_name="docs", run_id=run_id) == []


def test_lifecycle_releases_once_per_key_for_skipped_typed_unit(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120021_000000"
    chop = ChopConfig(name="docs", description="")
    proposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:skip",
                }
            ]
        },
    )
    seeded = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=True,
    )
    assert seeded.accepted_indices == (0,)
    _bundle, typed_admission = _typed_bundle(
        tmp_path,
        logical_id="unit-skip",
        outcome="skipped",
        dedupe_key="docs:skip",
    )
    _launched_entry(
        run_id,
        pid=0,
        launches=[],
        typed_admission=typed_admission,
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    retried = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=False,
    )
    assert retried.accepted_indices == (0,)
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Released 1 once-per key(s) after typed admission" in output


def test_lifecycle_preserves_script_duration_ms_through_finalization(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000000"
    _launched_entry(run_id, pid=321, script_duration_ms=250)
    _record_agent(run_id, pid=321)
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    # duration_ms is overwritten with the agent-lifetime span, but
    # script_duration_ms keeps the script's own wall-clock value.
    assert entry.duration_ms != 250
    assert entry.script_duration_ms == 250


def test_lifecycle_releases_only_failed_agents_once_per_key(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120010_000000"
    chop = ChopConfig(name="docs", description="")
    proposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Keep.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:keep",
                },
                {
                    "prompt": "Retry.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:retry",
                },
            ]
        },
    )
    seeded = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=True,
    )
    assert seeded.accepted_indices == (0, 1)
    _launched_entry(
        run_id,
        pid=321,
        launches=[
            {
                "pid": 999,
                "artifacts_timestamp": "20260718120010",
                "dedupe_key": "docs:keep",
            },
            {
                "pid": 654,
                "artifacts_timestamp": "20260718120011",
                "dedupe_key": "docs:retry",
            },
        ],
    )
    _record_agent(run_id, pid=321, timestamp="260718_120010")
    _record_agent(run_id, pid=654, timestamp="260718_120011")
    succeeded_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120010"
    )
    succeeded_artifacts.mkdir(parents=True)
    (succeeded_artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    failed_artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120011"
    )
    failed_artifacts.mkdir(parents=True)
    (failed_artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"

    once_per = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=False,
    )
    assert once_per.accepted_indices == (1,)
    assert once_per.decisions[0]["outcome"] == "duplicate"
    assert once_per.decisions[1]["outcome"] == "accept"


def test_lifecycle_logs_once_per_release_failure_and_still_finalizes(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120012_000000"
    _launched_entry(
        run_id,
        pid=765,
        launches=[
            {
                "pid": 765,
                "artifacts_timestamp": "20260718120012",
                "dedupe_key": "docs:retry",
            }
        ],
    )
    _record_agent(run_id, pid=765, timestamp="260718_120012")
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120012"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "failed"}), encoding="utf-8"
    )

    with patch(
        "sase.axe._chop_lifecycle_keys.release_chop_once_per_keys",
        side_effect=OSError("seen store unavailable"),
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Failed to release once-per keys" in output
    assert "seen store unavailable" in output


def test_lifecycle_does_not_release_keys_for_incomplete_launch_linkage(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120013_000000"
    _launched_entry(
        run_id,
        pid=321,
        launches=[
            {"pid": 321, "dedupe_key": "docs:first"},
            {"pid": 654, "dedupe_key": "docs:missing"},
        ],
    )
    _record_agent(run_id, pid=321)

    with patch("sase.axe._chop_lifecycle_keys.release_chop_once_per_keys") as release:
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "linkage incomplete" in entry.error


def test_lifecycle_fails_dead_agent_without_done_marker(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120001_000000"
    _launched_entry(run_id, pid=654)
    _record_agent(run_id, pid=654)

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch("sase.axe._chop_lifecycle_keys.release_chop_once_per_keys") as release,
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "without completion artifact" in entry.error


def test_lifecycle_uses_done_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120002_000000"
    _launched_entry(run_id, pid=987)
    record = _record_agent(run_id, pid=987)
    child = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=True,
        status="KILLED",
        bundle_path="/archive/20260718120000__c0.json",
    )
    root = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status="DONE",
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch(
            "sase.axe._chop_lifecycle_completion.load_dismissed_bundle_summaries",
            return_value=[child, root],
        ) as load_summaries,
    ):
        completion = agent_completion(record)
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    assert completion.succeeded
    assert "dismissed bundle /archive/20260718120000.json" in completion.detail
    load_summaries.assert_called_with(
        suffixes={"20260718120000"},
        top_level_only=True,
        limit=None,
    )
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"


@pytest.mark.parametrize("status", ["FAILED", "KILLED"])
def test_lifecycle_uses_failed_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = f"20260718T120003_{status.lower()}"
    _launched_entry(run_id, pid=876)
    _record_agent(run_id, pid=876)
    summary = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status=status,
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch(
            "sase.axe._chop_lifecycle_completion.load_dismissed_bundle_summaries",
            return_value=[summary],
        ),
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None
    assert "dismissed bundle /archive/20260718120000.json" in entry.error
    assert f"status {status}" in entry.error
