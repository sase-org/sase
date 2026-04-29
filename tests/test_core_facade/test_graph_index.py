"""Tests for ``sase.core.graph_index_facade``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models.changespec_graph_index import (
    build_changespec_graph_index as raw_build_graph_index,
)
from sase.core import graph_index_facade, parser_facade
from sase.core.backend import BACKEND_ENV_VAR


def test_graph_index_facade_matches_python(sample_project: Path) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = graph_index_facade.build_changespec_graph_index(specs)
    direct = raw_build_graph_index(specs)
    assert set(via_facade.name_map.keys()) == set(direct.name_map.keys())
    assert via_facade.get_children("example") == direct.get_children("example")


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
