"""Core creation and parenting coverage for plan-file ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.cli_work_from_plan import (
    PlanFileWorkError,
    is_plan_file_target,
    work_from_plan_file,
)
from sase.bead.model import BeadTier, IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from tests.test_bead.cli_work_from_plan_helpers import (
    EPIC_PLAN,
    MALFORMED_HEADER_EPIC_PLAN,
    epic_plan_with_parent,
    write_plan_update,
)


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
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
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
    assert result.launched_agent_names == (
        *result.phase_bead_ids,
        f"{result.epic_id}.land",
    )
    assert launches == [result.epic_id]
    assert result.archived_plan_path.parent.parent.name == "plans"
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        result.archived_plan_path.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == result.epic_id
    with BeadProject(project_dir) as project:
        epic = project.show(result.epic_id)
        assert epic.tier is BeadTier.EPIC
        assert epic.design.startswith("plan:")
        assert [phase.size for phase in project.get_epic_children(epic.id)] == [
            PhaseSize.SMALL,
            PhaseSize.MEDIUM,
            PhaseSize.LARGE,
        ]


def test_plan_file_mode_rejects_malformed_header_block_before_lock_or_archive(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "incoming" / "malformed.md"
    source.parent.mkdir()
    source.write_text(MALFORMED_HEADER_EPIC_PLAN, encoding="utf-8")

    def _fail_if_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("must not run before header validation fails")

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._epic_plan_launch_lock", _fail_if_called
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file", _fail_if_called
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file", _fail_if_called
    )

    with pytest.raises(PlanFileWorkError) as exc_info:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    error = exc_info.value
    assert error.validation is not None
    assert not error.validation.ok
    assert any(
        diagnostic.code == "header-invalid"
        for diagnostic in error.validation.diagnostics
    )


def test_plan_file_mode_archive_boundary_failure_is_actionable_end_to_end(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The up-front header gate normally rejects this before archiving (see
    the test above). This pins the defense-in-depth case: if a malformed
    header ever reaches the archive boundary anyway, the launch path's
    wrapped error still names the plan and the parser's reason instead of a
    bare, location-less ``validation: ...`` message."""
    source = project_dir / "incoming" / "malformed.md"
    source.parent.mkdir()
    source.write_text(MALFORMED_HEADER_EPIC_PLAN, encoding="utf-8")

    from sase.sdd.plan_validate import validate_plan

    monkeypatch.setattr(
        "sase.sdd.plan_validate.validate_plan_file",
        lambda _path, tier, *, mode="authoring": validate_plan(
            EPIC_PLAN, tier, mode=mode
        ),
    )

    with pytest.raises(PlanFileWorkError) as exc_info:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    message = str(exc_info.value)
    assert str(source) in message
    assert "header-invalid" in message
    assert "trailing text" in message


def test_plan_file_mode_persists_durable_stage_timing(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "incoming" / "timed.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")
    timing_path = project_dir / "launch_timing.jsonl"
    monkeypatch.setenv("SASE_TUI_LAUNCH_TIMING_PATH", str(timing_path))
    monkeypatch.delenv("SASE_BEAD_WORK_TIMING", raising=False)
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

    records = [
        json.loads(line)
        for line in timing_path.read_text(encoding="utf-8").splitlines()
    ]
    record = next(
        record
        for record in records
        if record["operation"] == "bead_work" and record["event"] == "launch_timing"
    )
    stage_records = [
        record for record in records if record["event"] == "launch_timing_stage"
    ]
    stage_names = {stage["stage"] for stage in record["stages"]}
    assert record["operation"] == "bead_work"
    assert record["bead_id"] == result.epic_id
    assert record["correlation_id"]
    assert stage_records
    assert {
        "plan_launch_lock",
        "plan_store_health_pre_archive",
        "archive_plan_file",
        "archived_plan_commit",
        "bead_project_open",
        "epic_creation",
        "phase_creation",
        "dependency_creation",
        "header_projection",
        "plan_link_commit",
    } <= stage_names


def test_plan_file_creates_hierarchical_child_epic_from_managed_parent(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        root = project.create("Root epic", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Parent phase", IssueType.PHASE, parent_id=root.id)

    source = project_dir / "child_epic.md"
    source.write_text(epic_plan_with_parent(phase.id), encoding="utf-8")
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

    assert result.epic_id == f"{phase.id}.1"
    assert result.parent_id == phase.id
    assert result.phase_bead_ids == (
        f"{phase.id}.1.1",
        f"{phase.id}.1.2",
        f"{phase.id}.1.3",
    )
    assert result.epic_id is not None
    with BeadProject(project_dir) as project:
        assert project.show(result.epic_id).parent_id == phase.id


def test_plan_file_parent_override_and_force_top_level(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        root = project.create("Root epic", IssueType.PLAN, tier=BeadTier.EPIC)
        authored_parent = project.create(
            "Authored parent", IssueType.PHASE, parent_id=root.id
        )
        override_parent = project.create(
            "Override parent", IssueType.PHASE, parent_id=root.id
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
    overridden_source = project_dir / "overridden_child.md"
    overridden_source.write_text(
        epic_plan_with_parent(authored_parent.id), encoding="utf-8"
    )
    top_level_source = project_dir / "top_level_child.md"
    top_level_source.write_text(
        epic_plan_with_parent(authored_parent.id), encoding="utf-8"
    )

    overridden = work_from_plan_file(
        str(overridden_source),
        dry_run=False,
        yes=True,
        no_push=False,
        parent=override_parent.id,
        render=False,
    )
    top_level = work_from_plan_file(
        str(top_level_source),
        dry_run=False,
        yes=True,
        no_push=False,
        parent="top-level",
        render=False,
    )

    assert overridden.parent_id == override_parent.id
    assert overridden.epic_id == f"{override_parent.id}.1"
    assert top_level.parent_id is None
    assert top_level.epic_id is not None and "." not in top_level.epic_id


def test_plan_file_parent_dry_run_previews_id_and_missing_parent_has_remedy(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        root = project.create("Root epic", IssueType.PLAN, tier=BeadTier.EPIC)
        project.create("First phase", IssueType.PHASE, parent_id=root.id)
        project.create("Second phase", IssueType.PHASE, parent_id=root.id)

    source = project_dir / "preview_child.md"
    source.write_text(epic_plan_with_parent(root.id), encoding="utf-8")
    result = work_from_plan_file(
        str(source),
        dry_run=True,
        yes=False,
        no_push=False,
        render=True,
    )

    assert result.epic_id is None
    assert result.parent_id == root.id
    assert result.preview_epic_id == f"{root.id}.3"
    output = capsys.readouterr().out
    assert "preview epic" in output
    assert f"{root.id}.3" in output
    assert f"Epic: {root.id}.3" in output

    missing = project_dir / "missing_parent.md"
    missing.write_text(epic_plan_with_parent("sase-missing.9"), encoding="utf-8")
    with pytest.raises(PlanFileWorkError, match="--parent top-level") as excinfo:
        work_from_plan_file(
            str(missing),
            dry_run=True,
            yes=False,
            no_push=False,
            render=False,
        )
    assert "missing from the active store" in str(excinfo.value)
