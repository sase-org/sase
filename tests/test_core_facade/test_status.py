"""Tests for ``sase.core.status_facade`` (Phase 8E direct-Rust wiring)."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

from sase.core import status_facade
from sase.core.backend import RUST_EXTENSION_MODULE_NAME

from tests.test_core_facade._helpers import (
    SAMPLE_PROJECT_TEXT,
    basic_plan_request,
    install_fake_status_module,
)


def _force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make :func:`sase.core.backend.load_rust_extension` see no module."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail)


def test_status_facade_pure_helpers(sample_project: Path) -> None:
    """The pure line helpers route through the real Rust binding by default."""
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "WIP"
    rewritten = status_facade.apply_status_update(lines, "example", "Draft")
    assert "STATUS: Draft" in rewritten
    # Original lines must not be mutated.
    assert "STATUS: WIP" in "".join(lines)


def test_status_facade_line_helpers_missing_extension_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``sase_core_rs`` is missing the strict loader raises ``ImportError``."""
    _force_no_rust_extension(monkeypatch)
    lines = sample_project.read_text().splitlines(keepends=True)

    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        status_facade.read_status_from_lines(lines, "example")
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        status_facade.apply_status_update(lines, "example", "Draft")


def test_status_facade_line_helpers_missing_binding_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel without the binding raises ``AttributeError`` with the op name."""
    install_fake_status_module(monkeypatch)
    lines = sample_project.read_text().splitlines(keepends=True)

    with pytest.raises(AttributeError, match="read_status_from_lines"):
        status_facade.read_status_from_lines(lines, "example")
    with pytest.raises(AttributeError, match="apply_status_update"):
        status_facade.apply_status_update(lines, "example", "Draft")


def test_status_facade_line_helpers_call_rust_binding(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The facade calls the registered ``sase_core_rs`` line-helper bindings."""
    read_calls: list[tuple[list[str], str]] = []
    apply_calls: list[tuple[list[str], str, str]] = []

    def fake_read(lines: list[str], name: str) -> str:
        read_calls.append((list(lines), name))
        return "RUST_SENTINEL"

    def fake_apply(lines: list[str], name: str, new_status: str) -> str:
        apply_calls.append((list(lines), name, new_status))
        return "RUST_REWRITTEN"

    install_fake_status_module(
        monkeypatch,
        read_status_from_lines=fake_read,
        apply_status_update=fake_apply,
    )

    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "RUST_SENTINEL"
    assert (
        status_facade.apply_status_update(lines, "example", "Draft") == "RUST_REWRITTEN"
    )
    assert read_calls == [(lines, "example")]
    assert apply_calls == [(lines, "example", "Draft")]


def test_status_facade_line_helpers_real_extension_parity(
    sample_project: Path,
) -> None:
    """When ``sase_core_rs`` is installed, Rust matches the Python golden helpers.

    The Python helpers in :mod:`sase.status_state_machine.field_updates`
    are the host-logic golden references; this test pins their
    byte-for-byte parity with the direct Rust binding.
    """
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    from sase.status_state_machine.field_updates import (
        apply_status_update_python,
        read_status_from_lines_python,
    )

    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(
        lines, "example"
    ) == read_status_from_lines_python(lines, "example")
    assert status_facade.apply_status_update(
        lines, "example", "Draft"
    ) == apply_status_update_python(lines, "example", "Draft")


# === plan_status_transition (Phase 4E) =======================================


def test_plan_status_transition_against_python_golden() -> None:
    """The facade output matches :func:`plan_status_transition_python` byte-for-byte."""
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    from sase.core.status_wire_conversion import plan_status_transition_python

    request = basic_plan_request()
    via_facade = status_facade.plan_status_transition(request)
    direct = plan_status_transition_python(request)
    assert via_facade == direct
    assert via_facade.success is True
    assert via_facade.status_update_target == "Draft"


def test_plan_status_transition_missing_extension_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``sase_core_rs`` is missing the planner facade raises ``ImportError``."""
    _force_no_rust_extension(monkeypatch)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        status_facade.plan_status_transition(basic_plan_request())


def test_plan_status_transition_missing_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel without the binding raises ``AttributeError`` with the op name."""
    install_fake_status_module(monkeypatch)
    with pytest.raises(AttributeError, match="plan_status_transition"):
        status_facade.plan_status_transition(basic_plan_request())


def test_plan_status_transition_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The facade marshals the request and rehydrates the typed plan."""
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        SUFFIX_ACTION_NONE,
        status_wire_to_json_dict,
    )

    request = basic_plan_request()
    captured: list[dict] = []

    def fake_plan(payload: dict) -> dict:
        captured.append(payload)
        return {
            "schema_version": STATUS_WIRE_SCHEMA_VERSION,
            "success": True,
            "old_status": payload["old_status"],
            "error": None,
            "status_update_target": "RUST_SENTINEL",
            "suffix_action": SUFFIX_ACTION_NONE,
            "suffixed_name": None,
            "base_name": None,
            "mentor_draft_action": "none",
            "archive_action": "none",
            "timestamp_event": None,
            "timestamp_target_name": None,
            "revert_siblings": False,
        }

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.plan_status_transition = fake_plan  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    plan = status_facade.plan_status_transition(request)
    assert plan.status_update_target == "RUST_SENTINEL"
    assert plan.success is True
    # The request was marshaled through ``status_wire_to_json_dict`` before
    # the binding call, exposing the same primitive shape Rust expects.
    assert captured == [status_wire_to_json_dict(request)]


def test_plan_status_transition_rust_error_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Rust-side ``ValueError`` propagates instead of being swallowed."""

    def boom(_payload: dict) -> dict:
        raise ValueError("rust planner: schema mismatch")

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.plan_status_transition = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    with pytest.raises(ValueError, match="schema mismatch"):
        status_facade.plan_status_transition(basic_plan_request())


def test_plan_status_transition_real_extension_parity() -> None:
    """When ``sase_core_rs`` is installed, the Rust planner matches Python.

    Skips cleanly when the optional extension is missing so a pure-Python
    checkout is never blocked.
    """
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "plan_status_transition"):
        pytest.skip("sase_core_rs is too old (no plan_status_transition).")

    from sase.core.status_wire_conversion import plan_status_transition_python

    request = basic_plan_request(
        changespec_name="example",
        old_status="WIP",
        new_status="Draft",
    )
    via_facade = status_facade.plan_status_transition(request)
    direct = plan_status_transition_python(request)
    assert via_facade == direct


def test_transition_changespec_status_uses_planner_facade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: the in-lock decision step routes through the planner facade.

    A fake plan returned by the facade must be honored by the side-effect
    pipeline — proving :func:`transition_changespec_status_python` no
    longer hard-codes the pure decision.
    """
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        SUFFIX_ACTION_NONE,
        StatusTransitionPlanWire,
    )
    from sase.status_state_machine import transition_changespec_status

    project = tmp_path / "myproj.gp"
    project.write_text(SAMPLE_PROJECT_TEXT)

    captured_requests: list = []

    def fake_plan(request):  # type: ignore[no-untyped-def]
        captured_requests.append(request)
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=True,
            old_status=request.old_status,
            error=None,
            status_update_target=request.new_status,
            suffix_action=SUFFIX_ACTION_NONE,
            suffixed_name=None,
            base_name=None,
            mentor_draft_action="none",
            archive_action="none",
            timestamp_event=None,
            timestamp_target_name=None,
            revert_siblings=False,
        )

    monkeypatch.setattr("sase.core.status_facade.plan_status_transition", fake_plan)
    monkeypatch.setattr(
        "sase.status_state_machine.transitions.handle_suffix_strip",
        lambda *args, **kwargs: [],
    )

    success, old_status, error, _ = transition_changespec_status(
        str(project), "example", "Draft", validate=True
    )

    assert success is True
    assert old_status == "WIP"
    assert error is None
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.changespec_name == "example"
    assert request.old_status == "WIP"
    assert request.new_status == "Draft"

    # The STATUS line was rewritten using the plan's update target.
    assert "STATUS: Draft" in project.read_text()


def test_transition_changespec_status_planner_failure_skips_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing plan must short-circuit before any disk writes happen."""
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        StatusTransitionPlanWire,
    )
    from sase.status_state_machine import transition_changespec_status

    project = tmp_path / "myproj.gp"
    original_text = SAMPLE_PROJECT_TEXT
    project.write_text(original_text)

    def rejecting_plan(request):  # type: ignore[no-untyped-def]
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=False,
            old_status=request.old_status,
            error="rust says no",
        )

    monkeypatch.setattr(
        "sase.core.status_facade.plan_status_transition", rejecting_plan
    )

    write_calls: list = []

    def fail_if_called(*args, **kwargs):  # type: ignore[no-untyped-def]
        write_calls.append((args, kwargs))
        raise AssertionError("write_changespec_atomic must not run on plan failure")

    monkeypatch.setattr("sase.ace.changespec.write_changespec_atomic", fail_if_called)

    success, old_status, error, sibling_results = transition_changespec_status(
        str(project), "example", "Draft", validate=True
    )

    assert success is False
    assert old_status == "WIP"
    assert error == "rust says no"
    assert sibling_results == []
    assert write_calls == []
    # File untouched.
    assert project.read_text() == original_text
