"""Typed clan-dispatch coverage for chop proposal launches."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_admission_store import (
    UNITS_DIRNAME,
    admission_dir,
    write_unit_receipt,
)
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_typed_admission import make_axe_chop_agent_dispatcher
from sase.core.agent_launch_wire import AgentUnitWire, LaunchUnitWire
from sase.feature_flags import override_flags
from sase.xprompt import extract_vcs_workflow_tag
from sase.xprompt.directives import extract_prompt_directives
from tests._axe_chop_proposal_launch_helpers import patch_condition_workspace_lease

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


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


def _wait_unit(logical_id: str, *, identity: str) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=0,
        payload=AgentUnitWire(
            prompt="Body.",
            identity=identity,
            identity_explicit=True,
        ),
    )


def _wait_unit_metadata(
    logical_id: str,
    *,
    index: int,
    proposal_id: str | None,
    agent_name: str,
    wait_on: int | str | None = None,
    wait_logical_id: str | None = None,
) -> dict[str, object]:
    return {
        "lumberjack_name": "split",
        "chop_name": "split",
        "run_id": "run-wait",
        "logical_id": logical_id,
        "source_order": index,
        "proposal_index": index,
        "proposal_id": proposal_id,
        "agent_name": agent_name,
        "clan": None,
        "member_id": None,
        "declares_clan": False,
        "clan_tribe": None,
        "clan_summary": None,
        "workspace": "git:sase",
        "dedupe_key": None,
        "wait_on": wait_on,
        "wait_name": None,
        "wait_logical_id": wait_logical_id,
        "env": {},
    }


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


def test_typed_chop_dispatch_restores_wait_from_durable_receipt(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": _wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": _wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "actual.second"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, identity, message, _results = dispatcher(
        _wait_unit("unit-2", identity="second"), "fp-2"
    )

    assert ok is True
    assert identity == "actual.second"
    assert message is None
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert recorded[0]["wait_on"] == "first"
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_preserves_index_zero_wait_reference(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": _wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id=None,
            agent_name="planned.first",
        ),
        "unit-2": _wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id=None,
            agent_name="planned.second",
            wait_on=0,
            wait_logical_id="unit-1",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "actual.second"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(_wait_unit("unit-2", identity="second"), "fp-2")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert recorded[0]["wait_on"] == 0
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_relinks_wait_across_skipped_middle_member(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    root = admission_dir(tmp_path)
    write_unit_receipt(
        root,
        logical_id="unit-1",
        fingerprint="fp-1",
        identity="actual.first",
    )
    metadata = {
        "unit-1": _wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": _wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
        "unit-3": _wait_unit_metadata(
            "unit-3",
            index=2,
            proposal_id="third",
            agent_name="planned.third",
            wait_on="second",
            wait_logical_id="unit-2",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "actual.third"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(_wait_unit("unit-3", identity="third"), "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == ["actual.first"]
    assert "planned.second" not in calls[0][0]
    assert recorded[0]["wait_on"] == "first"
    assert recorded[0]["wait_name"] == "actual.first"


def test_typed_chop_dispatch_drops_wait_when_no_ancestor_launched(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    metadata = {
        "unit-1": _wait_unit_metadata(
            "unit-1",
            index=0,
            proposal_id="first",
            agent_name="planned.first",
        ),
        "unit-2": _wait_unit_metadata(
            "unit-2",
            index=1,
            proposal_id="second",
            agent_name="planned.second",
            wait_on="first",
            wait_logical_id="unit-1",
        ),
        "unit-3": _wait_unit_metadata(
            "unit-3",
            index=2,
            proposal_id="third",
            agent_name="planned.third",
            wait_on="second",
            wait_logical_id="unit-2",
        ),
    }
    calls: list[tuple[str, dict[str, str]]] = []
    recorded: list[dict[str, object]] = []
    dispatcher = make_axe_chop_agent_dispatcher(
        {"unit_dispatch_metadata": metadata},
        launch_agents_from_cwd_fn=_capturing_launch(calls, "actual.third"),
        launch_recorded_fn=recorded.append,
        bundle_dir=tmp_path,
    )
    assert dispatcher is not None

    ok, *_rest = dispatcher(_wait_unit("unit-3", identity="third"), "fp-3")

    assert ok is True
    _, directives = extract_prompt_directives(calls[0][0])
    assert directives.wait == []
    assert "planned.second" not in calls[0][0]
    assert recorded[0]["wait_on"] is None
    assert recorded[0]["wait_name"] is None


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
