"""Deferred land-row matching tests."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.prompt_archive.deferred import restore_deferred_prompt_archives
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    render_plan_header_block,
)
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.test_deferred_prompt_archive._helpers import OWNER


def _archive_with_agent_label(repo: Path, label: str) -> None:
    month = repo / "prompts/202611"
    month.mkdir(parents=True, exist_ok=True)
    (month / "plan.md").write_text(
        render_plan_header_block(
            (
                PlanHeaderSection(
                    kind=PlanHeaderSectionKind.AGENTS,
                    entries=(PlanHeaderEntry(label=label),),
                ),
            )
        )
        + "\nArchived plan prompt.\n",
        encoding="utf-8",
    )


def _land_request(artifacts_dir: Path) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="foo.land",
        global_agent="alice.athena.foo.land",
        primary_revision="c" * 40,
        local_hood="foo.land",
        artifacts_dir=str(artifacts_dir),
    )


def test_deferred_land_row_accepts_planner_archive_for_same_session_member(
    tmp_path: Path,
) -> None:
    target, _remote = setup_target(tmp_path)
    artifacts_dir = tmp_path / "runs/land"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "followup_prompt.md").write_text("Follow up.\n", encoding="utf-8")
    _archive_with_agent_label(target.sidecar_path, "alice.athena.foo.land--plan")
    request = _land_request(artifacts_dir)

    failures = restore_deferred_prompt_archives(
        target,
        (request,),
        run_git,
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", ()),
    )

    assert failures == {}


def test_deferred_land_row_does_not_match_prefix_sharing_session(
    tmp_path: Path,
) -> None:
    target, _remote = setup_target(tmp_path)
    artifacts_dir = tmp_path / "runs/land"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "followup_prompt.md").write_text("Follow up.\n", encoding="utf-8")
    _archive_with_agent_label(target.sidecar_path, "alice.athena.foo.landing--plan")
    request = _land_request(artifacts_dir)

    failures = restore_deferred_prompt_archives(
        target,
        (request,),
        run_git,
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", ()),
    )

    assert request.logical_key in failures
    assert "missing local source does not prove" in failures[request.logical_key]
