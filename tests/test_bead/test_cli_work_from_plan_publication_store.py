"""Store publication coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_publication_helpers import (
    stable_plan_formatting,
)


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    stable_plan_formatting(monkeypatch)


def test_plan_file_publication_uses_split_beads_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import publish_epic_graph_before_launch

    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.test:project--plans.git",
        beads_dir=beads,
    )
    pushed: list[Path] = []

    def fake_push(path: Path, **_kwargs: object) -> SimpleNamespace:
        pushed.append(path)
        return SimpleNamespace(pushed=True, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)

    assert publish_epic_graph_before_launch(store, no_push=False)
    assert pushed == [beads]


def test_push_store_after_launch_pushes_plans_and_beads_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launch push must reach sidecar remotes synchronously, not a queue."""

    from sase.bead.cli_work_from_plan_store import push_store_after_launch

    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.test:project--plans.git",
        beads_dir=beads,
        beads_remote_url="git@example.test:project--beads.git",
    )
    pushed: list[Path] = []

    def fake_push(path: Path, **_kwargs: object) -> SimpleNamespace:
        pushed.append(path)
        return SimpleNamespace(pushed=True, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda *_args, **_kwargs: pytest.fail("launch push must be synchronous"),
    )

    push_store_after_launch(store, no_push=False)

    assert pushed == [plans, beads]


def test_push_store_after_launch_notifies_when_plans_push_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import push_store_after_launch

    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    archived = plans / "202607" / "rollout.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("# Plan\n", encoding="utf-8")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.test:project--plans.git",
        beads_dir=beads,
        beads_remote_url="git@example.test:project--beads.git",
    )
    pushed: list[Path] = []
    notified: list[tuple[object, ...]] = []
    log_path = tmp_path / "sync.log"

    def fake_push(path: Path, **_kwargs: object) -> SimpleNamespace:
        pushed.append(path)
        if path == plans:
            return SimpleNamespace(
                pushed=False,
                skipped_no_remote=False,
                error="git push rejected",
                log_path=log_path,
            )
        return SimpleNamespace(pushed=True, skipped_no_remote=False, error=None)

    def notify(*args: object, **kwargs: object) -> None:
        notified.append((*args, kwargs))

    monkeypatch.setenv("SASE_AGENT_CL_NAME", "gh_sase-org__sase")
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)
    monkeypatch.setattr("sase.notifications.notify_workflow_complete", notify)

    push_store_after_launch(
        store,
        no_push=False,
        archived_plan_path=archived,
    )

    assert pushed == [plans, beads]
    assert len(notified) == 1
    sender, cl_name, success, notes, kwargs = notified[0]
    assert sender == "plan-archive"
    assert cl_name == "gh_sase-org__sase"
    assert success is False
    assert any("Failed to archive approved plan: rollout.md" in note for note in notes)
    assert any("git push rejected" in note for note in notes)
    assert str(log_path) in "\n".join(notes)
    assert kwargs["extra_files"] == [str(archived)]


def test_plan_file_publication_passes_worker_lock_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import publish_epic_graph_before_launch
    from sase.bead.sync import PUBLICATION_WORKER_LOCK_WAIT_SECONDS, _PushOutcome

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=tmp_path / "plans",
        repo_root=tmp_path / "plans",
        remote_url="git@example.test:project--plans.git",
        beads_dir=tmp_path / "beads",
    )
    calls: list[dict[str, object]] = []

    def fake_push(_path: Path, **kwargs: object) -> _PushOutcome:
        calls.append(kwargs)
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)

    assert publish_epic_graph_before_launch(store, no_push=False) is True
    assert calls == [{"worker_lock_wait": PUBLICATION_WORKER_LOCK_WAIT_SECONDS}]


def test_plan_file_publication_returns_when_concurrent_worker_published_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import publish_epic_graph_before_launch
    from sase.bead.sync import _PushOutcome

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=tmp_path / "plans",
        repo_root=tmp_path / "plans",
        remote_url="git@example.test:project--plans.git",
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda *_args, **_kwargs: _PushOutcome(
            pushed=True,
            skipped_no_remote=False,
            error=None,
        ),
    )

    assert publish_epic_graph_before_launch(store, no_push=False) is True


def test_plan_file_publication_reports_true_contention_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import publish_epic_graph_before_launch
    from sase.bead.sync import _PushOutcome

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=tmp_path / "plans",
        repo_root=tmp_path / "plans",
        remote_url="git@example.test:project--plans.git",
    )
    log_path = tmp_path / "sync.log"
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda *_args, **_kwargs: _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=None,
            skipped_locked=True,
            log_path=log_path,
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        publish_epic_graph_before_launch(store, no_push=False)

    message = str(excinfo.value)
    assert "held the store lock" in message
    assert f"managed sync log: {log_path}" in message
