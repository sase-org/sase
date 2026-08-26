"""Shared helpers for chop proposal-launch clan-dispatch test modules."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from sase.agent.launch_admission_store import UNITS_DIRNAME, admission_dir
from sase.core.agent_launch_wire import AgentUnitWire, LaunchUnitWire


def clan_unit(
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


def clan_unit_metadata(
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


def capturing_launch(
    calls: list[tuple[str, dict[str, str]]], agent_name: str
) -> Callable[..., list[SimpleNamespace]]:
    def _launch(prompt: str, *, extra_env: dict[str, str]) -> list[SimpleNamespace]:
        calls.append((prompt, extra_env))
        return [SimpleNamespace(pid=len(calls), agent_name=agent_name, timestamp="")]

    return _launch


def clan_marker_path(bundle_dir: Path, clan: str) -> Path:
    return admission_dir(bundle_dir) / UNITS_DIRNAME / f"clan-declared-{clan}.json"


def wait_unit(logical_id: str, *, identity: str) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=0,
        payload=AgentUnitWire(
            prompt="Body.",
            identity=identity,
            identity_explicit=True,
        ),
    )


def wait_unit_metadata(
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
