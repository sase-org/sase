"""Tests for the agent cleanup facade and Rust binding parity."""

from __future__ import annotations

import types
from typing import Any

import pytest

from sase.core.agent_cleanup_facade import (
    _plan_agent_cleanup_python,
    agents_to_cleanup_targets,
    plan_agent_cleanup,
)
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    KILL_KIND_RUNNING,
    agent_cleanup_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from tests._rust_extension_module_helpers import (
    patch_rust_extension,
)

from tests.test_core_facade._agent_cleanup_helpers import (
    _SCENARIOS,
    _scenario_clan_sequential_family_dismiss,
    _scenario_explicit_clan_sequential_family_dismiss,
    _scenario_marked_set,
)


def _require_schema_4_cleanup_binding() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not all(
        hasattr(rust_module, name)
        for name in ("plan_agent_cleanup", "agent_cleanup_wire_schema_version")
    ):
        pytest.skip("sase_core_rs is too old (no plan_agent_cleanup).")
    assert int(rust_module.agent_cleanup_wire_schema_version()) == (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION
    )
    assert AGENT_CLEANUP_WIRE_SCHEMA_VERSION == 4


def _fail_if_python_cleanup_planner_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def _python_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "schema-4 rust cleanup path fell back to the Python planner"
        )

    monkeypatch.setattr(
        "sase.core.agent_cleanup_facade.plan_agent_cleanup_python",
        _python_must_not_run,
    )


def test_plan_agent_cleanup_uses_rust_binding_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents, request = _scenario_marked_set()
    targets = agents_to_cleanup_targets(agents)
    captured: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []

    def fake_plan(
        target_payload: list[dict[str, Any]], request_payload: dict[str, Any]
    ) -> dict[str, Any]:
        captured.append((target_payload, request_payload))
        plan = _plan_agent_cleanup_python(target_payload, request_payload)
        payload = agent_cleanup_wire_to_json_dict(plan)
        payload["kill_items"][0]["kind"] = KILL_KIND_RUNNING
        return payload

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.agent_cleanup_wire_schema_version = (  # type: ignore[attr-defined]
        lambda: AGENT_CLEANUP_WIRE_SCHEMA_VERSION
    )
    fake.plan_agent_cleanup = fake_plan  # type: ignore[attr-defined]
    patch_rust_extension(monkeypatch, fake)

    plan = plan_agent_cleanup(targets, request)

    assert [(item.identity.cl_name, item.kind) for item in plan.kill_items] == [
        ("running", KILL_KIND_RUNNING)
    ]
    assert captured == [
        (
            agent_cleanup_wire_to_json_dict(targets),
            agent_cleanup_wire_to_json_dict(request),
        )
    ]


def test_plan_agent_cleanup_falls_back_when_binding_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    patch_rust_extension(monkeypatch, fake)
    agents, request = _scenario_marked_set()

    plan = plan_agent_cleanup(agents_to_cleanup_targets(agents), request)

    assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
    assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]


def test_plan_agent_cleanup_falls_back_when_binding_schema_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.agent_cleanup_wire_schema_version = lambda: 2  # type: ignore[attr-defined]
    fake.plan_agent_cleanup = lambda *_: pytest.fail(  # type: ignore[attr-defined]
        "stale planner must not receive a tribe-shaped payload"
    )
    patch_rust_extension(monkeypatch, fake)
    agents, request = _scenario_marked_set()

    plan = plan_agent_cleanup(agents_to_cleanup_targets(agents), request)

    assert [item.identity.cl_name for item in plan.kill_items] == ["running"]
    assert [item.identity.cl_name for item in plan.dismiss_items] == ["done"]


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_rust_cleanup_planner_matches_python_reference(
    scenario: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_schema_4_cleanup_binding()
    _fail_if_python_cleanup_planner_runs(monkeypatch)

    agents, request = scenario()
    targets = agents_to_cleanup_targets(agents)

    assert plan_agent_cleanup(targets, request) == _plan_agent_cleanup_python(
        targets,
        request,
    )


@pytest.mark.parametrize(
    "scenario",
    (
        _scenario_clan_sequential_family_dismiss,
        _scenario_explicit_clan_sequential_family_dismiss,
    ),
)
def test_rust_and_python_planners_agree_on_clan_sequential_family(
    scenario: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_schema_4_cleanup_binding()
    _fail_if_python_cleanup_planner_runs(monkeypatch)

    agents, request = scenario()
    targets = agents_to_cleanup_targets(agents)

    rust_plan = plan_agent_cleanup(targets, request)
    python_plan = _plan_agent_cleanup_python(targets, request)
    assert rust_plan == python_plan
    assert [item.identity.cl_name for item in rust_plan.dismiss_items] == [
        "sase-ps.plan",
        "sase-ps.plan--1",
        "sase-ps.plan--mon",
    ]
    assert [
        item.cl_name for item in rust_plan.side_effects.dismissed_index_additions
    ] == [
        "sase-ps.plan",
        "sase-ps.plan--1",
        "sase-ps.plan--mon",
    ]
