"""Tests for ``sase.core.graph_index_facade``."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.changespec_graph_index import (
    build_changespec_graph_index as raw_build_graph_index,
)
from sase.core import graph_index_facade, parser_facade


def test_graph_index_facade_matches_python(sample_project: Path) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = graph_index_facade.build_changespec_graph_index(specs)
    direct = raw_build_graph_index(specs)
    assert set(via_facade.name_map.keys()) == set(direct.name_map.keys())
    assert via_facade.get_children("example") == direct.get_children("example")
