"""Deterministic approved-epic frontmatter to bead DAG tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.cli_work_handler import launch_epic_bead_work
from sase.bead.epic_from_plan import create_and_launch_epic_from_plan
from sase.bead.model import BeadTier, IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.store import SddStore

from .cli_work_helpers import FakeLaunchResult


EPIC_PLAN = """---
tier: epic
title: Deterministic rollout
goal: Ship the rollout through an ordered DAG
model: claude/opus
changespec: rollout
bug_id: 12345
phases:
  - id: core
    title: Build the core
    depends_on: []
    description: Implement the shared core.
    size: small
    model: claude/sonnet
  - id: cli
    title: Add the CLI
    depends_on: [core]
    size: medium
    model: "@coder"
  - id: smoke
    title: Exercise the rollout
    depends_on: [core, cli]
    size: large
    model: codex/gpt-5.6-sol
---
# Plan

Execute the rollout.
"""


def _write_plan_update(path: Path, content: str, _message: str) -> bool:
    path.write_text(content, encoding="utf-8")
    return True


def test_create_and_launch_maps_frontmatter_in_order(
    project_dir: Path,
) -> None:
    plan_path = project_dir / "plans" / "rollout.md"
    plan_path.parent.mkdir()
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    commits: list[str] = []
    launched: list[str] = []

    with BeadProject(project_dir) as proj:

        def commit_plan_update(path: Path, content: str, _message: str) -> bool:
            commits.append(content)
            # The plan link is not committed until the complete DAG exists.
            frontmatter, _body, _had_frontmatter = parse_frontmatter(commits[-1])
            header = parse_plan_header_block(commits[-1])
            bead_section = next(
                section
                for section in header.sections
                if section.kind is PlanHeaderSectionKind.BEAD
            )
            assert bead_section.label == frontmatter["bead_id"]
            assert bead_section.target is None
            assert [
                child.id
                for child in proj.get_epic_children(str(frontmatter["bead_id"]))
            ] == [
                f"{frontmatter['bead_id']}.1",
                f"{frontmatter['bead_id']}.2",
                f"{frontmatter['bead_id']}.3",
            ]
            path.write_text(content, encoding="utf-8")
            return True

        def launch_work(project: BeadProject, epic_id: str) -> bool:
            launched.append(epic_id)
            assert [child.id for child in project.get_epic_children(epic_id)] == [
                f"{epic_id}.1",
                f"{epic_id}.2",
                f"{epic_id}.3",
            ]
            return True

        result = create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="plans:202607/rollout.md",
            commit_plan_update=commit_plan_update,
            launch_work=launch_work,
        )

        assert result.epic.tier is BeadTier.EPIC
        assert result.epic.title == "Deterministic rollout"
        assert result.epic.description == "Ship the rollout through an ordered DAG"
        assert result.epic.design == "plans:202607/rollout.md"
        assert result.epic.model == "claude/opus"
        assert result.epic.changespec_name == "rollout"
        assert result.epic.changespec_bug_id == "12345"
        assert [phase.id for phase in result.phases] == [
            f"{result.epic.id}.1",
            f"{result.epic.id}.2",
            f"{result.epic.id}.3",
        ]
        assert result.phases[0].description == "Implement the shared core."
        assert result.phases[1].description == (
            "Phase `cli` in approved epic plan `plans:202607/rollout.md`."
        )
        assert [phase.model for phase in result.phases] == [
            "claude/sonnet",
            "@coder",
            "codex/gpt-5.6-sol",
        ]
        assert [phase.size for phase in result.phases] == [
            PhaseSize.SMALL,
            PhaseSize.MEDIUM,
            PhaseSize.LARGE,
        ]
        assert [
            (dependency.issue_id, dependency.depends_on_id)
            for dependency in result.dependencies
        ] == [
            (result.phases[1].id, result.phases[0].id),
            (result.phases[2].id, result.phases[0].id),
            (result.phases[2].id, result.phases[1].id),
        ]

    assert len(commits) == 1
    linked_frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan_path.read_text(encoding="utf-8")
    )
    assert linked_frontmatter["bead_id"] == result.epic.id
    assert launched == [result.epic.id]


@pytest.mark.parametrize(
    ("proposer", "agent_name", "expected_source"),
    [
        pytest.param(
            "bbugyi200.athena.q8--plan",
            "other--code",
            "proposer",
            id="recorded-proposer",
        ),
        pytest.param(None, "q8--plan", "agent", id="acting-agent-fallback"),
        pytest.param(None, None, "owner", id="store-owner-fallback"),
    ],
)
def test_epic_and_phases_share_resolved_plan_creator(
    proposer: str | None,
    agent_name: str | None,
    expected_source: str,
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import globalize_owned_agent_name

    plan_content = EPIC_PLAN
    if proposer is not None:
        plan_content = plan_content.replace(
            "goal: Ship the rollout through an ordered DAG\n",
            f"goal: Ship the rollout through an ordered DAG\nproposed_by: {proposer}\n",
        )
    if agent_name is not None:
        monkeypatch.setenv("SASE_AGENT_NAME", agent_name)
    plan_path = project_dir / "attributed-rollout.md"
    plan_path.write_text(plan_content, encoding="utf-8")

    with BeadProject(project_dir) as proj:
        result = create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="plans:202607/attributed-rollout.md",
            commit_plan_update=_write_plan_update,
            launch_work=lambda _project, _epic_id: True,
        )

        if expected_source == "proposer":
            assert proposer is not None
            expected_creator = proposer
        elif expected_source == "agent":
            assert agent_name is not None
            expected_creator = globalize_owned_agent_name(agent_name)
        else:
            expected_creator = result.epic.owner
        assert result.epic.created_by == expected_creator
        assert {phase.created_by for phase in result.phases} == {expected_creator}


def test_bead_link_write_reprojects_prompt_section(
    project_dir: Path,
) -> None:
    plans_root = project_dir / "repo--plans"
    plan_path = plans_root / "202607" / "rollout.md"
    prompt_path = plan_path.parent / "prompts" / plan_path.name
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("# Prompt\n", encoding="utf-8")
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    store = SddStore("sidecar_repos", plans_root, plans_root)

    with BeadProject(project_dir) as proj:
        create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="plans:202607/rollout.md",
            commit_plan_update=_write_plan_update,
            launch_work=lambda _project, _epic_id: True,
            store=store,
            primary_root=project_dir,
        )

    sections = parse_plan_header_block(plan_path.read_text(encoding="utf-8")).sections
    assert [section.kind for section in sections] == [
        PlanHeaderSectionKind.PROMPT,
        PlanHeaderSectionKind.BEAD,
    ]
    assert sections[0].label == "202607/prompts/rollout.md"
    assert sections[0].target == "prompts/rollout.md"


def test_creation_failure_removes_epic_and_restores_plan(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    with BeadProject(project_dir) as proj:
        monkeypatch.setattr(
            proj,
            "add_dependency",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("dep write failed")),
        )
        with pytest.raises(RuntimeError, match="dep write failed"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=lambda *_args: pytest.fail(
                    "plan update ran before the complete DAG existed"
                ),
                launch_work=lambda _project, _epic_id: True,
            )
        assert proj.list_issues() == []

    assert plan_path.read_text(encoding="utf-8") == EPIC_PLAN


@pytest.mark.parametrize(
    ("message", "error_kwargs", "preserves_epic"),
    [
        pytest.param("launch failed", {}, False, id="zero-spawn"),
        pytest.param(
            "partial launch failed",
            {"agents_spawned": True, "graph_published": True},
            True,
            id="partial-spawn",
        ),
        pytest.param(
            "commit failed",
            {"agents_launched": True, "graph_published": True},
            True,
            id="post-launch-commit",
        ),
    ],
)
def test_epic_creation_rollback_respects_runner_spawn_boundary(
    project_dir: Path,
    message: str,
    error_kwargs: dict[str, bool],
    preserves_epic: bool,
) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match=message):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=_write_plan_update,
                launch_work=lambda _project, _epic_id: (_ for _ in ()).throw(
                    BeadWorkError(message, **error_kwargs)
                ),
            )
        issues = proj.list_issues()
        if preserves_epic:
            assert len(issues) == 4
            assert (
                len([issue for issue in issues if issue.issue_type is IssueType.PLAN])
                == 1
            )
        else:
            assert issues == []

    content = plan_path.read_text(encoding="utf-8")
    if preserves_epic:
        linked_frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
        assert linked_frontmatter["bead_id"]
    else:
        assert content == EPIC_PLAN


def test_existing_bead_link_refuses_duplicate_creation(project_dir: Path) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(
        EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-99"),
        encoding="utf-8",
    )

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match="refusing to create a duplicate"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=_write_plan_update,
                launch_work=lambda _project, _epic_id: True,
            )
        assert proj.list_issues() == []


def test_invalid_plan_creates_nothing_and_does_not_launch(
    project_dir: Path,
) -> None:
    plan_path = project_dir / "invalid.md"
    plan_path.write_text(
        EPIC_PLAN.replace("depends_on: [core]", "depends_on: [missing]"),
        encoding="utf-8",
    )
    commits: list[Path] = []
    launches: list[str] = []

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match="failed deterministic validation"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="invalid.md",
                commit_plan_update=lambda path, _content, _message: (
                    not commits.append(path)
                ),
                launch_work=lambda _project, epic_id: not launches.append(epic_id),
            )
        assert proj.list_issues() == []

    assert commits == []
    assert launches == []
    assert plan_path.read_text(encoding="utf-8") == EPIC_PLAN.replace(
        "depends_on: [core]", "depends_on: [missing]"
    )


@pytest.mark.usefixtures("fake_cli_work_xprompts")
def test_valid_plan_runs_real_bead_work_wave_path(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid epic reaches the real wave renderer and JIT launcher path."""
    from sase.agent.names import AgentNameWipeResult
    from sase.bead.model import Status

    plan_path = project_dir / "rollout.md"
    plan_path.write_text(
        EPIC_PLAN.replace("changespec: rollout\nbug_id: 12345\n", ""),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: AgentNameWipeResult(target_name=name, found=False),
    )

    def fake_launch(
        query: str,
        extra_env: object = None,
        segment_extra_env: object = None,
    ) -> FakeLaunchResult:
        del extra_env, segment_extra_env
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: False,
    )

    with BeadProject(project_dir) as proj:
        result = create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="rollout.md",
            commit_plan_update=_write_plan_update,
            launch_work=lambda project, epic_id: launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                no_push=True,
            ),
        )

        assert proj.show(result.epic.id).is_ready_to_work is True
        launched_phases = [proj.show(phase.id) for phase in result.phases]
        assert all(phase.status is Status.IN_PROGRESS for phase in launched_phases)
        assert [phase.assignee for phase in launched_phases] == [
            phase.id for phase in result.phases
        ]
        launched_epic = proj.show(result.epic.id)
        assert launched_epic.status is Status.IN_PROGRESS
        assert launched_epic.assignee == f"{result.epic.id}.land"

    query = captured["query"]
    for phase in result.phases:
        assert f"#bd/work_phase_bead:{phase.id}" in query
        assert f"bead={phase.id}" in query
    assert f"#bd/land_epic:{result.epic.id}" in query
    assert f"bead={result.epic.id}" in query
    assert f"%w:{result.phases[0].id}" in query
    assert f"%w:{result.phases[0].id},{result.phases[1].id}" in query


def test_failed_forward_plan_commit_removes_graph_without_launch(
    project_dir: Path,
) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    updates: list[tuple[str, str]] = []
    launches: list[str] = []

    def fail_commit(path: Path, content: str, message: str) -> bool:
        updates.append((content, message))
        path.write_text(content, encoding="utf-8")
        return False

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match="failed to commit bead_id"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=fail_commit,
                launch_work=lambda _project, epic_id: not launches.append(epic_id),
            )
        assert proj.list_issues() == []

    assert len(updates) == 2
    assert updates[0][1].startswith("Link approved epic plan")
    assert updates[1] == (
        EPIC_PLAN,
        "Restore approved epic plan after failed launch: rollout",
    )
    assert launches == []
    assert plan_path.read_text(encoding="utf-8") == EPIC_PLAN
