"""Inspect surfaces for ``%auto`` E1 ``cli``: list/show/log and viewers.

``sase autonomy list``/``show``/``log`` work with and without ``--json``;
``sase agent list`` gains the ``AUTO`` column and the ``autonomy`` JSON
block; ``sase agent show`` gains the Autonomy section; ``sase gate show``
gains the ``Policy:`` line and the ``policy`` JSON key.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.agents.cli_list import _agent_to_json
from sase.autonomy.cli_log import handle_autonomy_log
from sase.autonomy.cli_profiles import (
    handle_autonomy_list,
    handle_autonomy_show,
)
from sase.core.agent_scan_wire import AgentMetaWire


def _run(handler: Any, args: SimpleNamespace, capsys: Any) -> str:
    assert handler(args) == 0
    return capsys.readouterr().out


def test_autonomy_list_json_and_pretty(capsys: Any) -> None:
    out = _run(handle_autonomy_list, SimpleNamespace(json=True), capsys)
    payload = json.loads(out)
    names = [profile["name"] for profile in payload["profiles"]]
    assert names == ["manual", "standard", "tale", "epic"]
    standard = next(
        profile for profile in payload["profiles"] if profile["name"] == "standard"
    )
    assert standard["kind"] == "default"
    assert "coverage" in payload
    assert [item["role"] for item in payload["roles"]] == [
        "epic_phase",
        "epic_land",
    ]
    assert all(
        set(item.keys()) == {"role", "profile", "source"} for item in payload["roles"]
    )

    out = _run(handle_autonomy_list, SimpleNamespace(json=False), capsys)
    assert "standard (default)" in out
    assert "Roles" in out
    assert "epic_phase" in out
    assert "epic_land" in out
    assert "Covers host checkpoints only" in out


def test_autonomy_show_json_pretty_and_unknown(capsys: Any) -> None:
    out = _run(
        handle_autonomy_show,
        SimpleNamespace(profile="tale", json=True),
        capsys,
    )
    payload = json.loads(out)
    assert payload["profile"]["name"] == "tale"
    assert payload["profile"]["layer"] == "builtin"
    assert "tale" in payload["profile"]["selections"]

    out = _run(
        handle_autonomy_show,
        SimpleNamespace(profile="epic", json=False),
        capsys,
    )
    assert "epic" in out
    assert "Covers host checkpoints only" in out

    import pytest

    with pytest.raises(SystemExit) as exited:
        handle_autonomy_show(SimpleNamespace(profile="nope", json=False))
    assert exited.value.code == 2


def _seed_log(home: Path) -> None:
    from datetime import UTC, datetime

    from sase.core.rust import require_rust_binding

    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    append = require_rust_binding("autonomy_append_decision")
    for gate_kind, outcome, agent in (
        ("plan", "auto", "seed-agent"),
        ("epic_plan", "ask", "seed-agent"),
        ("question", "auto", "other-agent"),
    ):
        append(
            str(home),
            {
                "schema_version": 1,
                "at": now,
                "agent": agent,
                "agent_session": "seed-session",
                "project": "sase",
                "gate_kind": gate_kind,
                "gate_id": f"seed-{gate_kind}",
                "creator_role": "top_level",
                "decision": {
                    "outcome": outcome,
                    "value": "approve_archive" if outcome == "auto" else None,
                    "option_ids": ["approve", "commit"] if outcome == "auto" else [],
                    "rule": "gates.plan" if outcome == "auto" else "gates.epic",
                    "reason": "seed",
                    "profile": "tale",
                    "selection": "tale",
                    "revision": 1,
                    "digest": "seed",
                    "source": "prompt",
                },
            },
        )


def test_autonomy_log_json_envelope(
    capsys: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _seed_log(home)
    monkeypatch.setattr("sase.core.paths.sase_home", lambda: home)

    out = _run(
        handle_autonomy_log,
        SimpleNamespace(agent=None, kind=None, since=None, outcome=None, json=True),
        capsys,
    )
    payload = json.loads(out)
    assert len(payload["entries"]) == 3
    assert "coverage" in payload

    out = _run(
        handle_autonomy_log,
        SimpleNamespace(agent=None, kind="plan", since="1h", outcome="auto", json=True),
        capsys,
    )
    payload = json.loads(out)
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["gate_kind"] == "plan"

    out = _run(
        handle_autonomy_log,
        SimpleNamespace(
            agent="other-agent",
            kind=None,
            since=None,
            outcome=None,
            json=True,
        ),
        capsys,
    )
    payload = json.loads(out)
    assert [entry["agent"] for entry in payload["entries"]] == ["other-agent"]


def test_agent_list_autonomy_json_and_profile() -> None:
    from sase.autonomy.record import resolve_selection
    from sase.integrations._agent_list_entry_models import AgentListEntry
    from sase.integrations._agent_list_entry_models import AgentWaitInfo

    record = resolve_selection("tale", source="prompt", surface="launch")
    entry = AgentListEntry(
        name="tale-agent",
        project="sase",
        pid=1,
        model="m",
        provider="p",
        provider_badge=None,
        workspace_num=1,
        duration="1m",
        duration_seconds=60,
        started_at=None,
        finished_at=None,
        prompt="p",
        status="RUNNING",
        status_bucket="Running",
        status_glyph="",
        approve=True,
        artifacts_dir="/tmp/x",
        wait=AgentWaitInfo(),
        autonomy=dict(record),
    )
    assert entry.autonomy_profile == "tale"
    payload = _agent_to_json(entry)
    assert payload["autonomy"]["profile"] == "tale"
    assert payload["autonomy"]["selection"] == "tale"
    assert payload["autonomy"]["source"] == "prompt"
    assert payload["autonomy"]["revision"] == 1
    assert payload["autonomy"]["class"] == "attended"
    assert payload["approve"] is True

    manual = AgentListEntry(
        name="manual-agent",
        project="sase",
        pid=1,
        model="m",
        provider="p",
        provider_badge=None,
        workspace_num=1,
        duration="1m",
        duration_seconds=60,
        started_at=None,
        finished_at=None,
        prompt="p",
        status="RUNNING",
        status_bucket="Running",
        status_glyph="",
        approve=False,
        artifacts_dir="/tmp/x",
        wait=AgentWaitInfo(),
    )
    assert manual.autonomy_profile is None
    assert _agent_to_json(manual)["autonomy"] is None


def test_agent_list_builder_carries_record() -> None:
    from sase.autonomy.record import resolve_selection
    from sase.integrations.agent_list_entries import _build_agent_list_entry
    from tests._agent_list_entries_helpers import agent, record

    autonomy = resolve_selection("epic", source="prompt", surface="launch")
    entry = _build_agent_list_entry(
        agent(name="epic-agent"),
        record=record(agent_meta=AgentMetaWire(autonomy=dict(autonomy))),
    )
    assert entry.autonomy_profile == "epic"

    legacy = _build_agent_list_entry(
        agent(name="legacy-agent"),
        record=record(agent_meta=AgentMetaWire(approve=True)),
    )
    assert legacy.autonomy is not None
    assert legacy.autonomy["profile"] == "standard"


def test_gate_show_carries_policy_block(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    from tests.autonomy_contract import harness
    from tests.plan_validation_helpers import VALID_TALE_PLAN

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    _, _, artifacts_dir = harness.launch_meta("%auto:tale\nDo the work", workdir)
    plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    from sase.notification_gates.cli_show import show_gate
    from sase.plan_gate import build_plan_approval_gate_spec

    spec = build_plan_approval_gate_spec(
        str(plan),
        "tale-policy-1",
        auto_enabled=True,
        auto_argument="tale",
    )
    gate = harness.create_plan_gate_isolated(spec, artifacts_dir, "tale-policy-1")
    request_id = gate.to_dict().get("request_id", "tale-policy-1")

    payload = show_gate("plan", request_id)
    assert payload["policy"]["outcome"] == "auto"
    assert payload["policy"]["profile"] == "tale"
    assert payload["policy"]["revision"] == 1

    from sase.notification_gates.cli_show import print_human_gate

    print_human_gate(payload)
    assert "Policy:" in capsys.readouterr().out
