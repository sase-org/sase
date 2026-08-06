"""Unit tests for the selection engine's import-graph construction.

Path-to-module naming, import parsing, and the on-disk graph cache. The shared
synthetic repository and ``select`` helper come from
``tests._test_selection_engine_helpers``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import _touch, _write
from tests._test_selection_graph import (
    build_import_graph,
    is_test_file,
    module_name_for_path,
    parse_import_targets,
    parser_fingerprint,
)


# --------------------------------------------------------------------------
# Path and import parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/sase/foo/bar.py", "sase.foo.bar"),
        ("src/sase/__init__.py", "sase"),
        ("src/sase/foo/__init__.py", "sase.foo"),
        ("tests/x/test_y.py", "tests.x.test_y"),
        ("tests/conftest.py", "tests.conftest"),
    ],
)
def test_module_name_for_path(path: str, expected: str) -> None:
    assert module_name_for_path(path) == expected


def test_is_test_file_only_matches_collectable_tests() -> None:
    assert is_test_file("tests/test_a.py")
    assert is_test_file("tests/deep/test_a.py")
    assert not is_test_file("tests/_helper.py")
    assert not is_test_file("tests/conftest.py")
    assert not is_test_file("src/sase/test_helpers.py")


def test_parse_import_targets_names_module_and_alias() -> None:
    targets = parse_import_targets("from sase.core import paths\n", "src/sase/x.py")

    assert "sase.core" in targets
    assert "sase.core.paths" in targets


def test_parse_import_targets_resolves_relative_imports() -> None:
    targets = parse_import_targets("from ..core import paths\n", "src/sase/ace/x.py")

    assert "sase.core" in targets
    assert "sase.core.paths" in targets


def test_parse_import_targets_survives_syntax_errors() -> None:
    assert parse_import_targets("def broken(\n", "src/sase/x.py") == []


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------


def test_graph_records_reverse_edges(repo: Path) -> None:
    graph = build_import_graph(repo, cache_path=None)

    assert graph.path_for("pkg.a") == "src/pkg/a.py"
    assert "pkg.b" in graph.importers["pkg.a"]
    assert "tests._helper" in graph.importers["pkg.a"]
    # Out-of-repo imports never become edges.
    assert "pytest" not in graph.modules


def test_graph_includes_untracked_files(repo: Path) -> None:
    _write(repo, "tests/test_untracked.py", "from pkg import a\n")

    graph = build_import_graph(repo, cache_path=None)

    assert "tests/test_untracked.py" in graph.paths


def test_warm_cache_matches_cold_build(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"

    cold = build_import_graph(repo, cache_path=cache)
    warm = build_import_graph(repo, cache_path=cache)

    assert cold.stats["cache_hit"] is False
    assert warm.stats["cache_hit"] is True
    assert cold.paths == warm.paths
    assert cold.importers == warm.importers


def test_cache_reparses_changed_files(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"
    build_import_graph(repo, cache_path=cache)
    _write(repo, "src/pkg/hub.py", "from pkg import d\n")

    refreshed = build_import_graph(repo, cache_path=cache)

    assert refreshed.stats["cache_hit"] is False
    assert "pkg.hub" in refreshed.importers["pkg.d"]
    assert "pkg.hub" not in refreshed.importers.get("pkg.a", ())


def test_cache_is_discarded_when_the_parser_changes(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"
    build_import_graph(repo, cache_path=cache)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["parser"] = "stale-parser-digest"
    cache.write_text(json.dumps(payload), encoding="utf-8")

    refreshed = build_import_graph(repo, cache_path=cache)

    assert refreshed.stats["cache_hit"] is False
    assert json.loads(cache.read_text(encoding="utf-8"))["parser"] == (
        parser_fingerprint()
    )


def test_cache_is_discarded_on_schema_mismatch(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"
    build_import_graph(repo, cache_path=cache)
    cache.write_text(json.dumps({"schema": 999, "entries": {}}), encoding="utf-8")

    assert build_import_graph(repo, cache_path=cache).stats["cache_hit"] is False


def test_corrupt_cache_is_ignored(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{not json", encoding="utf-8")

    graph = build_import_graph(repo, cache_path=cache)

    assert graph.stats["cache_hit"] is False
    assert "src/pkg/a.py" in graph.paths


def test_no_cache_forces_a_cold_build(repo: Path) -> None:
    cache = repo / ".pytest_cache" / "sase-selection" / "graph.json"
    build_import_graph(repo, cache_path=cache)

    cold = build_import_graph(repo, cache_path=cache, use_cache=False)

    assert cold.stats["cache_hit"] is False


def test_cold_and_warm_selections_are_identical(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    cold = select(repo)
    warm = select(repo)

    assert cold.selected == warm.selected
    assert warm.manifest["graph"]["cache_hit"] is True
