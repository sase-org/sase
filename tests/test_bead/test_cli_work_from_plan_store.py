"""Store and archive coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update


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
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
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
            f"plan:{result.archived_plan_path.relative_to(sidecar).as_posix()}"
        )


def _sidecar_context(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

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


@pytest.mark.parametrize("expect_prompt_snapshot", [True, False])
def test_plan_file_mode_forwards_expect_prompt_snapshot_to_archive(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expect_prompt_snapshot: bool,
) -> None:
    _sidecar_context(project_dir, tmp_path, monkeypatch)
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_archive_plan_file(*_args: object, **archive_kwargs: object) -> object:
        captured.update(archive_kwargs)
        raise RuntimeError("stop after capturing archive_plan_file kwargs")

    monkeypatch.setattr(
        "sase.sdd.plan_archive.archive_plan_file",
        fake_archive_plan_file,
    )

    with pytest.raises(PlanFileWorkError):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
            expect_prompt_snapshot=expect_prompt_snapshot,
        )

    assert captured["expect_prompt_snapshot"] is expect_prompt_snapshot


@pytest.mark.parametrize("expect_prompt_snapshot", [True, False])
def test_plan_file_mode_archives_prompt_link_per_expect_prompt_snapshot(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expect_prompt_snapshot: bool,
) -> None:
    from sase.sdd.artifact_links import parse_sdd_artifact_link

    prompt_refs: list[str] = []

    class Resolver:
        def prompt_url(self, prompt_ref: str) -> str | None:
            prompt_refs.append(prompt_ref)
            return f"https://github.com/sase-org/sase--agents/blob/main/{prompt_ref}"

        def bead_url(self, _bead_id: str) -> None:
            return None

    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: Resolver(),
    )

    _sidecar_context(project_dir, tmp_path, monkeypatch)
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
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
        expect_prompt_snapshot=expect_prompt_snapshot,
    )

    link = parse_sdd_artifact_link(
        result.archived_plan_path.read_text(encoding="utf-8")
    )
    month = result.archived_plan_path.parent.name
    if expect_prompt_snapshot:
        assert link.reference == f"prompts/{month}/rollout.md"
        assert set(prompt_refs) == {f"prompts/{month}/rollout.md"}
        assert (
            link.target
            == f"https://github.com/sase-org/sase--agents/blob/main/prompts/{month}/rollout.md"
        )
    else:
        assert link.reference is None


def test_plan_update_lock_failure_leaves_original_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import write_and_commit_plan_file
    from sase.sdd._repository_transaction import SddRepositoryHealthError

    repo = tmp_path / "plans"
    repo.mkdir()
    plan = repo / "approved.md"
    original = EPIC_PLAN.encode()
    plan.write_bytes(original)
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=repo,
        repo_root=repo,
    )

    @contextmanager
    def unavailable_lock(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        unavailable_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: pytest.fail("commit ran without the store lock"),
    )

    with pytest.raises(SddRepositoryHealthError, match="plan was not changed"):
        write_and_commit_plan_file(
            store,
            workspace_dir=repo,
            plan_path=plan,
            content=EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-1"),
            message="Link approved plan",
        )

    assert plan.read_bytes() == original


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
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
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
