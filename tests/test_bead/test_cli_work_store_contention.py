"""Bead-store lock contention behaviour for ``sase bead work`` launches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead import _store_contention
from sase.bead import cli as bead_cli
from sase.bead._project_mutations import BeadProjectMutationMixin
from sase.bead._store_contention import (
    BEAD_MUTATION_HOLDER_FILENAME,
    BeadStoreContentionError,
    retry_bead_store_mutation,
)
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.work import VCSLaunchContext

from .cli_work_helpers import FakeLaunchResult, make_args, seed_diamond, seed_task

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")

LOCK_TIMEOUT_MESSAGE = (
    "lock_timeout: timed out after 600000ms waiting for exclusive lock "
    "/store/beads.db; holder: pid=4242 operation=bead_update "
    "acquired_at=2026-08-01T12:34:52.000Z for store /store"
)


def beads_dir(project_dir: Path) -> Path:
    with BeadProject(project_dir) as proj:
        return Path(proj.beads_dir)


def write_holder(project_dir: Path, *, pid: int = 4242) -> None:
    """Record a bead-mutation lock holder the launch can name."""
    (beads_dir(project_dir) / BEAD_MUTATION_HOLDER_FILENAME).write_text(
        json.dumps(
            {
                "pid": pid,
                "operation": "bead_preclaim_epic_work",
                "acquired_at": "2026-08-01T12:34:52.000Z",
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_store_contention, "_sleep_before_retry", lambda _attempt: None)


@pytest.fixture(autouse=True)
def task_vcs_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )


def fail_with_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    *,
    project_dir: Path,
    failures: int,
) -> list[int]:
    """Make the first *failures* calls of a mutation expire on the store lock.

    The holder file is written as each expiry is raised, mirroring the core:
    it exists only while some other process actually owns the lock.
    """
    real = getattr(BeadProjectMutationMixin, method)
    calls: list[int] = []

    def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(len(calls) + 1)
        if len(calls) <= failures:
            write_holder(project_dir)
            raise ValueError(LOCK_TIMEOUT_MESSAGE)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(BeadProjectMutationMixin, method, flaky)
    return calls


def test_task_preclaim_retries_past_a_contended_store(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    calls = fail_with_lock_timeout(
        monkeypatch, "update", project_dir=project_dir, failures=1
    )
    launched: list[str] = []

    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: launched.append("launch") or [FakeLaunchResult()],
    )

    bead_cli.handle_bead_work(make_args(task_id, yes=True))

    assert len(calls) == 2
    assert launched == ["launch"]
    with BeadProject(project_dir) as proj:
        task = proj.show(task_id)
        assert (task.status, task.assignee) == (Status.IN_PROGRESS, task_id)
    out = capsys.readouterr().out
    assert f"Waiting for the bead store to preclaim task {task_id}" in out
    assert "pid=4242" in out


def test_task_preclaim_exhaustion_reports_holder_and_claims_nothing(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_id = seed_task(project_dir)
    fail_with_lock_timeout(monkeypatch, "update", project_dir=project_dir, failures=99)

    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: pytest.fail("contended launch must not checkpoint"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        lambda *_args, **_kwargs: pytest.fail("contended launch must not spawn"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(task_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        task = proj.show(task_id)
        assert (task.status, task.assignee) == (Status.READY, "")
    err = capsys.readouterr().err
    assert f"gave up waiting for the bead store to preclaim task {task_id}" in err
    assert "pid=4242" in err
    assert f"`sase bead work {task_id}`" in err


def test_epic_preclaim_exhaustion_rolls_back_the_ready_flag(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    fail_with_lock_timeout(
        monkeypatch, "preclaim_epic_work", project_dir=project_dir, failures=99
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        lambda *_args, **_kwargs: pytest.fail("contended launch must not spawn"),
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_work(make_args(epic_id, yes=True))
    assert excinfo.value.code == 1

    with BeadProject(project_dir) as proj:
        assert proj.show(epic_id).is_ready_to_work is False
        for phase_id in phase_ids:
            phase = proj.show(phase_id)
            assert (phase.status, phase.assignee) == (Status.OPEN, "")
    err = capsys.readouterr().err
    assert f"gave up waiting for the bead store to preclaim epic {epic_id}" in err
    assert "pid=4242" in err


def test_retry_leaves_non_contention_failures_untouched(tmp_path: Path) -> None:
    calls: list[int] = []

    def boom() -> None:
        calls.append(len(calls) + 1)
        raise ValueError("validation: assignee is not a known agent")

    with pytest.raises(ValueError, match="validation"):
        retry_bead_store_mutation(
            boom,
            beads_dir=tmp_path,
            what="preclaim task sase-d8",
            resume_command="sase bead work sase-d8",
        )

    assert calls == [1]


@pytest.mark.parametrize("holder_text", [None, "{not json", '["not a record"]'])
def test_retry_reports_an_unrecorded_holder_when_metadata_is_unusable(
    holder_text: str | None,
    tmp_path: Path,
) -> None:
    if holder_text is not None:
        (tmp_path / BEAD_MUTATION_HOLDER_FILENAME).write_text(
            holder_text, encoding="utf-8"
        )

    def boom() -> None:
        raise ValueError(LOCK_TIMEOUT_MESSAGE)

    with pytest.raises(BeadStoreContentionError) as excinfo:
        retry_bead_store_mutation(
            boom,
            beads_dir=tmp_path,
            what="preclaim task sase-d8",
            resume_command="sase bead work sase-d8",
            attempts=1,
        )

    assert "an unrecorded process" in str(excinfo.value)
