"""Tests for ``sase.core.status_facade`` (Phase 4D/4E)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from sase.core import status_facade
from sase.core.backend import (
    BACKEND_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR

from tests.test_core_facade._helpers import (
    SAMPLE_PROJECT_TEXT,
    basic_plan_request,
    install_fake_status_module,
)


def test_status_facade_pure_helpers(sample_project: Path) -> None:
    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "WIP"
    rewritten = status_facade.apply_status_update(lines, "example", "Draft")
    assert "STATUS: Draft" in rewritten
    # Original lines must not be mutated.
    assert "STATUS: WIP" in "".join(lines)


def test_status_facade_line_helpers_rust_without_binding_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 4D classifies the line helpers as shipped Rust ops.

    Under ``SASE_CORE_BACKEND=rust`` the facade must raise
    :class:`RustBackendUnavailableError` instead of silently using the
    Python implementation when the ``sase_core_rs`` binding for these
    helpers is missing.
    """
    install_fake_status_module(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    lines = sample_project.read_text().splitlines(keepends=True)

    with pytest.raises(RustBackendUnavailableError, match="read_status_from_lines"):
        status_facade.read_status_from_lines(lines, "example")
    with pytest.raises(RustBackendUnavailableError, match="apply_status_update"):
        status_facade.apply_status_update(lines, "example", "Draft")


def test_status_facade_line_helpers_rust_backend_uses_rust_impl(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_CORE_BACKEND=rust`` calls the registered Rust line-helper bindings."""
    read_calls: list[tuple[list[str], str]] = []
    apply_calls: list[tuple[list[str], str, str]] = []

    def fake_read(lines: list[str], name: str) -> str:
        read_calls.append((list(lines), name))
        # Sentinel so we can verify the Rust path's output reaches callers.
        return "RUST_SENTINEL"

    def fake_apply(lines: list[str], name: str, new_status: str) -> str:
        apply_calls.append((list(lines), name, new_status))
        return "RUST_REWRITTEN"

    install_fake_status_module(
        monkeypatch,
        read_status_from_lines=fake_read,
        apply_status_update=fake_apply,
    )
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "RUST_SENTINEL"
    assert (
        status_facade.apply_status_update(lines, "example", "Draft") == "RUST_REWRITTEN"
    )
    assert read_calls == [(lines, "example")]
    assert apply_calls == [(lines, "example", "Draft")]


def test_status_facade_line_helpers_dual_run_logs_comparison(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs one record per call, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")

    lines = sample_project.read_text().splitlines(keepends=True)

    # Mirror Python output byte-for-byte so the dual-run record is a match.
    from sase.status_state_machine.field_updates import (
        apply_status_update_python,
        read_status_from_lines_python,
    )

    py_read = read_status_from_lines_python(lines, "example")
    py_apply = apply_status_update_python(lines, "example", "Draft")

    read_calls: list[str] = []
    apply_calls: list[str] = []

    def fake_read(_rust_lines: list[str], name: str) -> str | None:
        read_calls.append(name)
        return py_read

    def fake_apply(_rust_lines: list[str], name: str, _new_status: str) -> str:
        apply_calls.append(name)
        return py_apply

    install_fake_status_module(
        monkeypatch,
        read_status_from_lines=fake_read,
        apply_status_update=fake_apply,
    )

    # Default backend is python; dual-run still routes through both impls.
    assert status_facade.read_status_from_lines(lines, "example") == py_read
    assert status_facade.apply_status_update(lines, "example", "Draft") == py_apply
    assert read_calls == ["example"]
    assert apply_calls == ["example"]

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 2
    ops = {rec["operation"] for rec in records}
    assert ops == {"read_status_from_lines", "apply_status_update"}
    for rec in records:
        assert rec["match"] is True
        assert rec["error_class"] is None


def test_status_facade_line_helpers_real_extension_parity(
    sample_project: Path,
) -> None:
    """When ``sase_core_rs`` is installed, Rust and Python produce identical output.

    Skips cleanly when the optional extension is missing so pure-Python
    contributors are never blocked.
    """
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    from sase.status_state_machine.field_updates import (
        apply_status_update_python,
        read_status_from_lines_python,
    )

    lines = sample_project.read_text().splitlines(keepends=True)
    rust_module = sys.modules[RUST_EXTENSION_MODULE_NAME]
    if not hasattr(rust_module, "read_status_from_lines"):
        pytest.skip("sase_core_rs is too old (no read_status_from_lines).")
    if not hasattr(rust_module, "apply_status_update"):
        pytest.skip("sase_core_rs is too old (no apply_status_update).")

    assert rust_module.read_status_from_lines(  # type: ignore[attr-defined]
        lines, "example"
    ) == read_status_from_lines_python(lines, "example")
    assert rust_module.apply_status_update(  # type: ignore[attr-defined]
        lines, "example", "Draft"
    ) == apply_status_update_python(lines, "example", "Draft")


# === plan_status_transition (Phase 4E) =======================================


def test_plan_status_transition_python_default_backend() -> None:
    """Default backend produces the same plan as the pure Python helper."""
    from sase.core.status_wire_conversion import plan_status_transition_python

    request = basic_plan_request()
    via_facade = status_facade.plan_status_transition(request)
    direct = plan_status_transition_python(request)
    assert via_facade == direct
    assert via_facade.success is True
    assert via_facade.status_update_target == "Draft"


def test_plan_status_transition_rust_without_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4E classifies the planner as a shipped Rust op.

    Under ``SASE_CORE_BACKEND=rust`` a missing ``plan_status_transition``
    binding must raise rather than silently fall through to Python.
    """
    install_fake_status_module(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError, match="plan_status_transition"):
        status_facade.plan_status_transition(basic_plan_request())


def test_plan_status_transition_rust_backend_uses_rust_impl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_CORE_BACKEND=rust`` calls the registered ``plan_status_transition`` binding.

    The fake binding returns a sentinel plan dict (success=True with a
    distinctive status_update_target) so we can verify the Rust path's
    output reaches callers without a silent Python fallback.
    """
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
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    plan = status_facade.plan_status_transition(request)
    assert plan.status_update_target == "RUST_SENTINEL"
    assert plan.success is True
    # The request was marshaled through ``status_wire_to_json_dict`` before
    # the binding call, exposing the same primitive shape Rust expects.
    assert captured == [status_wire_to_json_dict(request)]


def test_plan_status_transition_dual_run_logs_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs a record, returns the Python plan."""
    from sase.core.status_wire import status_wire_to_json_dict
    from sase.core.status_wire_conversion import plan_status_transition_python

    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")

    request = basic_plan_request()
    py_plan = plan_status_transition_python(request)
    py_plan_dict = status_wire_to_json_dict(py_plan)

    rust_calls: list[dict] = []

    def fake_plan(payload: dict) -> dict:
        rust_calls.append(payload)
        return py_plan_dict

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.plan_status_transition = fake_plan  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)

    plan = status_facade.plan_status_transition(request)
    # The Python plan is what callers see, even under dual-run.
    assert plan == py_plan
    assert rust_calls == [status_wire_to_json_dict(request)]

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["operation"] == "plan_status_transition"
    assert rec["match"] is True
    assert rec["error_class"] is None


def test_plan_status_transition_rust_error_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Rust-side ``ValueError`` propagates instead of silently falling back."""

    def boom(_payload: dict) -> dict:
        raise ValueError("rust planner: schema mismatch")

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.plan_status_transition = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(ValueError, match="schema mismatch"):
        status_facade.plan_status_transition(basic_plan_request())


def test_plan_status_transition_real_extension_parity() -> None:
    """When ``sase_core_rs`` is installed, the Rust planner matches Python.

    Skips cleanly when the optional extension is missing so a pure-Python
    checkout is never blocked.
    """
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
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
    pipeline — proving the refactored
    :func:`transition_changespec_status_python` no longer hard-codes the
    pure decision.
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
    """A failing plan must short-circuit before any disk writes happen.

    Mirrors the Phase 4E exit criterion that "Rust rejects a transition
    before writes occur".
    """
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
