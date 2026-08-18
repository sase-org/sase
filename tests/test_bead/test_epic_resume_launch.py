"""Detached epic-resume launch helper tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_resume_launch import (
    active_epic_resume,
    build_epic_resume_argv,
    epic_resume_origin_from_gate_source,
    submit_epic_resume_task,
)
from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)


def _fake_lease(tmp_path: Path, *, claim_pid: int = 4321) -> OperationalLease:
    checkout = tmp_path / "leased"
    checkout.mkdir(exist_ok=True)
    context = OperationContext(
        project="sase",
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=10,
        checkout_dir=checkout,
        primary_checkout_dir=tmp_path / "primary",
        claim_pid=claim_pid,
        claim_workflow="epic-resume",
    )
    return OperationalLease(
        project="sase",
        workflow="epic-resume",
        holder="epic-resume:sase-p4",
        workspace_num=10,
        checkout_dir=checkout,
        project_file=tmp_path / "sase.sase",
        claim_pid=claim_pid,
        cl_name=None,
        context=context,
    )


def test_build_epic_resume_argv_uses_the_long_yes_to_all_spelling() -> None:
    assert build_epic_resume_argv("sase-p4") == [
        "sase",
        "bead",
        "work",
        "sase-p4",
        "--yes-to-all",
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("tui", "ace"),
        ("telegram", "telegram"),
        ("auto_resolution", "axe"),
        ("host", "api"),
        (None, "api"),
    ],
)
def test_epic_resume_origin_maps_gate_response_sources(
    source: str | None,
    expected: str,
) -> None:
    assert epic_resume_origin_from_gate_source(source) == expected


def test_submit_epic_resume_task_submits_via_leased_checkout(
    tmp_path: Path,
) -> None:
    task = SimpleNamespace(task_id="k7m2xyz")
    lease = _fake_lease(tmp_path)
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ) as acquire,
        patch(
            "sase.workspace_provider.lease.submit_via_lease",
            return_value=task,
        ) as submit_via_lease,
    ):
        submitted = submit_epic_resume_task(
            "sase-p4",
            project="sase",
            origin="telegram",
        )

    assert submitted is task
    acquire.assert_called_once_with(
        "sase",
        workflow="epic-resume",
        holder="epic-resume:sase-p4",
    )
    request = submit_via_lease.call_args.args[0]
    assert list(request.argv) == [
        "sase",
        "bead",
        "work",
        "sase-p4",
        "--yes-to-all",
    ]
    assert request.label == "Epic resume · sase-p4"
    assert request.cwd == str(lease.checkout_dir)
    assert request.origin == "telegram"
    assert request.project == "sase"
    assert request.session_id is None
    assert request.tags == ("epic", "resume")
    assert submit_via_lease.call_args.args[1] is lease


def test_submit_epic_resume_task_reuses_active_resume(
    tmp_path: Path,
) -> None:
    existing = SimpleNamespace(
        task_id="existing",
        command=["sase", "bead", "work", "sase-p4", "--yes-to-all"],
        cwd=str(tmp_path),
        tags=["epic", "resume"],
    )
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[existing]) as read_procs,
        patch("sase.workspace_provider.lease.acquire_operational_lease") as acquire,
    ):
        submitted = submit_epic_resume_task("sase-p4", project="sase")

    assert submitted is existing
    assert read_procs.call_args.kwargs == {
        "status": frozenset({"pending", "running", "settling"}),
        "kind": {"command", "detached"},
    }
    acquire.assert_not_called()


def _proc_row(
    task_id: str,
    *,
    status: str = "running",
    kind: str = "command",
    command: list[str] | None = None,
    tags: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        status=status,
        kind=kind,
        command=command or ["sase", "bead", "work", "sase-p4", "--yes-to-all"],
        tags=tags or ["epic", "resume"],
    )


def test_active_epic_resume_returns_newest_matching_active_row() -> None:
    newest = _proc_row("newest", command=["sase", "bead", "work", "sase-p4"])
    older = _proc_row("older", command=["sase", "bead", "work", "sase-p4"])
    other = _proc_row("other", command=["sase", "bead", "work", "sase-p9"])

    with patch("sase.procs.read_procs", return_value=[other, newest, older]):
        assert active_epic_resume("sase-p4") is newest


def test_active_epic_resume_ignores_non_resume_rows() -> None:
    task_launch = _proc_row(
        "task-launch",
        command=["sase", "bead", "work", "sase-p4"],
        tags=["task", "launch"],
    )
    other_command = _proc_row(
        "other-command",
        command=["sase", "agent", "run", "sase-p4"],
    )
    terminal = _proc_row("terminal", status="success")
    rows = [task_launch, other_command, terminal]

    def read_tasks(*, status: frozenset[str], kind: set[str]) -> list[SimpleNamespace]:
        return [row for row in rows if row.status in status and row.kind in kind]

    with patch("sase.procs.read_procs", side_effect=read_tasks):
        assert active_epic_resume("sase-p4") is None
