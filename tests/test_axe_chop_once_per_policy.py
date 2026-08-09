"""Declarative chop once-per proposal policy coverage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_policy import apply_chop_once_per, release_chop_once_per_keys
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import read_chop_run

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_once_per_relinks_duplicate_head_dependent_to_no_wait(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "id": "root",
                    "prompt": "Root.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:root",
                },
                {
                    "prompt": "Dependent.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:dependent",
                    "wait_on": "root",
                },
            ]
        },
    )
    first = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals[:1],
        persist=True,
    )
    assert first.accepted_indices == (0,)

    repeated = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )
    assert repeated.accepted_indices == (1,)
    assert repeated.effective_waits == {1: None}
    assert repeated.decisions[0]["outcome"] == "duplicate"
    assert repeated.decisions[1]["outcome"] == "accept"
    assert repeated.decisions[1]["reason"] == (
        "wait dependency 'root' was deduped; relinked to none"
    )


def test_once_per_relinks_across_mid_chain_duplicate_by_id(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    seed = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:middle",
                }
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {"id": "root", "prompt": "Root.", "workspace": "git:sase"},
                {
                    "id": "middle",
                    "prompt": "Middle.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:middle",
                    "wait_on": "root",
                },
                {
                    "prompt": "Leaf.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:leaf",
                    "wait_on": "middle",
                },
            ]
        },
    )

    outcome = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )

    assert outcome.accepted_indices == (0, 2)
    assert outcome.effective_waits == {0: None, 2: "root"}
    assert outcome.decisions[1]["outcome"] == "duplicate"
    assert outcome.decisions[2]["reason"] == (
        "wait dependency 'middle' was deduped; relinked to 'root'"
    )


def test_once_per_relinks_across_consecutive_duplicates_by_index(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    seed = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed one.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:one",
                },
                {
                    "prompt": "Seed two.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:two",
                },
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {"prompt": "Root.", "workspace": "git:sase"},
                {
                    "prompt": "Duplicate one.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:one",
                    "wait_on": 0,
                },
                {
                    "prompt": "Duplicate two.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:two",
                    "wait_on": 1,
                },
                {
                    "prompt": "Leaf.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:leaf",
                    "wait_on": 2,
                },
            ]
        },
    )

    outcome = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )

    assert outcome.accepted_indices == (0, 3)
    assert outcome.effective_waits == {0: None, 3: 0}
    assert outcome.decisions[1]["outcome"] == "duplicate"
    assert outcome.decisions[2]["outcome"] == "duplicate"
    assert outcome.decisions[3]["reason"] == (
        "wait dependency 2 was deduped; relinked to 0"
    )


def test_release_once_per_keys_persists_exact_removal(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="events", description="")
    proposals = prepare_chop_proposals(
        "events",
        {
            "proposed_launches": [
                {
                    "prompt": "First.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:first",
                },
                {
                    "prompt": "Second.",
                    "workspace": "git:sase",
                    "dedupe_key": "event:second",
                },
            ]
        },
    )
    initial = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )
    assert initial.accepted_indices == (0, 1)

    assert (
        release_chop_once_per_keys("events", "events", ["event:first", "event:missing"])
        == 1
    )
    assert release_chop_once_per_keys("events", "events", ["event:first"]) == 0

    follow_up = apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=False,
    )
    assert follow_up.accepted_indices == (0,)
    assert follow_up.decisions[0]["outcome"] == "accept"
    assert follow_up.decisions[1]["outcome"] == "duplicate"


def test_all_duplicate_proposals_record_skipped_run(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    result = {
        "schema_version": 1,
        "status": "ok",
        "proposed_launches": [
            {
                "prompt": "Do it.",
                "workspace": "git:sase",
                "dedupe_key": "event:known",
            }
        ],
    }
    proposals = prepare_chop_proposals("events", result)
    chop = ChopConfig(name="events", description="")
    apply_chop_once_per(
        lumberjack_name="events",
        chop=chop,
        proposals=proposals,
        persist=True,
    )
    payload = json.dumps(result)
    make_script(
        tmp_path,
        "events",
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd") as launch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="events",
            chop=chop,
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="manual",
        )

    launch.assert_not_called()
    assert outcome.status == "skipped"
    assert outcome.run_id is not None
    entry = read_chop_run("events", "events", outcome.run_id)
    assert entry is not None
    assert entry.status == "skipped"
    assert entry.reason is not None and "once-per" in entry.reason
    assert entry.proposals[0]["validation"] == "duplicate"
