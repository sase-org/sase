"""Bead claim store-lock serialization tests."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.claims import claim_bead_for_waiting_agent
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.sync import bead_state_is_clean
from sase.sdd._repository_transaction import integrate_sdd_repository
from sase.sdd._repository_types import SddIntegrationOutcome, SddIntegrationStatus
from sase.sdd.store import SddStore

from .claims_test_helpers import (
    install_writable_bead_store,
    project_with_committed_phase,
)


def test_wait_claim_holds_store_lock_from_materialization_through_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    install_writable_bead_store(monkeypatch, beads_dir)
    materialized = threading.Event()
    allow_commit = threading.Event()
    integration_finished = threading.Event()
    original_claim = BeadProject.claim_for_agent_wait

    def pause_after_materialization(
        self: BeadProject,
        claimed_bead_id: str,
        agent_name: str,
    ) -> tuple[object, bool]:
        result = original_claim(self, claimed_bead_id, agent_name)
        materialized.set()
        assert allow_commit.wait(2.0)
        return result

    monkeypatch.setattr(
        BeadProject, "claim_for_agent_wait", pause_after_materialization
    )
    claim_results: list[bool] = []
    integration_results: list[SddIntegrationOutcome] = []

    claim_thread = threading.Thread(
        target=lambda: claim_results.append(
            claim_bead_for_waiting_agent(
                project_name="proj",
                bead_id=bead_id,
                agent_name="worker",
            )
        )
    )

    def integrate() -> None:
        integration_results.append(
            integrate_sdd_repository(
                tmp_path,
                beads_dir=beads_dir,
                fetch=False,
                op_prefix="test.claim_serialization",
            )
        )
        integration_finished.set()

    claim_thread.start()
    assert materialized.wait(2.0)
    integration_thread = threading.Thread(target=integrate)
    integration_thread.start()
    assert not integration_finished.wait(0.1)

    allow_commit.set()
    claim_thread.join(timeout=2.0)
    integration_thread.join(timeout=2.0)

    assert claim_results == [True]
    assert integration_finished.is_set()
    assert integration_results[0].status is SddIntegrationStatus.SUCCESS
    assert integration_results[0].status is not SddIntegrationStatus.UNRECOVERABLE


def test_launch_claim_holds_store_lock_from_materialization_through_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    store = SddStore(
        storage="separate_repo",
        sdd_dir=beads_dir.parent,
        repo_root=tmp_path,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.bead.sync.publish_bead_claim",
        lambda *_args, **_kwargs: None,
    )
    materialized = threading.Event()
    allow_commit = threading.Event()
    integration_finished = threading.Event()
    original_claim = BeadProject.claim_for_agent_launch

    def pause_after_materialization(
        self: BeadProject,
        claimed_bead_id: str,
        agent_name: str,
    ) -> object:
        result = original_claim(self, claimed_bead_id, agent_name)
        materialized.set()
        assert allow_commit.wait(2.0)
        return result

    monkeypatch.setattr(
        BeadProject, "claim_for_agent_launch", pause_after_materialization
    )
    launch_results: list[object] = []
    integration_results: list[SddIntegrationOutcome] = []

    claim_thread = threading.Thread(
        target=lambda: launch_results.append(
            claim_bead_for_agent_launch(
                agent_name="worker",
                bead_id=bead_id,
                workspace_dir=str(tmp_path),
                workspace_num=1,
                artifacts_dir=str(tmp_path / "artifacts"),
            )
        )
    )

    def integrate() -> None:
        integration_results.append(
            integrate_sdd_repository(
                tmp_path,
                beads_dir=beads_dir,
                fetch=False,
                op_prefix="test.launch_claim_serialization",
            )
        )
        integration_finished.set()

    claim_thread.start()
    assert materialized.wait(2.0)
    integration_thread = threading.Thread(target=integrate)
    integration_thread.start()
    assert not integration_finished.wait(0.1)

    allow_commit.set()
    claim_thread.join(timeout=5.0)
    integration_thread.join(timeout=5.0)

    assert integration_finished.is_set()
    assert integration_results[0].status is SddIntegrationStatus.SUCCESS
    assert len(launch_results) == 1
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.IN_PROGRESS, "worker")
    assert bead_state_is_clean(beads_dir)
