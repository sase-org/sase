"""Structured chop proposal-launch coverage."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_admission_store import UNITS_DIRNAME, admission_dir
from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.core.agent_launch_wire import AgentUnitWire, LaunchUnitWire
from sase.feature_flags import override_flags
from sase.xprompt.directives import extract_prompt_directives

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _result_script(tmp_path: Path, name: str, document: dict[str, object]) -> None:
    payload = json.dumps(document)
    make_script(
        tmp_path,
        name,
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )


def _config(tmp_path: Path) -> AxeConfig:
    return AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])


def _known_project_resolver(repo: Path) -> object:
    return SimpleNamespace(
        workflow_type="git",
        ref="sase",
        workspace_dir=str(repo),
        project_file="/tmp/projects/sase/sase.sase",
    )


def test_typed_chop_proposal_uses_durable_admission_and_chop_env(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    pwd_capture = tmp_path / "condition-pwd.txt"
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": (
                        "%if::\n"
                        "```bash\n"
                        f"pwd > {shlex.quote(str(pwd_capture))}\n"
                        "```\n"
                        "Review docs."
                    ),
                    "workspace": "git:sase",
                    "agent_name": "refresh",
                    "env": {"MODE": "typed", "SASE_CHOP_NAME": "prompt-owned"},
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [
            SimpleNamespace(
                pid=501,
                agent_name="refresh",
                workspace_num=2,
                workspace_dir=str(repo),
                project_name="sase",
                workflow_name="ace(run)-260823_120000",
                cl_name="sase",
                timestamp="260823_120000",
                artifacts_dir=str(tmp_path / "artifacts" / "20260823120000"),
            )
        ]

    with (
        override_flags(typed_launch_units=True),
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        launches = launch_chop_proposals(
            lumberjack_name="docs",
            chop_name="docs",
            run_id="run-typed",
            proposals=prepared,
            launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
            launch_agents_from_cwd_fn=_launch,
        )

    assert len(launches) == 1
    assert launches.typed_admission is not None
    assert launches.admission_result.admission_complete
    assert pwd_capture.read_text(encoding="utf-8").strip() == str(repo)
    prompt, env = calls[0]
    assert "%if" not in prompt
    assert "condition-pwd" not in prompt
    assert env["MODE"] == "typed"
    assert env["SASE_CHOP_NAME"] == "docs"
    assert env["SASE_CHOP_RUN_ID"] == "run-typed"
    assert env["SASE_CHOP_PROPOSAL_INDEX"] == "0"
    assert env["SASE_CHOP_ADMISSION_LOGICAL_ID"] == env["SASE_LAUNCH_LOGICAL_ID"]
    assert env["SASE_CHOP_ADMISSION_FINGERPRINT"]
    notify.assert_not_called()


def test_typed_chop_proposal_flag_off_rejects_before_launch(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\ntrue\n```\nReview docs.",
                    "workspace": "git:sase",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )

    def _launch(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        raise AssertionError("typed flag-off proposal reached the launcher")

    with override_flags(typed_launch_units=False):
        with pytest.raises(LaunchRequestError, match="typed_launch_units"):
            launch_chop_proposals(
                lumberjack_name="docs",
                chop_name="docs",
                run_id="run-flag-off",
                proposals=prepared,
                launch_agent_from_cwd_fn=lambda *args, **kwargs: None,
                launch_agents_from_cwd_fn=_launch,
            )


def test_runner_all_skipped_typed_admission_succeeds_without_agent(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    repo = tmp_path / "repo"
    repo.mkdir()
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "%if::\n```bash\nexit 1\n```\nReview stale docs.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:stale",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )

    with (
        override_flags(typed_launch_units=True),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd") as launch_batch,
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_succeeded"
    launch_batch.assert_not_called()
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", outcome.run_id).read_text(
        encoding="utf-8"
    )
    assert "Typed admission:" in output
    assert "1 skipped" in output
    assert "once-per duplicate" not in output


def test_clan_partial_launch_keeps_started_member_recorded(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "split",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "prompt": "First.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "toobig-@",
                    "dedupe_key": "split:first",
                },
                {
                    "prompt": "Second.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "toobig-@",
                    "dedupe_key": "split:second",
                },
            ],
        },
    )
    started = SimpleNamespace(
        pid=401,
        agent_name="toobig-0.first",
        timestamp="260719_130000",
    )

    def _fail_batch(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise MultiPromptPartialLaunchError(
            [started],
            RuntimeError("second spawn failed"),
        )

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agents_from_cwd", side_effect=_fail_batch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="split",
            chop=ChopConfig(name="split", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "action_failed"
    assert [launch["pid"] for launch in outcome.launches] == [401]
    assert outcome.run_id is not None
    entry = read_chop_run("split", "split", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert [launch["pid"] for launch in entry.launches] == [401]


def test_runner_launches_proposals_in_order_with_wait_directive(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "env": {"MODE": "refresh"},
                },
                {
                    "prompt": "Polish.",
                    "workspace": "git:sase",
                    "wait_on": 0,
                },
            ],
        },
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        index = len(calls)
        calls.append((prompt, extra_env))
        return SimpleNamespace(
            pid=100 + index,
            agent_name=f"actual.{index + 1}",
            workspace_num=index + 1,
            workspace_dir=f"/workspace/{index + 1}",
            project_name="sase",
            workflow_name=f"ace(run)-{index}",
            cl_name="sase",
            timestamp=f"260718_12000{index}",
            artifacts_dir=f"/artifacts/{index}",
        )

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="docs", description=""),
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "launched"
    assert len(calls) == 2
    assert "%wait:actual.1" in calls[1][0]
    assert calls[0][1]["MODE"] == "refresh"
    assert calls[0][1]["SASE_CHOP_RUN_ID"] == outcome.run_id
    assert calls[1][1]["SASE_CHOP_RUN_ID"] == outcome.run_id
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert entry.status == "launched"
    assert entry.finished_at is None
    assert [launch["pid"] for launch in entry.launches] == [100, 101]


def test_runner_launches_with_wait_relinked_across_duplicate(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    chop = ChopConfig(name="docs", description="")
    seed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Seed.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:middle",
                }
            ]
        },
    )
    apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=seed,
        persist=True,
    )
    _result_script(
        tmp_path,
        "docs",
        {
            "schema_version": 1,
            "status": "ok",
            "proposed_launches": [
                {"id": "root", "prompt": "Root.", "workspace": "git:sase"},
                {
                    "id": "middle",
                    "prompt": "Middle.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:middle",
                    "wait_on": "root",
                },
                {
                    "prompt": "Tail.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:tail",
                    "wait_on": "middle",
                },
            ],
        },
    )
    calls: list[str] = []

    def _launch(prompt: str, *, extra_env: dict[str, str]) -> SimpleNamespace:
        del extra_env
        index = len(calls)
        calls.append(prompt)
        return SimpleNamespace(
            pid=200 + index,
            agent_name=f"actual.{index + 1}",
        )

    with (
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        patch("sase.axe.chop_runner.launch_agent_from_cwd", side_effect=_launch),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=chop,
            axe_config=_config(tmp_path),
        )

    assert outcome.status == "launched"
    assert len(calls) == 2
    assert "%wait:" not in calls[0]
    assert "%wait:actual.1" in calls[1]
    assert outcome.proposals[1]["validation"] == "duplicate"
    assert outcome.proposals[2]["wait_on"] == "root"
    assert outcome.run_id is not None
    entry = read_chop_run("docs", "docs", outcome.run_id)
    assert entry is not None
    assert [launch["index"] for launch in entry.launches] == [0, 2]
    assert entry.launches[1]["wait_on"] == "root"
    assert entry.launches[1]["wait_name"] == "actual.1"


def test_verbose_flag_reaches_script_environment(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "verbose", "printf '%s' \"$SASE_CHOP_VERBOSE\"\n")
    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        outcome = run_configured_chop_once(
            lumberjack_name="checks",
            chop=ChopConfig(name="verbose", description=""),
            axe_config=_config(tmp_path),
            chop_verbose=True,
        )
    assert outcome.status == "success"
    assert outcome.run_id is not None
    entry = read_chop_run("checks", "verbose", outcome.run_id)
    assert entry is not None
    assert entry.output_bytes == 1


def _clan_unit(
    logical_id: str,
    *,
    identity: str,
    clan_declared: bool,
    clan: str | None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=0,
        payload=AgentUnitWire(
            prompt="Body.",
            identity=identity,
            identity_explicit=True,
            clan=clan,
            clan_declared=clan_declared,
            clan_tribe=clan_tribe,
            clan_summary=clan_summary,
        ),
    )


def _clan_unit_metadata(
    logical_id: str,
    *,
    clan: str,
    member_id: str,
    agent_name: str,
    declares_clan: bool,
    clan_tribe: str = "chop",
    clan_summary: str | None = "[bold]Large[/bold]",
) -> dict[str, object]:
    return {
        "lumberjack_name": "split",
        "chop_name": "split",
        "run_id": "run-clan",
        "logical_id": logical_id,
        "source_order": 0,
        "proposal_index": 0,
        "proposal_id": None,
        "agent_name": agent_name,
        "clan": clan,
        "member_id": member_id,
        "declares_clan": declares_clan,
        "clan_tribe": clan_tribe,
        "clan_summary": clan_summary,
        "workspace": "git:sase",
        "dedupe_key": None,
        "wait_on": None,
        "wait_name": None,
        "env": {},
    }


def _capturing_launch(
    calls: list[tuple[str, dict[str, str]]], agent_name: str
) -> Callable[..., list[SimpleNamespace]]:
    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [SimpleNamespace(pid=len(calls), agent_name=agent_name, timestamp="")]

    return _launch


def _clan_marker_path(bundle_dir: Path, clan: str) -> Path:
    return admission_dir(bundle_dir) / UNITS_DIRNAME / f"clan-declared-{clan}.json"


def test_typed_clan_dispatch_declares_the_originally_planned_declarer(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    unit = _clan_unit(
        "unit-1",
        identity="toobig-x.first",
        clan_declared=True,
        clan="toobig-x",
        clan_tribe="chop",
        clan_summary="[bold]Large[/bold]",
    )
    metadata = {
        "unit-1": _clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        )
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.first"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, message, results = dispatcher(unit, "fp-1")

    assert ok is True
    assert identity == "toobig-x.first"
    assert message is None
    assert len(results) == 1
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.first"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"
    assert _clan_marker_path(tmp_path, "toobig-x").exists()


def test_typed_clan_dispatch_promotes_next_member_when_declarer_skipped(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    # unit-1 is the statically planned declarer, but admission skipped it
    # (its `%if` predicate was false) so the dispatcher never runs for it.
    joiner_unit = _clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": _clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": _clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, _message, _results = dispatcher(joiner_unit, "fp-2")

    assert ok is True
    assert identity == "toobig-x.second"
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.second"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"


def test_typed_clan_dispatch_promotes_after_several_leading_skips(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    # unit-1 and unit-2 are both skipped; only unit-3 ever dispatches.
    third_unit = _clan_unit(
        "unit-3", identity="third", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        f"unit-{n}": _clan_unit_metadata(
            f"unit-{n}",
            clan="toobig-x",
            member_id=name,
            agent_name=f"toobig-x.{name}",
            declares_clan=(n == 1),
        )
        for n, name in ((1, "first"), (2, "second"), (3, "third"))
    }
    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.third"),
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(third_unit, "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.name == "toobig-x.third"
    assert directives.clan_declared is True


def test_typed_clan_dispatch_all_skipped_batch_writes_no_clan_marker(
    tmp_path: Path,
) -> None:
    metadata = {
        "unit-1": _clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        )
    }
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None
    # The dispatcher exists, but admission never called it because every
    # member was skipped or condition-errored, so no clan is ever claimed.
    assert not _clan_marker_path(tmp_path, "toobig-x").exists()


def test_typed_clan_dispatch_promotion_is_durable_across_fresh_dispatcher(
    tmp_path: Path,
) -> None:
    """A restarted coordinator builds a brand-new dispatcher closure; the
    declarer claim must still come from the durable bundle dir, not from
    Python state carried over in the previous closure."""
    pytest.importorskip("sase_core_rs")
    declarer_unit = _clan_unit(
        "unit-1",
        identity="toobig-x.first",
        clan_declared=True,
        clan="toobig-x",
        clan_tribe="chop",
        clan_summary="[bold]Large[/bold]",
    )
    joiner_unit = _clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": _clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": _clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []

    dispatcher_1 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.first"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_1 is not None
    dispatcher_1(declarer_unit, "fp-1")

    dispatcher_2 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_2 is not None
    dispatcher_2(joiner_unit, "fp-2")

    assert len(calls) == 2
    _, first_directives = extract_prompt_directives(calls[0][0])
    _, second_directives = extract_prompt_directives(calls[1][0])
    assert first_directives.clan_declared is True
    assert second_directives.clan_declared is False
    assert second_directives.clan == "toobig-x"
    assert second_directives.name == "toobig-x.second"


def test_typed_clan_dispatch_failed_declarer_blocks_second_declaration(
    tmp_path: Path,
) -> None:
    """A declarer launch that fails must still hold the declarer claim, so a
    later member cannot accidentally declare the same clan a second time."""
    pytest.importorskip("sase_core_rs")
    declarer_unit = _clan_unit(
        "unit-1", identity="toobig-x.first", clan_declared=True, clan="toobig-x"
    )
    joiner_unit = _clan_unit(
        "unit-2", identity="second", clan_declared=False, clan="toobig-x"
    )
    metadata = {
        "unit-1": _clan_unit_metadata(
            "unit-1",
            clan="toobig-x",
            member_id="first",
            agent_name="toobig-x.first",
            declares_clan=True,
        ),
        "unit-2": _clan_unit_metadata(
            "unit-2",
            clan="toobig-x",
            member_id="second",
            agent_name="toobig-x.second",
            declares_clan=False,
        ),
    }

    def _empty_launch(
        prompt: str, *, extra_env: dict[str, str]
    ) -> list[SimpleNamespace]:
        del prompt, extra_env
        return []

    dispatcher_1 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_empty_launch,
        bundle_dir=tmp_path,
    )
    assert dispatcher_1 is not None
    ok, identity, message, results = dispatcher_1(declarer_unit, "fp-1")
    assert ok is False
    assert identity is None
    assert message == "agent_dispatch_produced_no_results"
    assert results == []
    assert _clan_marker_path(tmp_path, "toobig-x").exists()

    calls: list[tuple[str, dict[str, str]]] = []
    dispatcher_2 = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "toobig-x.second"),
        bundle_dir=tmp_path,
    )
    assert dispatcher_2 is not None
    dispatcher_2(joiner_unit, "fp-2")

    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.clan_declared is False
    assert directives.clan == "toobig-x"
    assert directives.name == "toobig-x.second"


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
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "clan": "toobig-x",
                    "clan_summary": "[bold]Large[/bold]",
                },
                {
                    "id": "second",
                    "prompt": "%if::\n```bash\nexit 1\n```\nSecond.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "clan": "toobig-x",
                },
                {
                    "id": "third",
                    "prompt": "%if::\n```bash\nexit 0\n```\nThird.",
                    "workspace": "git:sase",
                    "agent_name": "third",
                    "clan": "toobig-x",
                },
            ]
        },
    )
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda _prompt: _known_project_resolver(repo),
    )
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
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "toobig-x.third"
    assert directives.clan == "toobig-x"
    assert directives.clan_declared is True
    assert directives.clan_tribe == "chop"
    assert directives.clan_summary == "[bold]Large[/bold]"
    assert len(launches) == 1
    assert launches[0]["clan"] == "toobig-x"
