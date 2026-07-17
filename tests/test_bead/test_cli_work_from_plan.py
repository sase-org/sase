"""Plan-file mode coverage for ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import (
    PlanFileWorkError,
    is_plan_file_target,
    work_from_plan_file,
)
from sase.bead.cli_work_handler import BeadWorkError, handle_bead_work
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore


EPIC_PLAN = """---
tier: epic
title: Plan-file rollout
goal: Exercise the host-owned plan-file launch.
phases:
  - id: core
    title: Build the core
    depends_on: []
  - id: cli
    title: Add the CLI
    depends_on: [core]
  - id: verify
    title: Verify the result
    depends_on: [core, cli]
---
# Plan

Execute the rollout.
"""


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("sase-64", False),
        ("plan.md", True),
        ("plans/epic", True),
        (r"plans\epic", True),
    ],
)
def test_plan_file_target_disambiguation(target: str, expected: bool) -> None:
    assert is_plan_file_target(target) is expected


def test_plan_file_mode_creates_links_and_launches_in_tree(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "incoming" / "rollout.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id is not None
    assert result.launched is True
    assert result.resumed is False
    assert result.phase_bead_ids == (
        f"{result.epic_id}.1",
        f"{result.epic_id}.2",
        f"{result.epic_id}.3",
    )
    assert result.launched_agent_names == (*result.phase_bead_ids, result.epic_id)
    assert launches == [result.epic_id]
    assert result.archived_plan_path.parent.parent.name == "plans"
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        result.archived_plan_path.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == result.epic_id
    with BeadProject(project_dir) as project:
        epic = project.show(result.epic_id)
        assert epic.tier is BeadTier.EPIC
        assert epic.design.startswith("sdd/plans/")


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
    [(False, ["async"]), (True, [])],
)
def test_plan_file_success_defers_one_store_push_until_launch_finishes(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_push: bool,
    expected_pushes: list[str],
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
        assert events[-1] == ("push", "async")


def test_plan_file_resume_reuses_linked_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Plan-file rollout",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        core = project.create("Build the core", IssueType.PHASE, parent_id=epic.id)
        cli = project.create("Add the CLI", IssueType.PHASE, parent_id=epic.id)
        verify = project.create("Verify the result", IssueType.PHASE, parent_id=epic.id)
        project.add_dependency(cli.id, core.id)
        project.add_dependency(verify.id, core.id)
        project.add_dependency(verify.id, cli.id)

    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", f"tier: epic\nbead_id: {epic.id}"),
        encoding="utf-8",
    )
    launches: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launches.append(epic_id),
    )
    pushes: list[str] = []
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        lambda _store, *, push_after_commit: pushes.append(push_after_commit),
    )

    result = work_from_plan_file(
        str(plan),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.epic_id == epic.id
    assert result.resumed is True
    assert result.phase_bead_ids == (core.id, cli.id, verify.id)
    assert launches == [epic.id]
    assert pushes == ["async"]
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 4


def test_retrying_original_file_preserves_archived_bead_link(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    first = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )
    second = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert second.epic_id == first.epic_id
    assert second.resumed is True
    with BeadProject(project_dir) as project:
        assert len(project.list_issues()) == 4


def test_plan_file_rejects_missing_linked_bead(
    project_dir: Path,
) -> None:
    plan = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-999"),
        encoding="utf-8",
    )

    with pytest.raises(PlanFileWorkError, match="remove the stale bead_id"):
        work_from_plan_file(
            str(plan),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )


def test_plan_file_launch_failure_rolls_back_for_resume(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert "sase bead work" in (excinfo.value.resume_command or "")
    assert "--no-push" in (excinfo.value.resume_command or "")
    with BeadProject(project_dir) as project:
        assert project.list_issues() == []
    archived = next((project_dir / "sdd" / "plans").glob("*/rollout.md"))
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert "bead_id" not in frontmatter


@pytest.mark.parametrize(
    ("no_push", "expected_commit_pushes", "expected_rollback_push"),
    [
        (False, [False, False, True], None),
        (True, [False, False, False], False),
    ],
)
def test_plan_file_rollback_keeps_best_effort_push_unless_disabled(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_push: bool,
    expected_commit_pushes: list[bool],
    expected_rollback_push: bool | None,
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
    commit_pushes: list[bool] = []

    def commit_store(
        _store: SddStore,
        _message: str,
        *,
        paths: list[Path],
        push_after_commit: bool,
    ) -> bool:
        del paths
        commit_pushes.append(push_after_commit)
        return True

    rollback_pushes: list[bool | None] = []

    def auto_commit(_message: str, **kwargs: bool) -> None:
        rollback_pushes.append(kwargs.get("push_after_commit"))

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    monkeypatch.setattr(
        "sase.bead.epic_from_plan.auto_commit_bead_store",
        auto_commit,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BeadWorkError("agent launch failed")
        ),
    )

    with pytest.raises(PlanFileWorkError, match="agent launch failed"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=no_push,
            render=False,
        )

    assert commit_pushes == expected_commit_pushes
    assert rollback_pushes == [expected_rollback_push]


def test_plan_file_dry_run_is_pure_and_previews_waves(
    project_dir: Path,
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    before = {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    }

    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=False,
    )

    after = {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert result.epic_id is None
    assert result.waves == (("core",), ("cli",), ("verify",))
    assert not result.archived_plan_path.exists()


def test_plan_file_json_output_is_one_stable_object(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )
    args = create_parser().parse_args(["bead", "work", str(source), "--json", "--yes"])

    handle_bead_work(args)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.out.count("\n") == 1
    assert payload["ok"] is True
    assert payload["mode"] == "plan_file"
    assert payload["epic_id"]
    assert len(payload["phase_bead_ids"]) == 3
    assert payload["launched_agent_names"][-1] == payload["epic_id"]


def test_bead_work_help_describes_both_targets_and_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "work", "--help"])

    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "Epic bead ID, or path to a validated epic plan file" in help_text
    assert "-j JSON, --json JSON" not in help_text
    assert "-j, --json" in help_text
    assert "--dry-run" in help_text
    assert "--no-push" in help_text
