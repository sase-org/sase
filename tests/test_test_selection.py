"""Unit tests for the diff-scoped test selection engine.

Every assertion here runs against a synthetic repository built under
``tmp_path``. Asserting against the real repository's import graph would make
these tests rot on every commit that adds or removes an import.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._test_selection import (
    FULL_SUITE,
    Selection,
    SelectionOptions,
    select_tests,
)
from tests._test_selection_graph import (
    SelectionError,
    build_import_graph,
    is_test_file,
    module_name_for_path,
    parse_import_targets,
    parser_fingerprint,
)
from tests._test_selection_report import summary_line
from tests._test_selection_rules import (
    CONTRACT_MANIFEST_PATH,
    RULE_BASE_UNRESOLVED,
    RULE_CONTRACT_SET_ALWAYS,
    RULE_CONTRACT_SET_ONLY,
    RULE_CORE_IDENTITY_CHANGED,
    RULE_DIRECTORY_CONFTEST,
    RULE_JUSTFILE,
    RULE_PACKAGING_CONFIG,
    RULE_RATIO_EXCEEDED,
    RULE_RENAME_OR_DELETE,
    RULE_ROOT_CONFTEST,
    RULE_SELECTION_TOOLING,
    RULE_SRC_DATA_ASSET,
)


from tests._test_selection_fixtures import (
    RING_SIZE,
    _git,
    _touch,
    _write,
    build_fixture_repo,
    install_fresh_baseline,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed synthetic repository with a known import shape."""
    root = build_fixture_repo(tmp_path)
    install_fresh_baseline(root)
    return root


def _select(
    root: Path,
    *,
    depth: int = 2,
    max_ratio: float = 1.0,
    base_ref: str = "HEAD",
    **kwargs: object,
) -> Selection:
    """Select against a *fresh* baseline, so the closure walks the given depth.

    Without one, ``no-baseline-depth-boost`` would buy every selection here an
    extra hop and these assertions would be measuring the compensation rather
    than the closure. The compensation has its own tests, in
    ``tests/test_test_selection_contexts.py``.
    """
    options = SelectionOptions(base_ref=base_ref, depth=depth, max_ratio=max_ratio)
    kwargs.setdefault("contexts_store", root.parent / "selection-store" / "project")
    return select_tests(root, options, **kwargs)  # type: ignore[arg-type]


def _commit_contract_manifest(root: Path, *entries: str) -> None:
    """Commit a contract manifest so it is not itself part of the change set."""
    _write(root, CONTRACT_MANIFEST_PATH, "".join(f"{entry}\n" for entry in entries))
    _git(root, "add", CONTRACT_MANIFEST_PATH)
    _git(root, "commit", "-q", "-m", "contract manifest")


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

    cold = _select(repo)
    warm = _select(repo)

    assert cold.selected == warm.selected
    assert warm.manifest["graph"]["cache_hit"] is True


# --------------------------------------------------------------------------
# Depth-bounded closure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        (0, {"tests/test_a.py"}),
        (1, {"tests/test_a.py", "tests/test_b.py", "tests/test_via_helper.py"}),
        (
            2,
            {
                "tests/test_a.py",
                "tests/test_b.py",
                "tests/test_c.py",
                "tests/test_cycle.py",
                "tests/test_via_helper.py",
            },
        ),
    ],
)
def test_depth_bounding_stops_where_it_should(
    repo: Path, depth: int, expected: set[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, depth=depth)

    assert set(selection.selected) == expected
    assert "tests/test_d.py" not in selection.selected


def test_closure_traverses_test_support_modules(repo: Path) -> None:
    """A test importing no production module is only reachable via helpers."""
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, depth=1)

    assert "tests/test_via_helper.py" in selection.selected
    assert selection.explanations["tests/test_via_helper.py"][0] == "pkg.a"


def test_cycles_terminate_and_do_not_explode_the_selection(repo: Path) -> None:
    _touch(repo, "src/pkg/ring0.py")

    selection = _select(repo, depth=2)

    ring_tests = {path for path in selection.selected if "test_ring" in path}
    assert ring_tests == {
        "tests/test_ring0.py",
        f"tests/test_ring{RING_SIZE - 1}.py",
        f"tests/test_ring{RING_SIZE - 2}.py",
    }
    assert len(ring_tests) < RING_SIZE


def test_mutual_cycle_terminates(repo: Path) -> None:
    _touch(repo, "src/pkg/cycle_x.py")

    selection = _select(repo, depth=3)

    assert "tests/test_cycle.py" in selection.selected


def test_changed_test_files_are_always_selected(repo: Path) -> None:
    _touch(repo, "tests/test_d.py")

    selection = _select(repo)

    assert "tests/test_d.py" in selection.selected


def test_untracked_new_test_file_is_selected(repo: Path) -> None:
    _write(repo, "tests/test_untracked.py", "from pkg import d\n")

    selection = _select(repo)

    assert "tests/test_untracked.py" in selection.selected


def test_deleted_test_file_is_not_selected(repo: Path) -> None:
    """A deleted path must not reach pytest, which exits 4 on a missing file."""
    _git(repo, "rm", "-q", "tests/test_d.py")

    selection = _select(repo)

    assert "tests/test_d.py" not in selection.selected
    assert RULE_RENAME_OR_DELETE in selection.rules


def test_docs_only_change_selects_nothing(repo: Path) -> None:
    _touch(repo, "docs/development.md")

    selection = _select(repo)

    assert selection.selected == ()
    assert RULE_CONTRACT_SET_ONLY in selection.rules
    assert not selection.escalated


# --------------------------------------------------------------------------
# Visual exclusion
# --------------------------------------------------------------------------


def test_visual_tests_are_never_selected(repo: Path) -> None:
    _touch(repo, "tests/_helper.py")

    selection = _select(repo)

    assert "tests/ace/tui/visual/test_visual.py" not in selection.selected
    assert not any(
        path.startswith("tests/ace/tui/visual/") for path in selection.selected
    )


def test_changed_visual_test_is_still_excluded(repo: Path) -> None:
    _touch(repo, "tests/ace/tui/visual/test_visual.py")

    selection = _select(repo)

    assert selection.selected == ()


def test_visual_tests_are_outside_the_universe(repo: Path) -> None:
    selection = _select(repo)

    assert selection.universe_count == selection.manifest["universe_count"]
    assert "tests/ace/tui/visual/test_visual.py" not in selection.selected
    assert selection.universe_count == 8 + RING_SIZE


# --------------------------------------------------------------------------
# Broadening rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("tests/conftest.py", RULE_ROOT_CONFTEST),
        ("tests/_suite_gate.py", RULE_ROOT_CONFTEST),
        ("pyproject.toml", RULE_PACKAGING_CONFIG),
        ("uv.lock", RULE_PACKAGING_CONFIG),
        ("Justfile", RULE_JUSTFILE),
        ("src/pkg/config.yml", RULE_SRC_DATA_ASSET),
        ("tools/run_pytest", RULE_SELECTION_TOOLING),
    ],
)
def test_full_suite_rules_fire_and_escalate(repo: Path, path: str, rule: str) -> None:
    _touch(repo, path)

    selection = _select(repo)

    assert rule in selection.rules
    assert selection.escalated
    assert selection.selected == ()
    assert selection.paths_output == FULL_SUITE


def test_directory_conftest_selects_its_whole_directory(repo: Path) -> None:
    _touch(repo, "tests/sub/conftest.py")

    selection = _select(repo)

    assert RULE_DIRECTORY_CONFTEST in selection.rules
    assert set(selection.selected) == {
        "tests/sub/test_sub.py",
        "tests/sub/test_sub_other.py",
    }
    assert not selection.escalated


def test_unresolvable_base_escalates(repo: Path) -> None:
    selection = _select(repo, base_ref="origin/nonexistent")

    assert RULE_BASE_UNRESOLVED in selection.rules
    assert selection.escalated
    assert selection.manifest["base"]["merge_base"] is None


def test_changed_core_identity_escalates(repo: Path) -> None:
    selection = _select(
        repo,
        environment="new-digest",
        previous_manifest={"baseline": {"environment": "old-digest"}},
    )

    assert RULE_CORE_IDENTITY_CHANGED in selection.rules
    assert selection.escalated


def test_unchanged_core_identity_does_not_escalate(repo: Path) -> None:
    selection = _select(
        repo,
        environment="same-digest",
        previous_manifest={"baseline": {"environment": "same-digest"}},
    )

    assert RULE_CORE_IDENTITY_CHANGED not in selection.rules
    assert not selection.escalated


def test_missing_previous_environment_is_not_a_change(repo: Path) -> None:
    selection = _select(repo, environment="digest", previous_manifest={})

    assert RULE_CORE_IDENTITY_CHANGED not in selection.rules


def test_deletion_bumps_effective_depth_by_one(repo: Path) -> None:
    _git(repo, "rm", "-q", "src/pkg/hub.py")
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, depth=1)

    assert RULE_RENAME_OR_DELETE in selection.rules
    # Depth 1 alone stops before test_c; the rename/delete bump buys it back.
    assert "tests/test_c.py" in selection.selected


def test_rename_records_the_rule(repo: Path) -> None:
    _git(repo, "mv", "src/pkg/d.py", "src/pkg/renamed.py")

    selection = _select(repo)

    assert RULE_RENAME_OR_DELETE in selection.rules


# --------------------------------------------------------------------------
# Contract set
# --------------------------------------------------------------------------


def test_contract_set_is_always_added(repo: Path) -> None:
    _commit_contract_manifest(repo, "tests/test_d.py")
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo)

    assert "tests/test_d.py" in selection.selected
    assert RULE_CONTRACT_SET_ALWAYS in selection.rules


def test_contract_set_applies_to_docs_only_changes(repo: Path) -> None:
    _commit_contract_manifest(repo, "tests/test_d.py")
    _touch(repo, "docs/development.md")

    selection = _select(repo)

    assert selection.selected == ("tests/test_d.py",)


def test_absent_contract_manifest_is_valid(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo)

    assert RULE_CONTRACT_SET_ALWAYS not in selection.rules
    assert selection.selected


def test_contract_manifest_ignores_comments_and_blanks(repo: Path) -> None:
    _commit_contract_manifest(repo, "# generated", "", "tests/test_d.py")
    _touch(repo, "docs/development.md")

    selection = _select(repo)

    assert selection.selected == ("tests/test_d.py",)


def test_changing_the_contract_manifest_escalates(repo: Path) -> None:
    _write(repo, CONTRACT_MANIFEST_PATH, "tests/test_d.py\n")
    _git(repo, "add", CONTRACT_MANIFEST_PATH)

    selection = _select(repo)

    assert RULE_SELECTION_TOOLING in selection.rules
    assert selection.escalated


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------


def test_ratio_escalation_trips_at_the_threshold(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, max_ratio=0.05)

    assert RULE_RATIO_EXCEEDED in selection.rules
    assert selection.escalated
    assert selection.selected == ()


def test_ratio_escalation_does_not_trip_below_the_threshold(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = _select(repo, max_ratio=0.9)

    assert RULE_RATIO_EXCEEDED not in selection.rules
    assert not selection.escalated


# --------------------------------------------------------------------------
# Manifest and reporting
# --------------------------------------------------------------------------


def test_manifest_carries_every_documented_field(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    manifest = _select(repo).manifest

    assert manifest["schema"] == 5
    assert set(manifest) == {
        "schema",
        "base",
        "changed_files",
        "depth",
        "effective_depth",
        "max_ratio",
        "rules_fired",
        "escalated",
        "selected",
        "selected_count",
        "universe_count",
        "baseline",
        "graph",
        "contexts",
        "timings",
    }
    assert manifest["changed_files"] == ["src/pkg/a.py"]
    assert set(manifest["contexts"]) == {
        "baseline",
        "consulted",
        "stale",
        "distance",
        "selected_count",
        "matched_files",
    }
    assert set(manifest["timings"]) == {
        "estimated_serial_seconds",
        "available",
        "reason",
        "coverage",
        "covered_count",
        "missing_count",
        "min_coverage",
        "table",
    }
    # Nothing compensated here, so the walked depth is the configured one.
    assert manifest["effective_depth"] == manifest["depth"]
    assert manifest["selected_count"] == len(manifest["selected"])
    assert manifest["baseline"]["tree_dirty"] is True
    assert manifest["graph"]["modules"] > 0
    assert manifest["graph"]["edges"] > 0


def test_summary_line_reports_escalation(repo: Path) -> None:
    _touch(repo, "Justfile")

    assert "escalated to the full suite" in summary_line(_select(repo))


def test_summary_line_reports_a_scoped_selection(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    assert summary_line(_select(repo)).startswith("selected 5 of ")


def test_paths_output_is_one_path_per_line(repo: Path) -> None:
    _touch(repo, "src/pkg/d.py")

    output = _select(repo).paths_output

    assert output.splitlines() == ["tests/test_d.py"]


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


def test_options_read_the_environment() -> None:
    options = SelectionOptions.from_environment(
        environ={
            "SASE_CHECK_BASE": "origin/main",
            "SASE_TEST_SELECTION_DEPTH": "3",
            "SASE_TEST_SELECTION_MAX_RATIO": "0.4",
        }
    )

    assert options.base_ref == "origin/main"
    assert options.depth == 3
    assert options.max_ratio == 0.4


def test_options_default_when_unset() -> None:
    options = SelectionOptions.from_environment(environ={})

    assert options.base_ref == "origin/master"
    assert options.depth == 2
    assert options.max_ratio == 0.25


@pytest.mark.parametrize(
    "environ",
    [
        {"SASE_TEST_SELECTION_DEPTH": "not-a-number"},
        {"SASE_TEST_SELECTION_DEPTH": "-1"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "0"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "1.5"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "nope"},
    ],
)
def test_options_reject_nonsense(environ: dict[str, str]) -> None:
    with pytest.raises(SelectionError):
        SelectionOptions.from_environment(environ=environ)
