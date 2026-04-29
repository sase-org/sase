"""Tests for the sase.core facade modules.

Phase 0A: each facade should call the existing Python implementation by
default and behave identically to it. ``SASE_CORE_BACKEND=rust`` should
fail clearly because no Rust implementation is registered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.changespec.models import ChangeSpec
from sase.ace.changespec.parser import parse_project_file as raw_parse_project_file
from sase.ace.query import evaluator as raw_evaluator
from sase.ace.query.parser import parse_query as raw_parse_query
from sase.ace.tui.models.changespec_graph_index import (
    build_changespec_graph_index as raw_build_graph_index,
)
from sase.core import (
    graph_index_facade,
    parser_facade,
    query_facade,
    status_facade,
)
from sase.core.backend import BACKEND_ENV_VAR, RustBackendUnavailableError
from sase.core.wire import ChangeSpecWire

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


def test_parse_project_file_rust_without_impl_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError):
        parser_facade.parse_project_file(str(sample_project))


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


def test_status_facade_rust_without_impl_raises(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    lines = sample_project.read_text().splitlines(keepends=True)
    with pytest.raises(RustBackendUnavailableError):
        status_facade.read_status_from_lines(lines, "example")


def test_query_facade_rust_without_impl_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError):
        query_facade.parse_query('"x"')
