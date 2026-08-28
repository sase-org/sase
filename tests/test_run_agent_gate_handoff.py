"""Tests for gate handoff workspace claim detection."""

from __future__ import annotations

from collections.abc import Iterable

from sase.axe.run_agent_gate_handoff import gate_handoff_claim_moved
from sase.gate_shell.claims import GATE_WORKSPACE_CLAIM_WORKFLOW
from sase.running_field import WorkspaceClaim


def _claims(*claims: WorkspaceClaim) -> Iterable[WorkspaceClaim]:
    return claims


def test_gate_handoff_claim_moved_matches_gate_claim_and_cl_name() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow=GATE_WORKSPACE_CLAIM_WORKFLOW,
        cl_name="feature",
        pid=999999,
    )

    assert gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        cl_name="feature",
        get_claimed_workspaces=lambda _project_file: _claims(claim),
    )


def test_gate_handoff_claim_moved_does_not_require_live_pid() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow=GATE_WORKSPACE_CLAIM_WORKFLOW,
        cl_name="feature",
        pid=-1,
    )

    assert gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        get_claimed_workspaces=lambda _project_file: _claims(claim),
    )


def test_gate_handoff_claim_moved_rejects_other_workspace() -> None:
    claim = WorkspaceClaim(
        workspace_num=18,
        workflow=GATE_WORKSPACE_CLAIM_WORKFLOW,
        cl_name="feature",
        pid=12345,
    )

    assert not gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        cl_name="feature",
        get_claimed_workspaces=lambda _project_file: _claims(claim),
    )


def test_gate_handoff_claim_moved_rejects_non_gate_workflow() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow="ace-run",
        cl_name="feature",
        pid=12345,
    )

    assert not gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        cl_name="feature",
        get_claimed_workspaces=lambda _project_file: _claims(claim),
    )


def test_gate_handoff_claim_moved_rejects_cl_name_mismatch() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow=GATE_WORKSPACE_CLAIM_WORKFLOW,
        cl_name="other",
        pid=12345,
    )

    assert not gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        cl_name="feature",
        get_claimed_workspaces=lambda _project_file: _claims(claim),
    )


def test_gate_handoff_claim_moved_fails_closed_on_claim_read_errors() -> None:
    def raise_error(_project_file: str) -> Iterable[WorkspaceClaim]:
        raise OSError("project file unavailable")

    assert not gate_handoff_claim_moved(
        "/tmp/project.sase",
        17,
        get_claimed_workspaces=raise_error,
    )
