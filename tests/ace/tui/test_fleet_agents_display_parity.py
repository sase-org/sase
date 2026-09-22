from __future__ import annotations

from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from tests.ace.tui.fleet_fixture import (
    fleet_host_response,
    fleet_installation_id,
    fleet_summary,
)

from ._fleet_display_parity_shared import (
    _PARITY_INTENT,
    _PARITY_PROJECT_FILE,
    _PARITY_REMOTE_ALIAS,
    _PARITY_STARTED_AT,
    _at,
    _normalized_collapsed_render,
    _normalized_rendered_rows,
    _panel_signature,
    _rendered_rows,
    _tree_signature,
    _visible_node_count,
)


def test_project_fleet_agents_render_like_local_rows_modulo_host_chip() -> None:
    """One body of work renders the same locally and through serialized wire."""
    local_rows = _local_parity_rows()
    remote_rows = list(
        project_fleet_agents(catalog_response=_remote_parity_response()).fleet_rows
    )

    assert _tree_signature(remote_rows) == _tree_signature(local_rows)
    assert _normalized_rendered_rows(remote_rows) == _normalized_rendered_rows(
        local_rows
    )
    assert _normalized_collapsed_render(remote_rows) == _normalized_collapsed_render(
        local_rows
    )
    assert _panel_signature(remote_rows) == _panel_signature(local_rows)
    assert _visible_node_count(remote_rows) == _visible_node_count(local_rows)

    remote_rendered = _rendered_rows(remote_rows)
    for row, rendered in zip(remote_rows, remote_rendered, strict=True):
        if (
            row.is_family_member_child
            or row.is_monitor
            or row.is_gate
            or row.is_proc_shell
        ):
            assert f"{_PARITY_REMOTE_ALIAS} " not in rendered
        else:
            assert f"{_PARITY_REMOTE_ALIAS} " in rendered


def _local_parity_rows() -> list[Agent]:
    agents = [
        _local_parity_agent(
            "solo.wait",
            "solo-wait",
            "WAITING",
            role="root",
            start_time=_at(_PARITY_STARTED_AT + 360),
            run_start_time=_at(_PARITY_STARTED_AT + 360),
        ),
        _local_parity_agent(
            "parity-family",
            "fam-root",
            "TESTING",
            role="root",
            start_time=_at(_PARITY_STARTED_AT),
            run_start_time=_at(_PARITY_STARTED_AT),
        ),
        _local_parity_agent(
            "parity-family--code",
            "fam-member",
            "DONE",
            parent="fam-root",
            role="member",
            agent_family="parity-family",
            role_suffix="--code",
            start_time=_at(_PARITY_STARTED_AT + 60),
            run_start_time=_at(_PARITY_STARTED_AT + 60),
            stop_time=_at(_PARITY_STARTED_AT + 300),
        ),
        _local_parity_agent(
            "parity-family--mon",
            "fam-mon",
            "TESTING",
            parent="fam-root",
            role="monitor",
            agent_family="parity-family",
            role_suffix="--mon",
            monitor_id="mon",
            monitor_state="running",
            monitor_start_status="TESTING",
            start_time=_at(_PARITY_STARTED_AT + 120),
            run_start_time=_at(_PARITY_STARTED_AT + 120),
        ),
        _local_parity_agent(
            "parity-family--gate",
            "fam-gate",
            "RUNNING",
            parent="fam-root",
            role="gate",
            agent_family="parity-family",
            role_suffix="--gate",
            gate_id="gate",
            gate_state="pending",
            start_time=_at(_PARITY_STARTED_AT + 180),
            run_start_time=_at(_PARITY_STARTED_AT + 180),
        ),
        _local_parity_agent(
            "parity-family--proc",
            "fam-proc",
            "RUNNING",
            parent="fam-root",
            role="proc",
            agent_family="parity-family",
            role_suffix="--proc",
            agent_type=AgentType.PROC_SHELL,
            proc_id="proc",
            start_time=_at(_PARITY_STARTED_AT + 200),
            run_start_time=_at(_PARITY_STARTED_AT + 200),
        ),
        _local_parity_agent(
            "parity-family--old",
            "fam-old",
            "DONE",
            parent="fam-root",
            role="historical_shell",
            agent_family="parity-family",
            role_suffix="--old",
            start_time=_at(_PARITY_STARTED_AT - 3600),
            run_start_time=_at(_PARITY_STARTED_AT - 3600),
            stop_time=_at(_PARITY_STARTED_AT - 1800),
        ),
        _local_parity_agent(
            "done-family",
            "done-root",
            "TALE DONE",
            role="root",
            start_time=_at(_PARITY_STARTED_AT - 7200),
            run_start_time=_at(_PARITY_STARTED_AT - 7200),
            stop_time=_at(_PARITY_STARTED_AT - 5400),
        ),
        _local_parity_agent(
            "done-family--plan",
            "done-plan",
            "TALE DONE",
            parent="done-root",
            role="historical_shell",
            agent_family="done-family",
            role_suffix="--plan",
            start_time=_at(_PARITY_STARTED_AT - 7200),
            run_start_time=_at(_PARITY_STARTED_AT - 7200),
            stop_time=_at(_PARITY_STARTED_AT - 6000),
        ),
        _local_parity_agent(
            "done-family--code",
            "done-code",
            "TALE DONE",
            parent="done-root",
            role="historical_shell",
            agent_family="done-family",
            role_suffix="--code",
            start_time=_at(_PARITY_STARTED_AT - 6000),
            run_start_time=_at(_PARITY_STARTED_AT - 6000),
            stop_time=_at(_PARITY_STARTED_AT - 5400),
        ),
        _local_parity_agent(
            "epic.work",
            "epic-root",
            "WORKING TALE",
            role="root",
            tribe="epic",
            clan_tribe="epic",
            start_time=_at(_PARITY_STARTED_AT + 90),
            run_start_time=_at(_PARITY_STARTED_AT + 150),
        ),
        _local_parity_agent(
            "epic.work--code",
            "epic-code",
            "WORKING TALE",
            parent="epic-root",
            role="member",
            agent_family="epic.work",
            role_suffix="--code",
            tribe="epic",
            clan_tribe="epic",
            start_time=_at(_PARITY_STARTED_AT + 150),
            run_start_time=_at(_PARITY_STARTED_AT + 150),
        ),
        _local_parity_agent(
            "epic.done",
            "epic-done",
            "EPIC CREATED √",
            role="root",
            tribe="epic",
            clan_tribe="epic",
            start_time=_at(_PARITY_STARTED_AT - 4000),
            run_start_time=_at(_PARITY_STARTED_AT - 4000),
            stop_time=_at(_PARITY_STARTED_AT - 3000),
        ),
        _local_parity_agent(
            "research.alpha",
            "clan-a",
            "DONE",
            role="root",
            agent_clan="research",
            agent_clan_generation="g1",
            clan_tribe="core",
            tribe="core",
            start_time=_at(_PARITY_STARTED_AT + 240),
            run_start_time=_at(_PARITY_STARTED_AT + 240),
            stop_time=_at(_PARITY_STARTED_AT + 360),
        ),
        _local_parity_agent(
            "research.beta",
            "clan-b",
            "FAILED",
            role="root",
            agent_clan="research",
            agent_clan_generation="g1",
            clan_tribe="core",
            tribe="core",
            start_time=_at(_PARITY_STARTED_AT + 300),
            run_start_time=_at(_PARITY_STARTED_AT + 300),
            stop_time=_at(_PARITY_STARTED_AT + 420),
        ),
    ]
    return normalize_loaded_agents(agents, [], is_process_running=lambda _pid: True)


def _local_parity_agent(
    name: str,
    suffix: str,
    status: str,
    *,
    parent: str | None = None,
    role: str | None = None,
    **overrides: object,
) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "sase-main",
        "project_file": _PARITY_PROJECT_FILE,
        "project_display_name": "SASE",
        "status": status,
        "start_time": _at(_PARITY_STARTED_AT),
        "run_start_time": _at(_PARITY_STARTED_AT),
        "raw_suffix": suffix,
        "agent_name": name,
        "agent_family_role": role,
        "parent_timestamp": parent,
        "llm_provider": "codex",
        "model": "gpt-5",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _remote_parity_response() -> dict[str, object]:
    installation_id = fleet_installation_id("a")

    def summary(
        agent_id: str,
        run_id: str,
        status: str,
        **overrides: object,
    ) -> dict[str, object]:
        defaults: dict[str, object] = {
            "installation_id": installation_id,
            "project_id": "sase-main",
            "project_name": "SASE",
            "project_label": "SASE",
            "agent_id": agent_id,
            "run_id": run_id,
            "agent_name": agent_id,
            "status": status,
            "provider": "codex",
            "model": "gpt-5",
            "bounded_intent": _PARITY_INTENT,
            "started_at_unix": _PARITY_STARTED_AT,
        }
        defaults.update(overrides)
        return fleet_summary(**defaults)  # type: ignore[arg-type]

    summaries = (
        summary(
            "solo.wait",
            "solo-wait",
            "waiting",
            family_id=None,
            started_at_unix=_PARITY_STARTED_AT + 360,
        ),
        summary(
            "parity-family",
            "fam-root",
            "TESTING",
            family_id="parity-family",
            family_role="root",
        ),
        summary(
            "parity-family--code",
            "fam-member",
            "done",
            family_id="parity-family",
            family_role="member",
            parent_timestamp="fam-root",
            started_at_unix=_PARITY_STARTED_AT + 60,
            stopped_at_unix=_PARITY_STARTED_AT + 300,
        ),
        summary(
            "parity-family--mon",
            "fam-mon",
            "TESTING",
            family_id="parity-family",
            family_role="monitor",
            row_kind="monitor",
            parent_timestamp="fam-root",
            started_at_unix=_PARITY_STARTED_AT + 120,
            occupied_runner_slot=False,
        ),
        summary(
            "parity-family--gate",
            "fam-gate",
            "running",
            family_id="parity-family",
            family_role="gate",
            row_kind="gate",
            parent_timestamp="fam-root",
            started_at_unix=_PARITY_STARTED_AT + 180,
            occupied_runner_slot=False,
        ),
        summary(
            "parity-family--proc",
            "fam-proc",
            "running",
            family_id="parity-family",
            family_role="proc",
            row_kind="proc",
            parent_timestamp="fam-root",
            started_at_unix=_PARITY_STARTED_AT + 200,
            occupied_runner_slot=False,
        ),
        summary(
            "parity-family--old",
            "fam-old",
            "done",
            family_id="parity-family",
            family_role="historical_shell",
            row_kind="historical_shell",
            parent_timestamp="fam-root",
            started_at_unix=_PARITY_STARTED_AT - 3600,
            stopped_at_unix=_PARITY_STARTED_AT - 1800,
            current_instance=False,
        ),
        summary(
            "done-family",
            "done-root",
            "TALE DONE",
            family_id="done-family",
            family_role="root",
            started_at_unix=_PARITY_STARTED_AT - 7200,
            stopped_at_unix=_PARITY_STARTED_AT - 5400,
            current_instance=False,
        ),
        summary(
            "done-family--plan",
            "done-plan",
            "TALE DONE",
            family_id="done-family",
            family_role="historical_shell",
            row_kind="historical_shell",
            parent_timestamp="done-root",
            started_at_unix=_PARITY_STARTED_AT - 7200,
            stopped_at_unix=_PARITY_STARTED_AT - 6000,
            current_instance=False,
        ),
        summary(
            "done-family--code",
            "done-code",
            "TALE DONE",
            family_id="done-family",
            family_role="historical_shell",
            row_kind="historical_shell",
            parent_timestamp="done-root",
            started_at_unix=_PARITY_STARTED_AT - 6000,
            stopped_at_unix=_PARITY_STARTED_AT - 5400,
            current_instance=False,
        ),
        summary(
            "epic.work",
            "epic-root",
            "WORKING TALE",
            family_id="epic.work",
            family_role="root",
            tribe="epic",
            clan_tribe="epic",
            started_at_unix=_PARITY_STARTED_AT + 90,
            run_started_at_unix=_PARITY_STARTED_AT + 150,
        ),
        summary(
            "epic.work--code",
            "epic-code",
            "WORKING TALE",
            family_id="epic.work",
            family_role="member",
            parent_timestamp="epic-root",
            tribe="epic",
            clan_tribe="epic",
            started_at_unix=_PARITY_STARTED_AT + 150,
            run_started_at_unix=_PARITY_STARTED_AT + 150,
        ),
        summary(
            "epic.done",
            "epic-done",
            "EPIC CREATED √",
            family_id=None,
            family_role="root",
            tribe="epic",
            clan_tribe="epic",
            started_at_unix=_PARITY_STARTED_AT - 4000,
            stopped_at_unix=_PARITY_STARTED_AT - 3000,
            current_instance=False,
        ),
        summary(
            "research.alpha",
            "clan-a",
            "done",
            family_id=None,
            agent_clan="research",
            agent_clan_generation="g1",
            clan_tribe="core",
            tribe="core",
            started_at_unix=_PARITY_STARTED_AT + 240,
            stopped_at_unix=_PARITY_STARTED_AT + 360,
        ),
        summary(
            "research.beta",
            "clan-b",
            "failed",
            family_id=None,
            agent_clan="research",
            agent_clan_generation="g1",
            clan_tribe="core",
            tribe="core",
            started_at_unix=_PARITY_STARTED_AT + 300,
            stopped_at_unix=_PARITY_STARTED_AT + 420,
        ),
    )
    return fleet_host_response(
        alias=_PARITY_REMOTE_ALIAS,
        installation_id=installation_id,
        summaries=summaries,
    )
