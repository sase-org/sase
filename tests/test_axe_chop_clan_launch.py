"""Clan-scoped structured chop launch integration coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.chop_proposals import plan_chop_proposals, prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.xprompt.directives import extract_prompt_directives

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _write_clan_result(
    tmp_path: Path,
    *,
    with_env: bool = False,
    clan_summary: str | None = None,
    member_names: tuple[str, str] = ("split_file.first", "split_file.second"),
) -> None:
    proposals: list[dict[str, object]] = [
        {
            "id": "first",
            "prompt": "Split first.py.",
            "workspace": "git:sase",
            "agent_name": member_names[0],
            "clan": "toobig-@",
        },
        {
            "prompt": "Split second.py.",
            "workspace": "git:sase",
            "agent_name": member_names[1],
            "clan": "toobig-@",
            "wait_on": "first",
        },
    ]
    if clan_summary is not None:
        proposals[0]["clan_summary"] = clan_summary
        proposals[1]["clan_summary"] = clan_summary
    if with_env:
        proposals[0]["env"] = {"FILE": "first.py"}
        proposals[1]["env"] = {"FILE": "second.py"}
    payload = json.dumps(
        {"schema_version": 1, "status": "ok", "proposed_launches": proposals}
    )
    make_script(
        tmp_path,
        "split",
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )


def _run(tmp_path: Path, *, dry_run: bool = False):
    return run_configured_chop_once(
        lumberjack_name="split",
        chop=ChopConfig(name="split", description=""),
        axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
        dry_run=dry_run,
        chop_verbose=True,
    )


def test_dry_run_previews_one_concrete_clan_without_reserving_names(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    clan_summary = "[bold cyan]Large modules[/bold cyan]\n  Split safely."
    _write_clan_result(tmp_path, clan_summary=clan_summary)
    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch_one,
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_many,
    ):
        outcome = _run(tmp_path, dry_run=True)

    launch_one.assert_not_called()
    launch_many.assert_not_called()
    assert outcome.status == "success"
    assert [item["clan"] for item in outcome.proposals] == [
        "toobig-0",
        "toobig-0",
    ]
    assert [item["clan_role"] for item in outcome.proposals] == ["declare", "join"]
    assert [item["clan_summary"] for item in outcome.proposals] == [
        clan_summary,
        None,
    ]
    assert outcome.proposals[0]["agent_name"] == "toobig-0.split_file.first"
    assert outcome.proposals[1]["wait_name"] == "toobig-0.split_file.first"
    _, directives = extract_prompt_directives(str(outcome.proposals[0]["prompt"]))
    assert directives.clan_summary == (
        "[bold cyan]Large modules[/bold cyan]\nSplit safely."
    )
    assert "summary=[[" not in str(outcome.proposals[1]["prompt"])
    assert "%id(split_file.second, clan=toobig-0)" in outcome.proposals[1]["prompt"]

    from sase.agent.names import get_reserved_agent_names

    assert get_reserved_agent_names() == set()


def _plan_clan_members(members: list[dict[str, object]]) -> list[tuple[str, str]]:
    prepared = prepare_chop_proposals(
        "split",
        {
            "proposed_launches": [
                {"prompt": "Split.", "workspace": "git:sase", "clan": "toobig-@"}
                | member
                for member in members
            ]
        },
    )
    return [(str(plan.clan), plan.agent_name) for plan in plan_chop_proposals(prepared)]


def test_dry_run_allocates_member_tokens_inside_the_concrete_clan(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _write_clan_result(
        tmp_path,
        member_names=("split_file.first.@", "split_file.second.@"),
    )
    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch_one,
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_many,
    ):
        outcome = _run(tmp_path, dry_run=True)

    launch_one.assert_not_called()
    launch_many.assert_not_called()
    assert outcome.status == "success"
    assert [item["agent_name"] for item in outcome.proposals] == [
        "toobig-0.split_file.first.0",
        "toobig-0.split_file.second.0",
    ]
    assert [item["clan"] for item in outcome.proposals] == ["toobig-0", "toobig-0"]
    assert [item["clan_role"] for item in outcome.proposals] == ["declare", "join"]
    assert [item["member_id"] for item in outcome.proposals] == [
        "split_file.first.0",
        "split_file.second.0",
    ]
    assert "%id:toobig-0.split_file.first.0" in str(outcome.proposals[0]["prompt"])
    assert "%id(split_file.second.0, clan=toobig-0)" in str(
        outcome.proposals[1]["prompt"]
    )
    assert "%wait:toobig-0.split_file.first.0" in str(outcome.proposals[1]["prompt"])
    assert outcome.proposals[1]["wait_name"] == "toobig-0.split_file.first.0"

    from sase.agent.names import get_reserved_agent_names

    assert get_reserved_agent_names() == set()


def test_clan_planning_mixes_plain_and_templated_members(
    temp_state_dir: Path,
) -> None:
    assert _plan_clan_members(
        [
            {"agent_name": "split_file.plain"},
            {"agent_name": "split_file.templated.@"},
        ]
    ) == [
        ("toobig-0", "toobig-0.split_file.plain"),
        ("toobig-0", "toobig-0.split_file.templated.0"),
    ]


def test_identical_member_templates_allocate_distinct_tokens(
    temp_state_dir: Path,
) -> None:
    assert _plan_clan_members(
        [
            {"agent_name": "split_file.dupe.@"},
            {"agent_name": "split_file.dupe.@"},
        ]
    ) == [
        ("toobig-0", "toobig-0.split_file.dupe.0"),
        ("toobig-0", "toobig-0.split_file.dupe.1"),
    ]


def test_identical_plain_members_remain_a_duplicate_identity_error(
    temp_state_dir: Path,
) -> None:
    with pytest.raises(ValueError, match="duplicate member identities"):
        _plan_clan_members(
            [
                {"agent_name": "split_file.dupe"},
                {"agent_name": "split_file.dupe"},
            ]
        )


def test_reserved_clan_moves_the_whole_group_without_leaking_member_tokens(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    from sase.agent.names import get_reserved_agent_names, reserve_registered_clan_name

    artifacts = tmp_path / "old-clan"
    artifacts.mkdir()
    reserve_registered_clan_name(
        "toobig-0",
        "old-generation",
        artifacts,
        create_only=True,
    )

    assert _plan_clan_members(
        [
            {"agent_name": "split_file.first.@"},
            {"agent_name": "split_file.second.@"},
        ]
    ) == [
        ("toobig-1", "toobig-1.split_file.first.0"),
        ("toobig-1", "toobig-1.split_file.second.0"),
    ]
    assert not any(
        name.startswith("toobig-0.split_file") for name in get_reserved_agent_names()
    )


def test_runner_batches_clan_proposals_with_per_member_env_and_full_waits(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    clan_summary = "[bold]Large modules[/bold]"
    _write_clan_result(tmp_path, with_env=True, clan_summary=clan_summary)
    calls: list[tuple[str, list[dict[str, str]]]] = []

    def _launch_many(
        query: str, *, segment_extra_env: list[dict[str, str]]
    ) -> list[SimpleNamespace]:
        calls.append((query, segment_extra_env))
        return [
            SimpleNamespace(
                pid=301,
                agent_name="toobig-0.split_file.first",
                timestamp="260719_120000",
            ),
            SimpleNamespace(
                pid=302,
                agent_name="toobig-0.split_file.second",
                timestamp="260719_120001",
            ),
        ]

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch_one,
        patch("sase.axe.chop_runner.launch_agents_from_cwd", side_effect=_launch_many),
    ):
        outcome = _run(tmp_path)

    launch_one.assert_not_called()
    assert outcome.status == "launched"
    assert len(calls) == 1
    query, envs = calls[0]
    segments = query.split("\n---\n")
    assert len(segments) == 2
    first_directives = extract_prompt_directives(segments[0])[1]
    second_directives = extract_prompt_directives(segments[1])[1]
    assert first_directives.clan_summary == clan_summary
    assert second_directives.clan_summary is None
    assert query.count("summary=[[") == 1
    assert "%id(split_file.second, clan=toobig-0)" in query
    assert "%wait:toobig-0.split_file.first" in query
    assert [env["FILE"] for env in envs] == ["first.py", "second.py"]
    assert all(env["SASE_CHOP_RUN_ID"] == outcome.run_id for env in envs)
    assert [launch["clan"] for launch in outcome.launches] == [
        "toobig-0",
        "toobig-0",
    ]
    assert outcome.launches[1]["wait_name"] == "toobig-0.split_file.first"
