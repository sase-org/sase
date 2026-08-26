"""Typed clan-dispatch coverage for end-to-end chop proposal batches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.feature_flags import override_flags
from sase.xprompt import extract_vcs_workflow_tag
from sase.xprompt.directives import extract_prompt_directives
from tests._axe_chop_proposal_launch_helpers import patch_condition_workspace_lease

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_typed_clan_batch_promotes_first_surviving_member_end_to_end(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A toobig_split-shaped clan batch where admission skips the two
    statically leading members: the first surviving member must declare the
    clan with the group's tribe and summary, and no member falls into
    ``@default``."""
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {
                    "id": "first",
                    "prompt": "%if::\n```bash\nexit 1\n```\nFirst.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "first",
                    "clan": "toobig-x",
                    "clan_summary": "[bold]Large[/bold]",
                },
                {
                    "id": "second",
                    "prompt": "%if::\n```bash\nexit 1\n```\nSecond.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "second",
                    "clan": "toobig-x",
                },
                {
                    "id": "third",
                    "prompt": "%if::\n```bash\nexit 0\n```\nThird.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "third",
                    "clan": "toobig-x",
                },
            ]
        },
    )

    def _gh_project_resolver(_prompt: str) -> SimpleNamespace:
        return SimpleNamespace(
            workflow_type="gh",
            ref="sase",
            workspace_dir=str(repo),
            project_file="/tmp/projects/sase/sase.sase",
        )

    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        _gh_project_resolver,
    )
    patch_condition_workspace_lease(monkeypatch, repo)
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [
            SimpleNamespace(
                pid=900 + len(calls),
                agent_name="toobig-x.third",
                workspace_num=len(calls),
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name=f"ace(run)-{len(calls)}",
                cl_name="sase",
                timestamp=f"26082{len(calls)}_120000",
                artifacts_dir=str(tmp_path / "artifacts" / str(len(calls))),
            )
        ]

    with (
        override_flags(typed_launch_units=True),
        patch("sase.notifications.senders.notify_workflow_complete"),
    ):
        launches = launch_chop_proposals(
            lumberjack_name="split",
            chop_name="split",
            run_id="run-clan",
            proposals=prepared,
            launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
            launch_agents_from_cwd_fn=_launch,
        )

    assert launches.admission_result is not None
    assert launches.admission_result.admission_complete
    assert len(calls) == 1
    prompt, _env = calls[0]
    assert "%if" not in prompt
    assert (extract_vcs_workflow_tag(prompt) or "").strip() == "#gh:sase"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "toobig-x.third"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"
    assert len(launches) == 1
    assert launches[0]["clan"] == "toobig-x"


def test_typed_clan_batch_restores_sequential_member_waits_end_to_end(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {
                    "id": "first",
                    "prompt": "%if::\n```bash\nexit 0\n```\nFirst.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "first",
                    "clan": "toobig-x",
                    "clan_summary": "[bold]Large[/bold]",
                },
                {
                    "id": "second",
                    "prompt": "%if::\n```bash\nexit 0\n```\nSecond.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "second",
                    "clan": "toobig-x",
                    "wait_on": "first",
                },
                {
                    "id": "third",
                    "prompt": "%if::\n```bash\nexit 0\n```\nThird.",
                    "workspace": "gh:sase-org/sase",
                    "agent_name": "third",
                    "clan": "toobig-x",
                    "wait_on": "second",
                },
            ]
        },
    )

    def _gh_project_resolver(_prompt: str) -> SimpleNamespace:
        return SimpleNamespace(
            workflow_type="gh",
            ref="sase",
            workspace_dir=str(repo),
            project_file="/tmp/projects/sase/sase.sase",
        )

    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        _gh_project_resolver,
    )
    patch_condition_workspace_lease(monkeypatch, repo)
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        _, directives = extract_prompt_directives(prompt)
        assert directives.name is not None
        return [
            SimpleNamespace(
                pid=900 + len(calls),
                agent_name=directives.name,
                workspace_num=len(calls),
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name=f"ace(run)-{len(calls)}",
                cl_name="sase",
                timestamp=f"26082{len(calls)}_120000",
                artifacts_dir=str(tmp_path / "artifacts" / str(len(calls))),
            )
        ]

    with (
        override_flags(typed_launch_units=True),
        patch("sase.notifications.senders.notify_workflow_complete"),
    ):
        launches = launch_chop_proposals(
            lumberjack_name="split",
            chop_name="split",
            run_id="run-chain",
            proposals=prepared,
            launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
            launch_agents_from_cwd_fn=_launch,
        )

    assert launches.admission_result is not None
    assert launches.admission_result.admission_complete
    assert len(calls) == 3
    waits = [extract_prompt_directives(prompt)[1].wait for prompt, _env in calls]
    assert waits == [[], ["toobig-x.first"], ["toobig-x.second"]]
    assert [launch["wait_name"] for launch in launches] == [
        None,
        "toobig-x.first",
        "toobig-x.second",
    ]
