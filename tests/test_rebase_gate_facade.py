from __future__ import annotations

from typing import Any

import pytest

from sase.core import rebase_gate


def test_facade_forwards_typed_requests_to_registered_rust_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []
    context: rebase_gate.ContextWire = {
        "schema_version": 1,
        "repository_root": "/repo",
        "inputs": [],
        "current_head": "a" * 40,
        "current_tree": "b" * 40,
        "changed_paths": [],
    }
    decision: rebase_gate.DecisionWire = {
        "schema_version": 1,
        "verdict": "skip",
        "reason": "disabled",
        "findings": [],
    }

    def require(name: str) -> Any:
        if name == "rebase_gate_wire_schema_version":
            return lambda: 1

        def invoke(request: dict[str, Any]) -> Any:
            calls.append((name, request))
            if name == "build_rebase_gate_context":
                return context
            if name == "merge_rebase_gate_contexts":
                return context
            if name == "update_rebase_gate_context":
                return context
            if name == "classify_rebase_gate_result":
                return decision
            raise AssertionError(name)

        return invoke

    monkeypatch.setattr(rebase_gate, "require_rust_binding", require)
    facts: rebase_gate.RebaseFactsWire = {
        "schema_version": 1,
        "repository_root": "/repo",
        "old_head": "1" * 40,
        "upstream_tip": "2" * 40,
        "merge_base": "3" * 40,
        "rebase_outcome": "applied",
        "current_head": "a" * 40,
        "current_tree": "b" * 40,
    }

    assert rebase_gate.build_rebase_gate_context(facts) == context
    assert rebase_gate.merge_rebase_gate_contexts(context, None) == context
    update: rebase_gate.ContextUpdateWire = {
        "schema_version": 1,
        "repository_root": "/repo",
        "current_head": "a" * 40,
        "current_tree": "b" * 40,
    }
    assert rebase_gate.update_rebase_gate_context(context, update) == context
    assert (
        rebase_gate.classify_rebase_gate_result(
            context,
            {"hook_command": "", "timeout_seconds": 10.0},
            {},
            None,
        )
        == decision
    )

    assert [name for name, _ in calls] == [
        "build_rebase_gate_context",
        "merge_rebase_gate_contexts",
        "update_rebase_gate_context",
        "classify_rebase_gate_result",
    ]
    assert calls[1][1] == {
        "schema_version": 1,
        "existing": context,
        "incoming": None,
    }


def test_facade_rejects_stale_binding_and_malformed_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rebase_gate,
        "require_rust_binding",
        lambda name: (lambda: 2) if name.endswith("schema_version") else lambda _: None,
    )
    with pytest.raises(AttributeError, match="wire is stale"):
        rebase_gate.build_rebase_gate_context({})  # type: ignore[arg-type]

    monkeypatch.setattr(
        rebase_gate,
        "require_rust_binding",
        lambda name: (
            (lambda: 1) if name.endswith("schema_version") else lambda _: "bad"
        ),
    )
    with pytest.raises(TypeError, match="non-dict rebase gate context"):
        rebase_gate.build_rebase_gate_context({})  # type: ignore[arg-type]
