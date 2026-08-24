"""Once-per key release coverage for chop action lifecycle finalization."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.chop_lifecycle import finalize_launched_chop_runs
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

from tests._axe_chop_lifecycle_helpers import launched_entry, record_agent
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

    record_agent(outcome.run_id, pid=100, timestamp="260718_120000")
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
    launched_entry(
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
    record_agent(run_id, pid=321, timestamp="260718_120010")
    record_agent(run_id, pid=654, timestamp="260718_120011")
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
    launched_entry(
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
    record_agent(run_id, pid=765, timestamp="260718_120012")
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
    launched_entry(
        run_id,
        pid=321,
        launches=[
            {"pid": 321, "dedupe_key": "docs:first"},
            {"pid": 654, "dedupe_key": "docs:missing"},
        ],
    )
    record_agent(run_id, pid=321)

    with patch("sase.axe._chop_lifecycle_keys.release_chop_once_per_keys") as release:
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "linkage incomplete" in entry.error
