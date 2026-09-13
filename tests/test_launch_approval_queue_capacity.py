"""LaunchApproval preserves authored %queue capacity through production dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_request import create_launch_approval_request
from sase.agent.launch_request_response import (
    dispatch_approved_launch_request,
    read_launch_request,
)
from sase.axe.run_agent_wait_markers import (
    queue_capacity_marker_fields,
    write_waiting_marker,
)
from sase.core.agent_launch_facade import agent_unit_dispatch_prompt
from sase.core.agent_launch_wire import AgentUnitWire, launch_plan_from_dict
from sase.feature_flags import override_flags
from sase.xprompt.directives import extract_prompt_directives
from tests._agent_names_extract_fixtures import run_extract
from tests._launch_admission_helpers import agent_result as _agent_result


_QUEUE_PROMPT = "%queue(capacity=100)\nDo work"
_LEGACY_CAPACITY_KEYS = frozenset({"wait_runners", "wait_runners_explicit"})


def _payload(request_path: Path) -> dict[str, Any]:
    envelope = json.loads(request_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    return payload


def _assert_canonical_capacity(mapping: dict[str, Any], *, explicit: bool) -> None:
    assert mapping["queue_capacity"] == 100
    if explicit:
        assert mapping["queue_capacity_explicit"] is True
    assert _LEGACY_CAPACITY_KEYS.isdisjoint(mapping)


def _capture_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_launch(prompt: str, extra_env: dict[str, str] | None = None) -> list[Any]:
        seen["prompt"] = prompt
        seen["extra_env"] = extra_env
        return [_agent_result(tmp_path)]

    monkeypatch.setattr("sase.agent.launcher.launch_agents_from_cwd", fake_launch)
    return seen


def test_agent_skill_typed_launch_preserves_canonical_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    with override_flags(typed_launch_units=True):
        created = create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": _QUEUE_PROMPT,
                "reason": "cover LaunchApproval capacity",
            },
            source_surface="agent_skill",
        )

    written = _payload(created.request_path)
    assert written["source_surface"] == "agent_skill"
    typed_plan = written["typed_plan"]
    unit_payload = typed_plan["units"][0]["payload"]
    _assert_canonical_capacity(unit_payload, explicit=False)
    assert unit_payload["kind"] == "agent"

    preview = created.preview_path.read_text(encoding="utf-8")
    plan = launch_plan_from_dict(typed_plan)
    agent = plan.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    assert agent.queue_capacity == 100
    rebuilt = agent_unit_dispatch_prompt(agent)
    assert "%queue(capacity=100)" in rebuilt
    assert "wait_runners" not in rebuilt
    assert "%wait(runners=" not in rebuilt
    # Queue admission is not a dependency wait; preview waits=none is not loss.
    if "waits=none" in preview:
        assert "%queue(capacity=100)" in rebuilt

    _cleaned, directives = extract_prompt_directives(rebuilt)
    assert directives.queue_capacity == 100
    extract_result = run_extract(tmp_path / "typed-meta", prompt=rebuilt)
    _assert_canonical_capacity(extract_result["meta"], explicit=True)

    marker_dir = tmp_path / "typed-marker"
    marker_dir.mkdir()
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_markers.update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: None,
    )
    write_waiting_marker(
        str(marker_dir),
        {
            "cl_name": "cl",
            "timestamp": "20260913120000",
            **queue_capacity_marker_fields(100, explicit=True),
        },
    )
    marker = json.loads((marker_dir / "waiting.json").read_text(encoding="utf-8"))
    _assert_canonical_capacity(marker, explicit=True)

    seen = _capture_launch(tmp_path, monkeypatch)
    with override_flags(typed_launch_units=True):
        result = dispatch_approved_launch_request(created.response_dir)
    assert "%queue(capacity=100)" in str(seen["prompt"])
    assert "wait_runners" not in str(seen["prompt"])
    assert result.launched_count == 1
    assert result.admission_complete is True

    bundle = read_launch_request(created.response_dir)
    _assert_canonical_capacity(
        bundle["typed_plan"]["units"][0]["payload"],
        explicit=False,
    )
    receipt = json.loads(
        (
            created.response_dir
            / "launch_admission"
            / "units"
            / f"{plan.units[0].logical_id}.json"
        ).read_text(encoding="utf-8")
    )
    _assert_canonical_capacity(receipt, explicit=True)


def test_flag_off_compat_dispatch_keeps_canonical_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    with override_flags(typed_launch_units=False):
        created = create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": _QUEUE_PROMPT,
                "reason": "cover flag-off capacity",
            },
            source_surface="agent_skill",
        )

    written = _payload(created.request_path)
    assert "typed_plan" not in written
    assert written["dispatch"]["prompt"] == _QUEUE_PROMPT
    assert "%queue(capacity=100)" in written["dispatch"]["prompt"]
    assert "wait_runners" not in written["dispatch"]["prompt"]

    seen = _capture_launch(tmp_path, monkeypatch)
    with override_flags(typed_launch_units=False):
        result = dispatch_approved_launch_request(created.response_dir)
    assert seen["prompt"] == _QUEUE_PROMPT
    assert result.launched_count == 1

    _cleaned, directives = extract_prompt_directives(str(seen["prompt"]))
    assert directives.queue_capacity == 100
    extract_result = run_extract(tmp_path / "compat-meta", prompt=str(seen["prompt"]))
    _assert_canonical_capacity(extract_result["meta"], explicit=True)
