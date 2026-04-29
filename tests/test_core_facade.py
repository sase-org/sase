"""Tests for the sase.core facade modules.

Each facade should call the existing Python implementation by default and
behave identically to it. Shipped Rust operations configured for backend
dispatch should fail clearly under ``SASE_CORE_BACKEND=rust`` when no Rust
implementation is registered; intentionally unported facade operations fall
back to Python.

When ``sase_core_rs`` is importable, ``parse_project_bytes`` routes to the Rust
binding under ``SASE_CORE_BACKEND=rust`` and dual-run logs a comparison record.
The file-path ``parse_project_file`` API stays Python-only for compatibility.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file as raw_parse_project_file
from sase.ace.changespec.parser import parse_project_file_python
from sase.ace.query import evaluator as raw_evaluator
from sase.ace.query.parser import parse_query_python as raw_parse_query
from sase.ace.tui.models.changespec_graph_index import (
    build_changespec_graph_index as raw_build_graph_index,
)
from sase.core import (
    graph_index_facade,
    parser_facade,
    query_facade,
    status_facade,
)
from sase.core.backend import (
    BACKEND_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR
from sase.core.wire import CHANGESPEC_WIRE_SCHEMA_VERSION, ChangeSpecWire
from sase.core.wire_conversion import changespec_to_wire

_SAMPLE_PROJECT_TEXT = """\
NAME: example
DESCRIPTION: Example feature.
PARENT:
PR:
STATUS: WIP

NAME: child
DESCRIPTION: Child of example.
PARENT: example
PR:
STATUS: WIP
"""


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    target = tmp_path / "myproj.gp"
    target.write_text(_SAMPLE_PROJECT_TEXT)
    return target


def test_parse_project_file_matches_python_impl(sample_project: Path) -> None:
    via_facade = parser_facade.parse_project_file(str(sample_project))
    direct = raw_parse_project_file(str(sample_project))
    assert [cs.name for cs in via_facade] == [cs.name for cs in direct]
    assert all(isinstance(cs, ChangeSpec) for cs in via_facade)


def test_parse_project_bytes_returns_wire_records(sample_project: Path) -> None:
    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    assert [w.name for w in wires] == ["example", "child"]
    # File path should be the caller-provided one even though parsing went
    # through a temp file under the hood.
    assert all(w.file_path == str(sample_project) for w in wires)


def test_parse_project_file_rust_backend_still_uses_python_parser(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    via_facade = parser_facade.parse_project_file(str(sample_project))
    direct = parse_project_file_python(str(sample_project))
    assert [cs.name for cs in via_facade] == [cs.name for cs in direct]
    assert all(isinstance(cs, ChangeSpec) for cs in via_facade)


def test_query_parse_and_evaluate_match_python(
    sample_project: Path,
) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = query_facade.parse_query('"example"')
    direct = raw_parse_query('"example"')
    # parse_query returns a dataclass tree; their .__class__ and .value
    # should match.
    assert type(via_facade) is type(direct)

    ctx = query_facade.build_query_context(specs)
    direct_ctx = raw_evaluator.build_query_context(specs)
    assert set(ctx.name_map.keys()) == set(direct_ctx.name_map.keys())

    for cs in specs:
        expected = raw_evaluator.evaluate_query(direct, cs, specs)
        assert query_facade.evaluate_query(via_facade, cs, specs) == expected
        assert query_facade.evaluate_query_with_context(via_facade, cs, ctx) == expected


def test_evaluate_query_many_matches_per_row(sample_project: Path) -> None:
    """Batch facade output equals the per-row Python path on every spec."""
    specs = parser_facade.parse_project_file(str(sample_project))
    expr = raw_parse_query('"example"')
    expected = [raw_evaluator.evaluate_query(expr, cs, specs) for cs in specs]
    assert query_facade.evaluate_query_many('"example"', specs) == expected


_ANCESTRY_PROJECT_TEXT = """\
NAME: root
DESCRIPTION: Root of the chain.
PARENT:
PR:
STATUS: Draft

NAME: middle
DESCRIPTION: Middle of the chain.
PARENT: root
PR:
STATUS: WIP

NAME: leaf
DESCRIPTION: Leaf of the chain.
PARENT: middle
PR:
STATUS: Ready

NAME: family
DESCRIPTION: Base member of the family.
PARENT:
PR:
STATUS: WIP

NAME: family__260102_010101
DESCRIPTION: Reverted retry sibling.
PARENT:
PR:
STATUS: Reverted

NAME: unrelated
DESCRIPTION: No relation.
PARENT:
PR:
STATUS: Mailed
"""


@pytest.fixture
def ancestry_project(tmp_path: Path) -> Path:
    target = tmp_path / "ancestry.gp"
    target.write_text(_ANCESTRY_PROJECT_TEXT)
    return target


@pytest.mark.parametrize(
    "query",
    [
        "ancestor:root",
        "ancestor:middle",
        "^root",
        "sibling:family",
        "sibling:family__260102_010101",
        "^root AND %w",
        "sibling:family OR ancestor:middle",
        "!ancestor:root",
    ],
)
def test_evaluate_query_many_matches_with_context_for_ancestor_and_sibling(
    ancestry_project: Path, query: str
) -> None:
    """Batch results match the per-row context path for ancestor/sibling filters."""
    specs = parser_facade.parse_project_file(str(ancestry_project))
    expr = raw_parse_query(query)
    ctx = raw_evaluator.build_query_context(specs)
    expected = [
        raw_evaluator.evaluate_query_with_context(expr, cs, ctx) for cs in specs
    ]
    assert query_facade.evaluate_query_many(query, specs) == expected


def test_graph_index_facade_matches_python(sample_project: Path) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = graph_index_facade.build_changespec_graph_index(specs)
    direct = raw_build_graph_index(specs)
    assert set(via_facade.name_map.keys()) == set(direct.name_map.keys())
    assert via_facade.get_children("example") == direct.get_children("example")


def test_status_facade_pure_helpers(sample_project: Path) -> None:
    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "WIP"
    rewritten = status_facade.apply_status_update(lines, "example", "Draft")
    assert "STATUS: Draft" in rewritten
    # Original lines must not be mutated.
    assert "STATUS: WIP" in "".join(lines)


def _install_fake_status_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    read_status_from_lines=None,
    apply_status_update=None,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing the Phase 4D line helpers."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if read_status_from_lines is not None:
        fake.read_status_from_lines = read_status_from_lines  # type: ignore[attr-defined]
    if apply_status_update is not None:
        fake.apply_status_update = apply_status_update  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def test_status_facade_line_helpers_rust_without_binding_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 4D classifies the line helpers as shipped Rust ops.

    Under ``SASE_CORE_BACKEND=rust`` the facade must raise
    :class:`RustBackendUnavailableError` instead of silently using the
    Python implementation when the ``sase_core_rs`` binding for these
    helpers is missing.
    """
    _install_fake_status_module(monkeypatch)
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

    _install_fake_status_module(
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

    _install_fake_status_module(
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


def _basic_plan_request(
    *,
    changespec_name: str = "example",
    old_status: str = "WIP",
    new_status: str = "Draft",
    validate: bool = True,
):
    """Build a minimal :class:`StatusTransitionRequestWire` for facade tests."""
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        StatusTransitionRequestWire,
    )

    return StatusTransitionRequestWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        changespec_name=changespec_name,
        old_status=old_status,
        new_status=new_status,
        validate=validate,
        parent_status=None,
    )


def test_plan_status_transition_python_default_backend() -> None:
    """Default backend produces the same plan as the pure Python helper."""
    from sase.core.status_wire_conversion import plan_status_transition_python

    request = _basic_plan_request()
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
    _install_fake_status_module(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError, match="plan_status_transition"):
        status_facade.plan_status_transition(_basic_plan_request())


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

    request = _basic_plan_request()
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

    request = _basic_plan_request()
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
        status_facade.plan_status_transition(_basic_plan_request())


def test_plan_status_transition_real_extension_parity() -> None:
    """When ``sase_core_rs`` is installed, the Rust planner matches Python.

    Skips cleanly when the optional extension is missing so a pure-Python
    checkout is never blocked.
    """
    pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    from sase.core.status_wire_conversion import plan_status_transition_python

    request = _basic_plan_request(
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
    project.write_text(_SAMPLE_PROJECT_TEXT)

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
    original_text = _SAMPLE_PROJECT_TEXT
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


def test_unported_query_facade_apis_rust_without_impl_fall_back_to_python(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    specs = parser_facade.parse_project_file(str(sample_project))
    expr = raw_parse_query('"example"')
    ctx = query_facade.build_query_context(specs)
    direct_ctx = raw_evaluator.build_query_context(specs)

    assert set(ctx.name_map) == set(direct_ctx.name_map)
    assert query_facade.evaluate_query(expr, specs[0], specs) is True
    assert query_facade.evaluate_query_with_context(expr, specs[0], ctx) is True


def test_graph_index_facade_rust_without_impl_falls_back_to_python(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = graph_index_facade.build_changespec_graph_index(specs)
    direct = raw_build_graph_index(specs)
    assert set(via_facade.name_map.keys()) == set(direct.name_map.keys())
    assert via_facade.get_children("example") == direct.get_children("example")


def test_parse_query_rust_without_impl_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_query routes to the Rust binding only when the extension is
    importable; without it, ``SASE_CORE_BACKEND=rust`` must still raise.
    """
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError):
        query_facade.parse_query('"x"')


def _python_wire_records_as_dicts(file_path: str, _data: bytes) -> list[dict]:
    """Reuse the Python parser to manufacture the dict shape Rust would emit.

    Goes through the raw Python parser (not the facade) so the helper works
    even when ``SASE_CORE_BACKEND=rust`` is active in the surrounding test.
    """
    specs = parse_project_file_python(file_path)
    wires = []
    for cs in specs:
        cs.file_path = file_path
        wires.append(changespec_to_wire(cs))
    return [
        {
            "schema_version": w.schema_version,
            "name": w.name,
            "project_basename": w.project_basename,
            "file_path": w.file_path,
            "source_span": {
                "file_path": w.source_span.file_path,
                "start_line": w.source_span.start_line,
                "end_line": w.source_span.end_line,
            },
            "status": w.status,
            "parent": w.parent,
            "cl_or_pr": w.cl_or_pr,
            "bug": w.bug,
            "description": w.description,
            "test_targets": list(w.test_targets),
            "kickstart": w.kickstart,
            "commits": [],
            "hooks": [],
            "comments": [],
            "mentors": [],
            "timestamps": [],
            "deltas": [],
        }
        for w in wires
    ]


def _install_fake_rust_module(
    monkeypatch: pytest.MonkeyPatch,
    parse_fn,  # callable[[str, bytes], list[dict]]
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` module exposing ``parse_project_bytes``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.parse_project_bytes = parse_fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def test_parse_project_bytes_rust_unavailable_keeps_python(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Rust extension + default backend = Python path, unchanged behavior."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)
    assert [w.name for w in wires] == ["example", "child"]


def test_parse_project_bytes_rust_backend_uses_rust_impl(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_CORE_BACKEND=rust`` calls the registered Rust binding.

    The fake binding records its arguments so we can assert no fallback to
    the Python path happened.
    """
    calls: list[tuple[str, bytes]] = []

    def fake_parse(path: str, data: bytes) -> list[dict]:
        calls.append((path, data))
        # The fake produces parity output by routing through Python so we
        # exercise the dict -> ChangeSpecWire rehydration code path.
        return _python_wire_records_as_dicts(path, data)

    _install_fake_rust_module(monkeypatch, fake_parse)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)

    assert len(calls) == 1
    assert calls[0][0] == str(sample_project)
    assert calls[0][1] == raw_bytes
    assert [w.name for w in wires] == ["example", "child"]
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    # The schema version round-trips through the dict adapter unchanged.
    assert all(w.schema_version == CHANGESPEC_WIRE_SCHEMA_VERSION for w in wires)


def test_parse_project_bytes_rust_backend_missing_binding_raises_cleanly(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError, match="parse_project_bytes"):
        parser_facade.parse_project_bytes(
            str(sample_project),
            sample_project.read_bytes(),
        )


def test_parse_project_bytes_dual_run_logs_comparison(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs one record, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")

    rust_calls: list[tuple[str, bytes]] = []

    def fake_parse(path: str, data: bytes) -> list[dict]:
        rust_calls.append((path, data))
        return _python_wire_records_as_dicts(path, data)

    _install_fake_rust_module(monkeypatch, fake_parse)

    raw_bytes = sample_project.read_bytes()
    wires = parser_facade.parse_project_bytes(str(sample_project), raw_bytes)

    # Python output is what the caller sees, even under dual-run.
    assert all(isinstance(w, ChangeSpecWire) for w in wires)
    assert [w.name for w in wires] == ["example", "child"]
    assert len(rust_calls) == 1

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["operation"] == "parse_project_bytes"
    assert rec["match"] is True
    assert rec["error_class"] is None
    assert rec["source_path"] == str(sample_project)


def test_parse_project_bytes_rust_error_surfaces(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Rust-side ``ValueError`` propagates instead of silently falling back."""

    def boom(_path: str, _data: bytes) -> list[dict]:
        raise ValueError("encoding: invalid UTF-8 (bad.gp)")

    _install_fake_rust_module(monkeypatch, boom)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    raw_bytes = sample_project.read_bytes()
    with pytest.raises(ValueError, match="encoding"):
        parser_facade.parse_project_bytes(str(sample_project), raw_bytes)


def _install_fake_query_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parse_query=None,
    evaluate_query_many=None,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing the Phase 2D query bindings."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    if parse_query is not None:
        fake.parse_query = parse_query  # type: ignore[attr-defined]
    if evaluate_query_many is not None:
        fake.evaluate_query_many = evaluate_query_many  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def test_parse_query_rust_backend_uses_rust_impl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_CORE_BACKEND=rust`` routes parse_query through the binding."""
    calls: list[str] = []

    def fake_parse_query(query: str) -> dict:
        calls.append(query)
        # Mirror the Python wire shape sase_core_rs emits for a single string.
        return {
            "kind": "string",
            "value": "x",
            "case_sensitive": False,
            "is_error_suffix": False,
            "is_running_agent": False,
            "is_running_process": False,
            "property_key": None,
            "operands": [],
        }

    _install_fake_query_module(monkeypatch, parse_query=fake_parse_query)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    expr = query_facade.parse_query('"x"')
    assert calls == ['"x"']
    # The dict is rehydrated into the Python AST via the wire converters,
    # so the caller sees the same shape as the Python path.
    assert type(expr) is type(raw_parse_query('"x"'))


def test_parse_query_rust_backend_missing_binding_raises_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_query_module(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError, match="parse_query"):
        query_facade.parse_query('"x"')


def test_evaluate_query_many_rust_backend_uses_rust_impl(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch facade routes through the Rust binding under ``rust``."""
    specs = parser_facade.parse_project_file(str(sample_project))
    # Sentinel result so we can verify the Rust path's output reaches callers
    # without colliding with the Python evaluator's natural output.
    sentinel = [False, True]

    calls: list[tuple[str, int]] = []

    def fake_evaluate(query: str, spec_dicts: list[dict]) -> list[bool]:
        calls.append((query, len(spec_dicts)))
        return list(sentinel)

    _install_fake_query_module(monkeypatch, evaluate_query_many=fake_evaluate)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    result = query_facade.evaluate_query_many('"example"', specs)
    assert result == sentinel
    assert calls == [('"example"', len(specs))]


def test_evaluate_query_many_rust_backend_forwards_null_mentor_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "myproj.gp"
    project.write_text(
        """\
NAME: missing_mentor_timestamp
DESCRIPTION:
PARENT:
PR:
STATUS: WIP
MENTORS:
  (1) profileA[1/1]
      | profileA:mentor1 - RUNNING - (@: mentor_mentor1-123-260101_130000)
"""
    )
    specs = parser_facade.parse_project_file(str(project))

    def fake_evaluate(query: str, spec_dicts: list[dict]) -> list[bool]:
        assert query == '"missing_mentor_timestamp"'
        status_line = spec_dicts[0]["mentors"][0]["status_lines"][0]
        assert status_line["timestamp"] is None
        return [True]

    _install_fake_query_module(monkeypatch, evaluate_query_many=fake_evaluate)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    result = query_facade.evaluate_query_many('"missing_mentor_timestamp"', specs)
    assert result == [True]


def test_evaluate_query_many_rust_backend_missing_binding_raises_cleanly(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    _install_fake_query_module(monkeypatch, parse_query=lambda _query: {})
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError, match="evaluate_query_many"):
        query_facade.evaluate_query_many('"example"', specs)


def test_evaluate_query_many_dual_run_logs_comparison(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs one record, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")

    specs = parser_facade.parse_project_file(str(sample_project))
    rust_calls: list[int] = []

    # Compute the Python result up front so the fake can mirror it byte-for-byte
    # and the dual-run record is a "match".
    py_expected = query_facade._evaluate_query_many_python('"example"', specs)

    def fake_evaluate(query: str, spec_dicts: list[dict]) -> list[bool]:
        rust_calls.append(len(spec_dicts))
        assert query == '"example"'
        return list(py_expected)

    _install_fake_query_module(monkeypatch, evaluate_query_many=fake_evaluate)

    result = query_facade.evaluate_query_many('"example"', specs)
    assert result == py_expected
    assert rust_calls == [len(specs)]

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["operation"] == "evaluate_query_many"
    assert rec["match"] is True
    assert rec["error_class"] is None
