"""Clan-scoped structured chop launch integration coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _write_clan_result(tmp_path: Path, *, with_env: bool = False) -> None:
    proposals: list[dict[str, object]] = [
        {
            "id": "first",
            "prompt": "Split first.py.",
            "workspace": "git:sase",
            "agent_name": "split_file.first",
            "clan": "toobig-@",
        },
        {
            "prompt": "Split second.py.",
            "workspace": "git:sase",
            "agent_name": "split_file.second",
            "clan": "toobig-@",
            "wait_on": "first",
        },
    ]
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
    _write_clan_result(tmp_path)
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
    assert outcome.proposals[0]["agent_name"] == "toobig-0.split_file.first"
    assert outcome.proposals[1]["wait_name"] == "toobig-0.split_file.first"
    assert "%clan(toobig-0, tribe=chop)" in outcome.proposals[0]["prompt"]
    assert "%id(split_file.second, clan=toobig-0)" in outcome.proposals[1]["prompt"]

    from sase.agent.names import get_reserved_agent_names

    assert get_reserved_agent_names() == set()


def test_runner_batches_clan_proposals_with_per_member_env_and_full_waits(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _write_clan_result(tmp_path, with_env=True)
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
    assert "%clan(toobig-0, tribe=chop)" in query
    assert "%id(split_file.second, clan=toobig-0)" in query
    assert "%wait:toobig-0.split_file.first" in query
    assert [env["FILE"] for env in envs] == ["first.py", "second.py"]
    assert all(env["SASE_CHOP_RUN_ID"] == outcome.run_id for env in envs)
    assert [launch["clan"] for launch in outcome.launches] == [
        "toobig-0",
        "toobig-0",
    ]
    assert outcome.launches[1]["wait_name"] == "toobig-0.split_file.first"
