from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.fleet_fixture import (
    fleet_host_response,
    fleet_installation_id,
    fleet_summary,
)

_PARITY_NOW = datetime(2026, 9, 13, 12, 10)
_PARITY_STARTED_AT = 1_789_300_800.0
_PARITY_PROJECT_FILE = "/tmp/sase-main/project.yml"
_PARITY_REMOTE_ALIAS = "apollo"
_PARITY_INTENT = "prove display parity"


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

    remote_rendered = _rendered_rows(remote_rows)
    for row, rendered in zip(remote_rows, remote_rendered, strict=True):
        if row.is_family_member_child:
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
            start_time=datetime(2026, 9, 13, 12, 6),
            run_start_time=datetime(2026, 9, 13, 12, 6),
        ),
        _local_parity_agent("parity-family", "fam-root", "RUNNING", role="root"),
        _local_parity_agent(
            "parity-family--code",
            "fam-member",
            "DONE",
            parent="fam-root",
            role="member",
            agent_family="parity-family",
            role_suffix="--code",
            start_time=datetime(2026, 9, 13, 12, 1),
            run_start_time=datetime(2026, 9, 13, 12, 1),
            stop_time=datetime(2026, 9, 13, 12, 5),
        ),
        _local_parity_agent(
            "parity-family--mon",
            "fam-mon",
            "RUNNING",
            parent="fam-root",
            role="monitor",
            agent_family="parity-family",
            role_suffix="--mon",
            monitor_id="mon",
            monitor_state="running",
            start_time=datetime(2026, 9, 13, 12, 2),
            run_start_time=datetime(2026, 9, 13, 12, 2),
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
            start_time=datetime(2026, 9, 13, 12, 3),
            run_start_time=datetime(2026, 9, 13, 12, 3),
        ),
        _local_parity_agent(
            "parity-family--old",
            "fam-old",
            "DONE",
            parent="fam-root",
            role="historical_shell",
            agent_family="parity-family",
            role_suffix="--old",
            start_time=datetime(2026, 9, 13, 11, 0),
            run_start_time=datetime(2026, 9, 13, 11, 0),
            stop_time=datetime(2026, 9, 13, 11, 30),
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
            start_time=datetime(2026, 9, 13, 12, 4),
            run_start_time=datetime(2026, 9, 13, 12, 4),
            stop_time=datetime(2026, 9, 13, 12, 6),
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
            start_time=datetime(2026, 9, 13, 12, 5),
            run_start_time=datetime(2026, 9, 13, 12, 5),
            stop_time=datetime(2026, 9, 13, 12, 7),
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
        "start_time": datetime(2026, 9, 13, 12, 0),
        "run_start_time": datetime(2026, 9, 13, 12, 0),
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
            "running",
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
            "running",
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


def _rendered_rows(rows: list[Agent]) -> list[str]:
    return [
        format_agent_option(
            row,
            index,
            is_selected=False,
            now=_PARITY_NOW,
            show_machine_chip=True,
        )[0].plain
        for index, row in enumerate(rows)
    ]


def _normalized_rendered_rows(rows: list[Agent]) -> list[str]:
    return [_without_remote_host_chip(text) for text in _rendered_rows(rows)]


def _normalized_collapsed_render(rows: list[Agent]) -> list[str]:
    visible, fold_counts = filter_agents_by_fold_state(rows, FoldStateManager())
    rendered = [
        format_agent_option(
            row,
            index,
            is_selected=False,
            fold_annotation=compute_fold_annotation(row, fold_counts, set()),
            now=_PARITY_NOW,
            show_machine_chip=True,
        )[0].plain
        for index, row in enumerate(visible)
    ]
    return [_without_remote_host_chip(text) for text in rendered]


def _without_remote_host_chip(text: str) -> str:
    return text.replace(f"{_PARITY_REMOTE_ALIAS} ", "")


def _tree_signature(rows: list[Agent]) -> list[tuple[object, ...]]:
    row_by_raw = {row.raw_suffix: _row_key(row) for row in rows if row.raw_suffix}
    row_by_fold = {
        fold_key: _row_key(row)
        for row in rows
        if (fold_key := agent_fold_key(row)) is not None
    }

    def parent_key(row: Agent) -> object:
        key = row.tree_parent_key or row.parent_timestamp
        if key is None:
            return None
        return row_by_fold.get(key) or row_by_raw.get(key)

    return [
        (
            _row_key(row),
            parent_key(row),
            row.status,
            row.is_clan_container,
            row.is_family_container_row,
            row.is_monitor,
            row.is_gate,
            row.is_proc_shell,
            tuple(_row_key(child) for child in row.followup_agents),
            tuple(_row_key(child) for child in row.runtime_children),
        )
        for row in rows
    ]


def _row_key(row: Agent) -> tuple[object, ...]:
    if row.is_clan_container:
        return ("clan", row.agent_clan, row.agent_clan_generation)
    return (
        "row",
        row.agent_name,
        row.agent_family_role,
        row.agent_clan,
        row.agent_clan_generation,
    )
