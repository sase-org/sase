"""Store, archive, and push coverage for plan-file ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def test_plan_file_mode_uses_sidecar_store(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
    )
    location = _BeadsLocation(
        root=sidecar,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.archived_plan_path.is_relative_to(sidecar)
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.show(result.epic_id or "").design == (
            result.archived_plan_path.relative_to(project_dir).as_posix()
        )


def test_plan_file_refuses_poisoned_sidecar_before_archive_or_bead_open(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "approved.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    sidecar.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=sidecar,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "seed"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    (sidecar / "beads").mkdir()
    (sidecar / ".git/rebase-merge").mkdir()
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
    )
    location = _BeadsLocation(
        root=sidecar,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_archive.archive_plan_file",
        lambda *_args, **_kwargs: pytest.fail("poisoned store was archived into"),
    )

    with pytest.raises(PlanFileWorkError, match="not safe to write") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    assert excinfo.value.resume_command == f"sase bead work {source} --yes"
    assert not (sidecar / "plans").exists()


def test_neutral_gate_plan_archives_under_original_stem(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = project_dir / "interaction_requests" / "epic_plan" / "request"
    bundle.mkdir(parents=True)
    source = bundle / "plan.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    original = project_dir / "proposals" / "canonical_rollout.md"
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "epic_plan",
                "payload": {
                    "original_plan_file": str(original),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.archived_plan_path.name == "canonical_rollout.md"


def test_plan_file_rejects_preserved_archive_identity_mismatch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "incoming" / "rollout.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")
    archived = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "---\ntier: tale\ntitle: Different plan\n---\n# Plan\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sase.sdd.files.get_yyyymm", lambda: "202607")

    with pytest.raises(PlanFileWorkError, match="archive collision") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    message = str(excinfo.value)
    assert str(source) in message
    assert str(archived) in message
    assert excinfo.value.resume_command == f"sase bead work {archived} --yes"


@pytest.mark.parametrize(
    ("no_push", "expected_pushes"),
    [(False, [True]), (True, [])],
)
def test_plan_file_success_runs_one_blocking_store_push_after_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_push: bool,
    expected_pushes: list[bool],
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
    )
    location = _BeadsLocation(
        root=sidecar,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )
    events: list[tuple[str, object]] = []

    def commit_store(
        _store: SddStore,
        message: str,
        *,
        paths: list[Path],
        push_after_commit: bool,
    ) -> bool:
        del paths
        events.append(("commit", (message, push_after_commit)))
        return True

    def launch(_project: BeadProject, _epic_id: str, **kwargs: object) -> bool:
        events.append(("launch", (kwargs["no_push"], kwargs["defer_push"])))
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        lambda _store, *, push_after_commit: events.append(("push", push_after_commit)),
    )

    work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=no_push,
        render=False,
    )

    commit_events = [value for kind, value in events if kind == "commit"]
    assert len(commit_events) == 2
    assert all(
        push_after_commit is False for _message, push_after_commit in commit_events
    )
    assert ("launch", (no_push, True)) in events
    assert [value for kind, value in events if kind == "push"] == expected_pushes
    if expected_pushes:
        assert events[-1] == ("push", True)
