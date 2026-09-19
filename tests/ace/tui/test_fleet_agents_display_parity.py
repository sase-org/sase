from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._display_panel_titles import (
    agent_panel_border_title,
    agent_panel_counts,
)
from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import agents_for_panel, panel_keys_for
from sase.ace.tui.models.agent_time import compute_leaf_row_runtime, compute_row_runtime
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.core.time import local_now
from tests.ace.tui.fleet_fixture import (
    fleet_host_response,
    fleet_installation_id,
    fleet_summary,
)

_PARITY_TZ = local_now().tzinfo
_PARITY_NOW = datetime(2026, 9, 13, 12, 10, tzinfo=_PARITY_TZ)
_PARITY_STARTED_AT = 1_789_300_800.0
_PARITY_PROJECT_FILE = "/tmp/sase-main/project.yml"
_PARITY_REMOTE_ALIAS = "apollo"
_PARITY_INTENT = "prove display parity"


def _at(unix: float) -> datetime:
    return datetime.fromtimestamp(unix, tz=_PARITY_TZ)


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


def _visible_node_count(rows: list[Agent]) -> int:
    visible, _fold_counts = filter_agents_by_fold_state(rows, FoldStateManager())
    return len(visible)


def _panel_signature(rows: list[Agent]) -> list[tuple[object, ...]]:
    signature: list[tuple[object, ...]] = []
    for key in panel_keys_for(rows):
        slice_rows = agents_for_panel(rows, key)
        counts = agent_panel_counts(slice_rows, set())
        title = agent_panel_border_title(key, counts.lane_count, counts=counts)
        signature.append(
            (
                key,
                counts.lane_count,
                counts.running,
                counts.waiting,
                counts.read,
                counts.failed,
                title.plain,
            )
        )
    return signature


def test_remote_default_tribe_panel_counts_include_done_lanes() -> None:
    """A mixed remote panel uses the shared family/clan counters, including done."""
    installation_id = fleet_installation_id("a")

    def summary(agent_id: str, run_id: str, status: str, **overrides: object) -> dict:
        payload: dict[str, object] = {
            "installation_id": installation_id,
            "project_id": "sase-main",
            "project_name": "SASE",
            "agent_id": agent_id,
            "run_id": run_id,
            "agent_name": agent_id,
            "status": status,
            "bounded_intent": _PARITY_INTENT,
            "started_at_unix": _PARITY_STARTED_AT,
        }
        payload.update(overrides)
        return fleet_summary(**payload)  # type: ignore[arg-type]

    response = fleet_host_response(
        alias=_PARITY_REMOTE_ALIAS,
        installation_id=installation_id,
        summaries=(
            summary("run.one", "run-one", "RUNNING", family_id=None),
            summary(
                "wait.one",
                "wait-one",
                "WAITING",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT + 60,
            ),
            summary(
                "done.family",
                "done-root",
                "TALE DONE",
                family_id="done.family",
                family_role="root",
                started_at_unix=_PARITY_STARTED_AT - 4000,
                stopped_at_unix=_PARITY_STARTED_AT - 2000,
                current_instance=False,
            ),
            summary(
                "done.family--old",
                "done-old",
                "TALE DONE",
                family_id="done.family",
                family_role="historical_shell",
                row_kind="historical_shell",
                parent_timestamp="done-root",
                started_at_unix=_PARITY_STARTED_AT - 4000,
                stopped_at_unix=_PARITY_STARTED_AT - 3000,
                current_instance=False,
            ),
            summary(
                "done.two",
                "done-two",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 1800,
                stopped_at_unix=_PARITY_STARTED_AT - 1200,
                current_instance=False,
            ),
            summary(
                "done.three",
                "done-three",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 900,
                stopped_at_unix=_PARITY_STARTED_AT - 600,
                current_instance=False,
            ),
            summary(
                "done.four",
                "done-four",
                "DONE",
                family_id=None,
                started_at_unix=_PARITY_STARTED_AT - 500,
                stopped_at_unix=_PARITY_STARTED_AT - 400,
                current_instance=False,
            ),
        ),
    )
    rows = list(project_fleet_agents(catalog_response=response).fleet_rows)
    counts = agent_panel_counts(agents_for_panel(rows, None), set())
    title = agent_panel_border_title(None, counts.lane_count, counts=counts)
    assert counts.lane_count == 6
    assert (counts.running, counts.waiting, counts.read) == (1, 1, 4)
    assert "[R1 W1 D4]" in title.plain
    nested = [row for row in rows if row.agent_name == "done.family--old"]
    assert nested and nested[0].is_family_member_child


def test_remote_family_elapsed_and_current_run_survive_projection() -> None:
    started = 1_800_000_000.0
    run_started = 1_800_000_600.0
    observed = 1_800_001_200.0
    summary = fleet_summary(
        agent_id="elapsed-family",
        agent_name="elapsed-family",
        status="WORKING TALE",
        started_at_unix=started,
        run_started_at_unix=run_started,
        observed_at_unix=observed,
        family_id="elapsed-family",
        family_role="root",
    )
    child = fleet_summary(
        agent_id="elapsed-family--code",
        run_id="run-code",
        agent_name="elapsed-family--code",
        status="WORKING TALE",
        family_id="elapsed-family",
        family_role="member",
        parent_timestamp="run-1",
        started_at_unix=run_started,
        run_started_at_unix=run_started,
        observed_at_unix=observed,
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(summary, child),
        observed_at_unix=observed,
    )
    rows = list(project_fleet_agents(catalog_response=response).fleet_rows)
    root = next(row for row in rows if row.agent_name == "elapsed-family")
    assert root.start_time is not None
    assert root.run_start_time is not None
    assert root.run_start_time > root.start_time
    now = _at(observed)
    _ts, family_elapsed = compute_row_runtime(root, now=now)
    _leaf_ts, current_elapsed = compute_leaf_row_runtime(
        root.followup_agents[0] if root.followup_agents else root,
        now=now,
    )
    assert family_elapsed
    assert current_elapsed
    rendered = format_agent_option(
        root, 0, is_selected=False, now=now, show_machine_chip=True
    )[0].plain
    assert " / " in rendered or family_elapsed == current_elapsed
