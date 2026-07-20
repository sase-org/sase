"""End-to-end epic summary smoke tests for ``sase bead work`` launches."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, IssueType, PhaseSize
from sase.bead.project import BeadProject

from .cli_work_helpers import FakeLaunchResult, make_args
from .sync_test_helpers import configure_git_identity


@dataclass(frozen=True)
class _PersistedEpicLaunch:
    epic_id: str
    epic_title: str
    phase_titles: tuple[str, ...]
    clan_summary: str
    stale_head: str
    refreshed_head: str
    remote_head: str


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()


def _write_checkout_marker(
    checkout: Path,
    primary: Path,
    *,
    workspace_num: int,
) -> None:
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "project_name": "project",
                "project_key": "project",
                "workspace_num": workspace_num,
                "primary_workspace_dir": str(primary),
                "registry_path": str(primary / ".sase" / "registry.json"),
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def stale_epic_summary_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_cli_work_xprompts: None,
) -> _PersistedEpicLaunch:
    """Persist a launch summary after its plans clone recovers from stale HEAD."""
    from sase.agent.clan_membership import (
        CLAN_MEMBERSHIP_ENV,
        ClanMembershipPlan,
        encode_clan_membership_plan,
    )
    from sase.axe.run_agent_directives import extract_directives_and_write_meta
    from sase.sdd.store import write_sdd_store_record

    remote = tmp_path / "plans.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    primary_workspace = tmp_path / "project"
    launch_workspace = tmp_path / "project_2"
    current_plans = primary_workspace / "sase" / "repos" / "plans"
    stale_plans = launch_workspace / "sase" / "repos" / "plans"
    current_plans.parent.mkdir(parents=True)
    stale_plans.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", str(remote), str(current_plans)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    configure_git_identity(current_plans)
    with BeadProject.init(current_plans, beads_dirname="beads"):
        pass
    _git(current_plans, "add", "-A")
    _git(current_plans, "commit", "-m", "Initialize plans bead store")
    _git(current_plans, "push", "-u", "origin", "main")

    subprocess.run(
        ["git", "clone", str(remote), str(stale_plans)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    configure_git_identity(stale_plans)
    stale_head = _git(stale_plans, "rev-parse", "HEAD")

    epic_title = "Diamond epic recovered from remote"
    with BeadProject(current_plans, beads_dirname="beads") as project:
        epic = project.create(
            epic_title,
            IssueType.PLAN,
            description="Exercise launch-time stale-store recovery.",
            design="202607/diamond.md",
            tier=BeadTier.EPIC,
        )
        phases = tuple(
            project.create(
                title,
                IssueType.PHASE,
                parent_id=epic.id,
                description=f"Deliver {title.lower()}.",
                size=PhaseSize.SMALL,
            )
            for title in ("P1 parse", "P2 render", "P3 persist", "P4 land")
        )
        project.add_dependency(phases[1].id, phases[0].id)
        project.add_dependency(phases[2].id, phases[0].id)
        project.add_dependency(phases[3].id, phases[1].id)
        project.add_dependency(phases[3].id, phases[2].id)
    phase_titles = tuple(phase.title for phase in phases)
    _git(current_plans, "add", "-A")
    _git(current_plans, "commit", "-m", "Add remote epic and phases")
    _git(current_plans, "push")
    remote_head = _git(remote, "rev-parse", "refs/heads/main")

    with BeadProject(stale_plans, beads_dirname="beads") as stale_project:
        with pytest.raises(KeyError):
            stale_project.show(epic.id)

    write_sdd_store_record(
        primary_workspace,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "test/project--plans",
                    "remote_url": str(remote),
                },
                "research": {
                    "repo": "test/project--research",
                    "remote_url": str(tmp_path / "research.git"),
                },
            },
        },
    )
    _write_checkout_marker(primary_workspace, primary_workspace, workspace_num=1)
    _write_checkout_marker(launch_workspace, primary_workspace, workspace_num=2)
    monkeypatch.chdir(primary_workspace)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent_log = artifacts_dir / "agent.log"

    def fake_launch(
        query: str,
        extra_env: Any = None,
        segment_extra_env: Any = None,
    ) -> FakeLaunchResult:
        del extra_env
        assert segment_extra_env
        for name, value in segment_extra_env[0].items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv(
            CLAN_MEMBERSHIP_ENV,
            encode_clan_membership_plan(
                ClanMembershipPlan(clan_name=epic.id, generation="g1")
            ),
        )

        with (
            patch("sase.agent.names.ensure_historical_auto_name_migration"),
            patch(
                "sase.agent.names.agent_name_allocation_lock",
                return_value=nullcontext(),
            ),
            patch("sase.agent.names.claim_agent_name"),
            patch("sase.agent.names.claim_registered_clan_name"),
            patch(
                "sase.xprompt.process_xprompt_references",
                side_effect=lambda value, **_: value,
            ),
            patch(
                "sase.llm_provider.temporary_override."
                "resolve_effective_default_provider_model",
                return_value=("codex", "gpt-5"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            extract_directives_and_write_meta(
                query.split("\n---\n", maxsplit=1)[0],
                str(launch_workspace),
                str(artifacts_dir),
                output_path=str(agent_log),
            )
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *args, **kwargs: True,
    )

    bead_cli.handle_bead_work(make_args(epic.id, yes=True, no_push=True))

    persisted = json.loads(
        (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert persisted["agent_clan"] == epic.id
    assert not agent_log.read_text(encoding="utf-8")
    return _PersistedEpicLaunch(
        epic_id=epic.id,
        epic_title=epic_title,
        phase_titles=phase_titles,
        clan_summary=persisted["clan_summary"],
        stale_head=stale_head,
        refreshed_head=_git(stale_plans, "rev-parse", "HEAD"),
        remote_head=remote_head,
    )


class TestEpicSummarySmokeExercises:
    """End-to-end smoke tests for epic clan summary persistence and rendering."""

    def test_epic_work_launch_refreshes_stale_clone_and_persists_rich_summary(
        self,
        stale_epic_summary_launch: _PersistedEpicLaunch,
    ) -> None:
        launch = stale_epic_summary_launch
        fallback = f"[bold]EPIC {launch.epic_id}[/]"

        assert launch.stale_head != launch.refreshed_head
        assert launch.refreshed_head == launch.remote_head
        assert launch.epic_title in launch.clan_summary
        assert all(title in launch.clan_summary for title in launch.phase_titles)
        assert "[bold #D75FFF]◆ EPIC" in launch.clan_summary
        assert "PHASES · 0/4 done at launch" in launch.clan_summary
        assert "bold black on #87D7FF" in launch.clan_summary
        assert fallback not in launch.clan_summary

    def test_epic_work_clan_panel_renders_persisted_summary(
        self,
        stale_epic_summary_launch: _PersistedEpicLaunch,
    ) -> None:
        """Clan panel renders the markup persisted by the launch exercise."""
        from sase.ace.tui.models._agent_tree import project_clan_tree
        from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
            build_clan_detail_text,
        )
        from tests.ace.tui.widgets._agent_display_clan_helpers import (
            make_clan_agent,
        )

        launch = stale_epic_summary_launch
        fallback = f"[bold]EPIC {launch.epic_id}[/]"
        assert "[bold #D75FFF]◆ EPIC" in launch.clan_summary
        assert fallback not in launch.clan_summary

        member = make_clan_agent(
            f"{launch.epic_id}.land",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        )
        member.clan_summary = launch.clan_summary
        result = build_clan_detail_text(project_clan_tree([member])[0])

        assert launch.epic_title in result.plain
        assert all(title in result.plain for title in launch.phase_titles)
