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


def test_status_facade_rust_without_impl_falls_back_to_python(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    lines = sample_project.read_text().splitlines(keepends=True)
    assert status_facade.read_status_from_lines(lines, "example") == "WIP"
    rewritten = status_facade.apply_status_update(lines, "example", "Draft")
    assert "STATUS: Draft" in rewritten

    success, old_status, error, sibling_results = (
        status_facade.transition_changespec_status(
            str(sample_project),
            "example",
            "Draft",
            validate=True,
        )
    )
    assert success is True
    assert old_status == "WIP"
    assert error is None
    assert sibling_results == []
    assert (
        status_facade.read_status_from_lines(
            sample_project.read_text().splitlines(keepends=True),
            "example",
        )
        == "Draft"
    )


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
