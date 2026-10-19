"""Unit tests for tools/check_testpypi_drill (phase sase-1my.5).

All registry reads use in-memory fixtures: no network. Each drill step is
covered green, plus the fail-closed cases the epic plan requires: an
unreachable registry, malformed evidence, a not-actually-broken 0.0.2, a
mid-drill un-yank, and a yanked release whose files are gone.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_testpypi_drill"

API = "https://test.pypi.org/pypi/"
PROJECT = "sase-yank-drill"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_testpypi_drill_test", str(TOOL_PATH))
    spec = importlib.util.spec_from_loader("check_testpypi_drill_test", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


tool = _load_tool()


def _file(version: str, yanked: bool | str = False) -> dict[str, Any]:
    return {"filename": f"{PROJECT}-{version}-py3-none-any.whl", "yanked": yanked}


def _fixture(
    versions: dict[str, list[dict[str, Any]]],
    deps: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    deps = deps or {}
    mapping: dict[str, Any] = {
        f"{API}{PROJECT}/json": {
            "info": {"version": "0.0.3"},
            "releases": versions,
        },
    }
    for version in versions:
        mapping[f"{API}{PROJECT}/{version}/json"] = {
            "info": {
                "version": version,
                "yanked": all(
                    bool(entry.get("yanked", False)) for entry in versions[version]
                ),
                "requires_dist": deps.get(version),
            },
        }
    return mapping


def _fetch_for(mapping: dict[str, Any]) -> Any:
    def _fetch(url: str) -> Any:
        return mapping[url]

    return _fetch


def test_good_step_is_green_when_001_is_published() -> None:
    mapping = _fixture({"0.0.1": [_file("0.0.1")]})
    assert tool.check(PROJECT, "good", API, _fetch_for(mapping)).ok


def test_broken_step_names_the_unsatisfiable_dependency() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": [_file("0.0.2")]},
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    verdict = tool.check(PROJECT, "broken", API, _fetch_for(mapping))
    assert verdict.ok
    assert "sase-yank-drill-does-not-exist" in verdict.reason


def test_yanked_step_falls_back_to_001() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": [_file("0.0.2", "manual")]},
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    assert tool.check(PROJECT, "yanked", API, _fetch_for(mapping)).ok


def test_fixed_step_is_green_with_002_still_yanked() -> None:
    mapping = _fixture(
        {
            "0.0.1": [_file("0.0.1")],
            "0.0.2": [_file("0.0.2", True)],
            "0.0.3": [_file("0.0.3")],
        },
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    assert tool.check(PROJECT, "fixed", API, _fetch_for(mapping)).ok


def test_a_yanked_newest_release_is_ignored() -> None:
    mapping = _fixture(
        {
            "0.0.1": [_file("0.0.1")],
            "0.0.2": [_file("0.0.2", True)],
            "0.0.3": [_file("0.0.3", True)],
        },
    )
    verdict = tool.check(PROJECT, "yanked", API, _fetch_for(mapping))
    assert verdict.ok


def test_unreachable_registry_fails_closed() -> None:
    def _boom(url: str) -> Any:
        raise tool.DrillFetchError("GET: unreachable")

    verdict = tool.check(PROJECT, "good", API, _boom)
    assert not verdict.ok
    assert "DRILL_FETCH_ERROR" in verdict.reason


def test_malformed_project_document_fails_closed() -> None:
    mapping = {f"{API}{PROJECT}/json": {"info": {}}}
    verdict = tool.check(PROJECT, "good", API, _fetch_for(mapping))
    assert not verdict.ok
    assert "DRILL_FETCH_ERROR" in verdict.reason


def test_broken_step_is_red_when_002_has_no_dependency() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": [_file("0.0.2")]},
    )
    verdict = tool.check(PROJECT, "broken", API, _fetch_for(mapping))
    assert not verdict.ok
    assert "DRILL_NOT_BROKEN" in verdict.reason


def test_yanked_step_is_red_while_002_is_installable() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": [_file("0.0.2")]},
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    verdict = tool.check(PROJECT, "yanked", API, _fetch_for(mapping))
    assert not verdict.ok
    assert "DRILL_NOT_YANKED" in verdict.reason


def test_yanked_step_is_red_when_002_files_are_gone() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": []},
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    verdict = tool.check(PROJECT, "yanked", API, _fetch_for(mapping))
    assert not verdict.ok


def test_fixed_step_is_red_when_002_was_unyanked() -> None:
    mapping = _fixture(
        {
            "0.0.1": [_file("0.0.1")],
            "0.0.2": [_file("0.0.2")],
            "0.0.3": [_file("0.0.3")],
        },
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    verdict = tool.check(PROJECT, "fixed", API, _fetch_for(mapping))
    assert not verdict.ok
    assert "DRILL_NOT_YANKED" in verdict.reason


def test_fixed_step_is_red_when_003_is_not_winning() -> None:
    mapping = _fixture(
        {"0.0.1": [_file("0.0.1")], "0.0.2": [_file("0.0.2", True)]},
        deps={"0.0.2": ["sase-yank-drill-does-not-exist>=1"]},
    )
    verdict = tool.check(PROJECT, "fixed", API, _fetch_for(mapping))
    assert not verdict.ok
    assert "DRILL_NOT_PUBLISHED" in verdict.reason


def test_unknown_step_raises() -> None:
    state = tool.ProjectState(releases={})
    with pytest.raises(ValueError, match="unknown drill step"):
        tool.evaluate(state, "explode")
