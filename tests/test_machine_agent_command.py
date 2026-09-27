from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.dispatch.models import DispatchConfig, MachineRecord, ProviderSettings
import sase.ops.commands.machine as machine_cmd
from sase.ops.commands.machine import handle_machine_agent_command
from sase.dispatch.mutations import RemoteDispatchMutationError


def test_machine_agent_refuses_unknown_subcommand() -> None:
    args = SimpleNamespace(
        machine_agent_subcommand="bogus",
        alias="apollo",
        agents=["worker"],
        timeout=None,
        json=False,
        operation_request_path=None,
        operation_result_path=None,
    )
    code = handle_machine_agent_command(args)
    assert code != 0


_PIN = "sase_inst_v1_" + "a" * 64
_DISPATCH_KEY = "dispatch-a464978fdf02d2e8a650a5242ec5fcce"


def _machine() -> MachineRecord:
    return MachineRecord(
        alias="apollo",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref="fleet:apollo",
        pinned_installation_id=_PIN,
    )


def _config() -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True)
        },
        machines=(_machine(),),
        request_timeout_seconds=5.0,
    )


def _turn_row(agent_id: str, session_id: str | None) -> dict[str, Any]:
    locator: dict[str, Any] = {
        "schema_version": 6,
        "project": {
            "schema_version": 6,
            "origin": {
                "schema_version": 6,
                "installation_id": _PIN,
            },
            "project_id": "home",
        },
        "agent_id": agent_id,
    }
    if session_id is not None:
        locator["agent_session_id"] = session_id
    return {
        "logical_locator": locator,
        "agent_id": None,
        "labels": {
            "agent_label": agent_id,
            "agent_session_label": session_id,
            "project_label": "home",
        },
        "exact_locator": {"agent_id": agent_id},
        "row_revision": {"revision": 7},
        "capabilities": {"lifecycle.stop": True},
    }


class _Facade:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.seen_queries: list[dict[str, Any]] = []

    def catalog_sync(
        self, query: dict[str, Any], timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        self.seen_queries.append(dict(query))
        return {"hosts": [{"payload": {"page": {"rows": self.rows}}}]}


def _patch(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> _Facade:
    facade = _Facade(rows)
    monkeypatch.setattr(machine_cmd, "load_dispatch_config", lambda: _config())
    monkeypatch.setattr(machine_cmd, "build_federation_facade", lambda: facade)
    return facade


def test_lookup_requests_terminal_rows_for_exact_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _patch(monkeypatch, [_turn_row(f"{_DISPATCH_KEY}--0", _DISPATCH_KEY)])
    snapshots = machine_cmd._lookup_snapshots("apollo", (_DISPATCH_KEY,), None)
    assert (
        facade.seen_queries and facade.seen_queries[0].get("include_terminal") is True
    )
    assert len(snapshots) == 1
    assert snapshots[0]["exact_locator"]["agent_id"] == f"{_DISPATCH_KEY}--0"


def test_lookup_matches_settled_session_key_not_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        [
            _turn_row(f"{_DISPATCH_KEY}--0", _DISPATCH_KEY),
            _turn_row("other-agent--0", "other-agent"),
        ],
    )
    snapshots = machine_cmd._lookup_snapshots("apollo", (_DISPATCH_KEY,), None)
    assert len(snapshots) == 1
    with pytest.raises(RemoteDispatchMutationError):
        machine_cmd._lookup_snapshots("apollo", ("dispatch-a464",), None)
    with pytest.raises(RemoteDispatchMutationError):
        machine_cmd._lookup_snapshots("apollo", ("missing-agent",), None)
