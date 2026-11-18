"""Typed chop proposal-launch admission coverage."""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_hold import LAUNCH_HOLD_KEY_ENV
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.axe.config import ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.core.agent_launch_wire import AgentUnitWire, HoldFieldsWire, LaunchUnitWire
from sase.feature_flags import override_flags
from sase.macro import extract_vcs_workflow_tag

from tests._axe_chop_proposal_launch_helpers import (
    config,
    known_project_resolver,
    patch_condition_workspace_lease,
    result_script,
)

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_typed_chop_proposal_uses_durable_admission_and_chop_env(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    pwd_capture = tmp_path / "condition-pwd.txt"
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": (
                        "%if::\n"
                        "```bash\n"
                        f"pwd > {shlex.quote(str(pwd_capture))}\n"
                        "```\n"
                        "Review docs."
                    ),
                    "workspace": "git:sase",
                    "agent_name": "refresh",
                    "env": {"MODE": "typed", "SASE_CHOP_NAME": "prompt-owned"},
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: known_project_resolver(repo),
    )
    patch_condition_workspace_lease(monkeypatch, repo)
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(
        prompt: str, *, extra_env: dict[str, str], origin: object = None
    ) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [
            SimpleNamespace(
                pid=501,
                agent_name="refresh",
                workspace_num=2,
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name="ace(run)-260823_120000",
                cl_name="sase",
                timestamp="260823_120000",
                artifacts_dir=str(tmp_path / "artifacts" / "20260823120000"),
            )
        ]

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        launches = launch_chop_proposals(
            lumberjack_name="docs",
            chop_name="docs",
            run_id="run-typed",
            proposals=prepared,
            launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
            launch_agents_from_cwd_fn=_launch,
        )

    assert len(launches) == 1
    assert launches.typed_admission is not None
    assert launches.admission_result.admission_complete
    assert pwd_capture.read_text(encoding="utf-8").strip() == str(repo)
    prompt, env = calls[0]
    assert "%if" not in prompt
    assert "condition-pwd" not in prompt
    assert env["MODE"] == "typed"
    assert env["SASE_CHOP_NAME"] == "docs"
    assert env["SASE_CHOP_RUN_ID"] == "run-typed"
    assert env["SASE_CHOP_PROPOSAL_INDEX"] == "0"
    assert env["SASE_CHOP_ADMISSION_LOGICAL_ID"] == env["SASE_LAUNCH_LOGICAL_ID"]
    assert env["SASE_CHOP_ADMISSION_FINGERPRINT"]
    assert (extract_vcs_workflow_tag(prompt) or "").strip() == "#git:sase"
    notify.assert_not_called()

    from sase.agent.direct_typed_launch import write_typed_launch_bundle
    from sase.agent.launch_request_response import read_launch_request
    from sase.notification_gates.paths import REQUEST_FILENAME

    bundle_dir = Path(launches.typed_admission["bundle_dir"])
    saved_payload = read_launch_request(bundle_dir)
    request_path = bundle_dir / REQUEST_FILENAME
    journal_path = bundle_dir / "launch_admission" / "journal.jsonl"
    request_before = request_path.read_bytes()
    journal_before = journal_path.read_bytes()
    write_typed_launch_bundle(
        prompt=str(saved_payload.get("submitted_prompt") or ""),
        expanded_prompt=str(saved_payload.get("expanded_prompt") or ""),
        typed_plan=saved_payload["typed_plan"],
        source_cwd=str(saved_payload["dispatch"]["cwd"]),
        source_surface=str(saved_payload["source_surface"]),
        selected_project=str(saved_payload["selected_project"]),
        project_file=saved_payload.get("project_file"),
        safe_inputs=saved_payload.get("safe_inputs"),
        unit_dispatch_metadata=saved_payload.get("unit_dispatch_metadata"),
        request_id=str(saved_payload["request_id"]),
        launch_submitted_at="a later invocation timestamp",
    )
    assert request_path.read_bytes() == request_before
    assert journal_path.read_bytes() == journal_before


def test_typed_chop_batch_pause_reopens_frozen_bundle_without_rechecking_skips(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    skipped_condition_runs = tmp_path / "skipped-condition-runs.txt"
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "skipped",
                    "prompt": (
                        "%if::\n```bash\n"
                        f"echo checked >> {shlex.quote(str(skipped_condition_runs))}\n"
                        "exit 1\n```\nSkip this proposal."
                    ),
                    "workspace": "git:sase",
                    "agent_name": "skipped",
                },
                {
                    "id": "first",
                    "prompt": "Review the first document.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                },
                {
                    "id": "second",
                    "prompt": "Review the second document.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                },
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: known_project_resolver(repo),
    )
    patch_condition_workspace_lease(monkeypatch, repo)

    pause = Event()
    launched_indexes: list[int] = []

    def _launch(
        prompt: str, *, extra_env: dict[str, str], origin: object = None
    ) -> list[SimpleNamespace]:
        del prompt, origin
        proposal_index = int(extra_env["SASE_CHOP_PROPOSAL_INDEX"])
        launched_indexes.append(proposal_index)
        if len(launched_indexes) == 1:
            pause.set()
        return [
            SimpleNamespace(
                pid=600 + proposal_index,
                agent_name={1: "first", 2: "second"}[proposal_index],
                workspace_num=2,
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name="ace(run)-260823_120000",
                cl_name="sase",
                timestamp="260823_120000",
                artifacts_dir=str(tmp_path / "artifacts" / str(proposal_index)),
            )
        ]

    started_at = datetime.now(UTC)
    preflight = SimpleNamespace(decision={"checkpoint_key": "docs"})
    created: list[str] = []

    def _launch_batch(*, stop: bool) -> Any:
        return launch_chop_proposals(
            lumberjack_name="docs",
            chop_name="docs",
            run_id="run-typed-pause",
            proposals=prepared,
            launch_agent_from_cwd_fn=None,
            launch_agents_from_cwd_fn=_launch,
            run_started_at=started_at,
            preflight=preflight,
            batch_created_fn=created.append,
            pause_requested_fn=pause.is_set if stop else (lambda: False),
        )

    first = _launch_batch(stop=True)
    assert first.paused is True
    assert first.admission_result.admission_complete is False
    assert launched_indexes == [1]
    assert len(created) == 1

    from sase.axe.chop_batch_store import load_chop_batch

    paused_batch = load_chop_batch("docs", "docs", "run-typed-pause")
    assert paused_batch["status"] == "paused"
    assert [member["status"] for member in paused_batch["members"]] == [
        "skipped",
        "launched",
        "pending",
    ]
    typed_bundle = paused_batch["typed_bundle"]
    assert typed_bundle["bundle_id"] == "axe-chop-run-typed-pause"
    bundle_dir = Path(first.typed_admission["bundle_dir"])
    request_path = bundle_dir / "request.json"
    journal_path = bundle_dir / "launch_admission" / "journal.jsonl"
    request_before = request_path.read_bytes()
    journal_before = journal_path.read_bytes()
    started_path = bundle_dir / "launch_admission" / "started.json"
    started_path.write_text(
        (
            '{"pid": 123, "request_id": "axe-chop-run-typed-pause", '
            f'"plan_digest": "{typed_bundle["bundle_digest"]}"}}'
        ),
        encoding="utf-8",
    )
    with monkeypatch.context() as live_coordinator:
        live_coordinator.setattr(
            "sase.ace.hooks.processes.is_process_running", lambda _pid: True
        )
        live = _launch_batch(stop=False)
    assert live.admission_result.admission_complete is False
    assert launched_indexes == [1]
    started_path.unlink()

    with monkeypatch.context() as no_replanning:
        no_replanning.setattr(
            "sase.agent.launch_request_planning.expand_prompt_for_typed_launch",
            lambda *_args, **_kwargs: pytest.fail(
                "typed replay re-expanded mutable prompt inputs"
            ),
        )
        resumed = _launch_batch(stop=False)
        finished = _launch_batch(stop=False)

    assert resumed.paused is False
    assert resumed.admission_result.admission_complete is True
    assert finished.admission_result.admission_complete is True
    assert launched_indexes == [1, 2]
    assert request_path.read_bytes() == request_before
    assert journal_path.read_bytes().startswith(journal_before)
    assert skipped_condition_runs.read_text(encoding="utf-8").splitlines() == [
        "checked"
    ]
    complete_batch = load_chop_batch("docs", "docs", "run-typed-pause")
    assert complete_batch["status"] == "complete"
    assert [member["status"] for member in complete_batch["members"]] == [
        "skipped",
        "launched",
        "launched",
    ]


def test_typed_chop_recovers_bundle_written_before_outer_batch(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "review",
                    "prompt": "%if::\n```bash\nexit 0\n```\nReview the document.",
                    "workspace": "git:sase",
                    "agent_name": "review",
                },
                {
                    "id": "second",
                    "prompt": (
                        "%if::\n```bash\nexit 0\n```\nReview the second document."
                    ),
                    "workspace": "git:sase",
                    "agent_name": "second",
                },
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: known_project_resolver(repo),
    )
    patch_condition_workspace_lease(monkeypatch, repo)

    from sase.agent import direct_typed_launch

    write_bundle = direct_typed_launch.write_typed_launch_bundle
    writes = 0

    def _write_then_interrupt(*args: Any, **kwargs: Any) -> Any:
        nonlocal writes
        result = write_bundle(*args, **kwargs)
        writes += 1
        if writes == 1:
            raise RuntimeError("simulated interruption after bundle persistence")
        return result

    monkeypatch.setattr(
        direct_typed_launch, "write_typed_launch_bundle", _write_then_interrupt
    )
    calls: list[int] = []
    pause = Event()

    def _launch(
        _prompt: str, *, extra_env: dict[str, str], origin: object = None
    ) -> list[SimpleNamespace]:
        del origin
        calls.append(int(extra_env["SASE_CHOP_PROPOSAL_INDEX"]))
        pause.set()
        return [
            SimpleNamespace(
                pid=800,
                agent_name="review" if calls[-1] == 0 else "second",
                workspace_num=2,
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name="ace(run)-260823_120000",
                cl_name="sase",
                timestamp="260823_120000",
                artifacts_dir=str(tmp_path / "artifacts"),
            )
        ]

    started_at = datetime.now(UTC)
    preflight = SimpleNamespace(decision={"checkpoint_key": "docs"})
    created: list[str] = []

    def _launch_batch() -> Any:
        return launch_chop_proposals(
            lumberjack_name="docs",
            chop_name="docs",
            run_id="run-typed-interrupted-write",
            proposals=prepared,
            launch_agent_from_cwd_fn=None,
            launch_agents_from_cwd_fn=_launch,
            run_started_at=started_at,
            preflight=preflight,
            batch_created_fn=created.append,
            pause_requested_fn=pause.is_set,
        )

    with pytest.raises(RuntimeError, match="after bundle persistence"):
        _launch_batch()

    with monkeypatch.context() as no_replanning:
        no_replanning.setattr(
            "sase.agent.launch_request_planning.expand_prompt_for_typed_launch",
            lambda *_args, **_kwargs: pytest.fail(
                "recovery re-expanded mutable prompt inputs"
            ),
        )
        resumed = _launch_batch()

    assert resumed.paused is True
    assert resumed.admission_result.admission_complete is False
    assert resumed.batch_id == "run-typed-interrupted-write"
    assert calls == [0]
    assert created == ["run-typed-interrupted-write"]


def test_typed_chop_dispatch_fails_closed_without_workspace_metadata() -> None:
    unit = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Review docs.",
            identity="refresh",
            identity_explicit=True,
        ),
    )

    def _launch(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        raise AssertionError("missing workspace metadata reached the launcher")

    dispatcher = make_axe_chop_agent_dispatcher(
        {
            "unit_dispatch_metadata": {
                "unit-1": {
                    "logical_id": "unit-1",
                    "lumberjack_name": "docs",
                    "chop_name": "docs",
                    "run_id": "run-missing-workspace",
                    "env": {},
                }
            }
        },
        launch_agents_from_cwd_fn=_launch,
    )
    assert dispatcher is not None

    ok, identity, message, results = dispatcher(unit, "fp-missing-workspace")

    assert ok is False
    assert identity is None
    assert message == "missing AXE job workspace for unit-1"
    assert results == []


def test_typed_chop_dispatch_carries_launch_hold_key() -> None:
    unit = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Review docs.",
            identity="refresh",
            identity_explicit=True,
            hold=HoldFieldsWire(future=True),
        ),
    )
    calls: list[dict[str, str]] = []

    def _launch(
        prompt: str, *, extra_env: dict[str, str], origin: object = None
    ) -> list[SimpleNamespace]:
        del prompt, origin
        calls.append(dict(extra_env))
        return [SimpleNamespace(pid=501, agent_name="refresh")]

    dispatcher = make_axe_chop_agent_dispatcher(
        {
            "request_id": "req-axe-hold",
            "unit_dispatch_metadata": {
                "unit-1": {
                    "logical_id": "unit-1",
                    "lumberjack_name": "docs",
                    "chop_name": "docs",
                    "run_id": "run-hold",
                    "workspace": "git:sase",
                    "env": {},
                }
            },
        },
        launch_agents_from_cwd_fn=_launch,
    )
    assert dispatcher is not None

    with override_flags():
        ok, identity, message, results = dispatcher(unit, "fp-axe-hold")

    assert ok is True
    assert identity == "refresh"
    assert message is None
    assert len(results) == 1
    assert calls[0][LAUNCH_HOLD_KEY_ENV] == "launch:req-axe-hold/unit-1"


def test_runner_all_skipped_typed_admission_succeeds_without_agent(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\nexit 1\n```\nReview stale docs.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:stale",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: known_project_resolver(repo),
    )
    patch_condition_workspace_lease(monkeypatch, repo)

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_batch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=config(tmp_path),
        )

    assert outcome.status == "action_succeeded"
    launch_batch.assert_not_called()
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", outcome.run_id).read_text(
        encoding="utf-8"
    )
    assert "Typed admission:" in output
    assert "1 skipped" in output
    assert "once-per duplicate" not in output
