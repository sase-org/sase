"""Integration coverage for rendered epic work and runner-side bead claims."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.claims import (
    BeadClaimReleaseOutcome,
    claim_bead_for_waiting_agent,
    release_bead_claim_for_agent,
)
from sase.bead.cli_work_launch import launch_bead_work_agents
from sase.bead.cli_work_plan import expected_agent_names
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.work import (
    VCSLaunchContext,
    build_epic_work_plan_from_beads_dir,
    epic_work_segment_env,
    render_multi_prompt,
)
from sase.sdd.store import SddStore
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.workflow_models import Workflow

from .claims_test_helpers import install_writable_bead_store
from .cli_work_helpers import seed_diamond


def _launch_result(name: str) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=1,
        workspace_dir="/workspace/1",
        output_path="/tmp/output",
        agent_name=name,
    )


@pytest.mark.parametrize("planned", [False, True], ids=["generic-cwd", "planned"])
def test_rendered_epic_preclaims_make_runner_lifecycle_quiet_noops(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    planned: bool,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        project.mark_ready_to_work(epic_id)
        plan = build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)
        project.preclaim_epic_work(
            epic_id,
            [
                (assignment.bead_id, assignment.agent_name)
                for wave in plan.waves
                for assignment in wave
            ],
            plan.land_agent_name,
        )

    launch_context = (
        VCSLaunchContext(vcs_workflow="git", project_name="proj") if planned else None
    )
    query = render_multi_prompt(
        plan,
        Workflow(name="bd/work_phase_bead"),
        Workflow(name="bd/land_epic"),
        vcs_context=launch_context,
    )
    envs = epic_work_segment_env(plan, plan_ref="sdd/plans/epic.md")
    dispatched: dict[str, Any] = {}

    if planned:
        monkeypatch.setattr(
            "sase.agent.launcher.launch_agent_from_cwd",
            lambda *args, **kwargs: pytest.fail("planned work must use the adapter"),
        )

        def launch_planned(**kwargs: Any) -> list[AgentLaunchResult]:
            dispatched.update(kwargs)
            return [_launch_result(name) for name in sorted(expected_agent_names(plan))]

        monkeypatch.setattr(
            "sase.agent.launcher.launch_planned_bead_work_agents",
            launch_planned,
        )
    else:
        monkeypatch.setattr(
            "sase.agent.launcher.launch_planned_bead_work_agents",
            lambda **kwargs: pytest.fail("generic work must use the CWD launcher"),
        )

        def launch_generic(
            rendered: str,
            extra_env: object = None,
            segment_extra_env: object = None,
        ) -> AgentLaunchResult:
            dispatched.update(
                query=rendered,
                extra_env=extra_env,
                segment_extra_env=segment_extra_env,
            )
            return _launch_result(plan.waves[0][0].agent_name)

        monkeypatch.setattr(
            "sase.agent.launcher.launch_agent_from_cwd",
            launch_generic,
        )

    launch_bead_work_agents(
        query,
        segment_extra_env=envs,
        expected_names=expected_agent_names(plan),
        launch_context=launch_context,
    )

    segments = (
        list(dispatched["segments"])
        if planned
        else str(dispatched["query"]).split("\n---\n")
    )
    dispatched_envs = tuple(dispatched["segment_extra_env"])
    directives_by_bead = {}
    for segment, env in zip(segments, dispatched_envs, strict=True):
        assert segment.count("%id") == 1
        _, directives = extract_prompt_directives(segment)
        assert directives.bead_id == env["SASE_BEAD_ID"]
        directives_by_bead[directives.bead_id] = directives

    install_writable_bead_store(monkeypatch, project_dir / "sdd/beads")
    store = SddStore(
        storage="separate_repo",
        sdd_dir=project_dir / "sdd",
        repo_root=project_dir,
    )
    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch(
            "sase.sdd.store.ensure_sdd_kind_clone",
            return_value=store.kind_root("beads"),
        ),
        patch(
            "sase.bead.sync.commit_bead_claim",
            side_effect=AssertionError("wait no-op must not commit"),
        ),
        patch(
            "sase.bead.sync.commit_bead_claim_release",
            side_effect=AssertionError("release no-op must not commit"),
        ),
        patch(
            "sase.bead.sync.publish_bead_claim",
            side_effect=AssertionError("runner no-op must not publish"),
        ),
        patch(
            "sase.sdd.files.commit_sdd_store_files",
            side_effect=AssertionError("promotion no-op must not commit"),
        ),
    ):
        for bead_id, directives in directives_by_bead.items():
            assert directives.name is not None
            assert claim_bead_for_waiting_agent(
                project_name="proj",
                bead_id=bead_id,
                agent_name=directives.name,
            )
            promoted = claim_bead_for_agent_launch(
                agent_name=directives.name,
                bead_id=bead_id,
                workspace_dir=str(project_dir),
                workspace_num=0,
                artifacts_dir=str(project_dir / "artifacts"),
            )
            assert (promoted.status, promoted.assignee) == (
                Status.IN_PROGRESS,
                directives.name,
            )
            assert (
                release_bead_claim_for_agent(
                    project_name="proj",
                    bead_id=bead_id,
                    agent_name=directives.name,
                )
                is BeadClaimReleaseOutcome.NOTHING_TO_RELEASE
            )

    with BeadProject(project_dir) as project:
        for phase_id in phase_ids:
            issue = project.show(phase_id)
            assert (issue.status, issue.assignee) == (
                Status.IN_PROGRESS,
                phase_id,
            )
        epic = project.show(epic_id)
        assert (epic.status, epic.assignee) == (
            Status.IN_PROGRESS,
            plan.land_agent_name,
        )


def test_wait_claim_survives_publication_lag_and_holds_until_promotion(
    project_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the launch failure: the canonical store lags the epic graph.

    The waiting agent's canonical checkout has not yet integrated the freshly
    published graph, so its first claim attempt cannot find the bead at all.
    The claim must recover from that, and the resulting ``claimed`` window must
    last for the whole wait rather than ending milliseconds later.
    """
    _epic_id, phase_ids = seed_diamond(project_dir)
    published_beads = project_dir / "sdd" / "beads"
    canonical_root = tmp_path_factory.mktemp("canonical")
    with BeadProject.init(canonical_root):
        pass
    canonical_beads = canonical_root / "sdd" / "beads"
    install_writable_bead_store(monkeypatch, canonical_beads)

    integrations: list[Path] = []

    def integrate(beads_dir: Path) -> None:
        """Stand in for the fetch/rebase that publishes the graph locally."""
        integrations.append(beads_dir)
        shutil.copytree(published_beads, beads_dir, dirs_exist_ok=True)

    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", integrate)

    blocker, waiting = phase_ids[0], phase_ids[1]
    agent_name = "diamond-1.2"

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=waiting,
        agent_name=agent_name,
    )
    assert integrations == [canonical_beads]
    with BeadProject(canonical_root) as project:
        issue = project.show(waiting)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, agent_name)

    # The claim is held for the whole wait: the blocker runs to completion and
    # a re-claim by the same agent is a no-op that needs no further recovery.
    with BeadProject(canonical_root) as project:
        project.close([blocker])
    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=waiting,
        agent_name=agent_name,
    )
    assert integrations == [canonical_beads]
    with BeadProject(canonical_root) as project:
        assert project.show(waiting).status == Status.CLAIMED

    store = SddStore(
        storage="in_tree",
        sdd_dir=canonical_root / "sdd",
        repo_root=canonical_root,
    )
    with patch("sase.sdd.store.resolve_sdd_store", return_value=store):
        promoted = claim_bead_for_agent_launch(
            agent_name=agent_name,
            bead_id=waiting,
            workspace_dir=str(canonical_root),
            workspace_num=0,
            artifacts_dir=str(canonical_root / "artifacts"),
        )

    assert (promoted.status, promoted.assignee) == (Status.IN_PROGRESS, agent_name)


@pytest.mark.parametrize("target", ["phase", "epic"])
def test_closed_rendered_bead_fails_before_model_callback(
    project_dir: Path,
    target: str,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    with BeadProject(project_dir) as project:
        plan = build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)
    query = render_multi_prompt(
        plan,
        Workflow(name="bd/work_phase_bead"),
        Workflow(name="bd/land_epic"),
    )
    target_id = phase_ids[0] if target == "phase" else epic_id
    segment = next(
        segment for segment in query.split("\n---\n") if f"bead={target_id})" in segment
    )
    _, directives = extract_prompt_directives(segment)
    assert directives.name is not None

    with BeadProject(project_dir) as project:
        if target == "epic":
            project.close(
                [target_id],
                reason="Test fixture cancels unfinished work",
                resolution="canceled",
                force=True,
            )
        else:
            project.close([target_id])
    store = SddStore(
        storage="in_tree",
        sdd_dir=project_dir / "sdd",
        repo_root=project_dir,
    )
    model_callbacks: list[str] = []

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        pytest.raises(RuntimeError, match=rf"Failed to claim bead '{target_id}'"),
    ):
        claim_bead_for_agent_launch(
            agent_name=directives.name,
            bead_id=target_id,
            workspace_dir=str(project_dir),
            workspace_num=0,
            artifacts_dir=str(project_dir / "artifacts"),
        )
        model_callbacks.append(target_id)

    assert model_callbacks == []
