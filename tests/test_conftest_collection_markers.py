"""Tests for root ``conftest.py`` collection hooks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tests import conftest


class _Item:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.markers: list[Any] = []

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)


def test_plan_chain_marker_uses_lexical_repo_relative_paths() -> None:
    item = _Item(conftest._REPO_ROOT / "tests/test_plan_rejection_response.py")
    config = SimpleNamespace(option=SimpleNamespace(collectonly=False))

    conftest.pytest_collection_modifyitems(
        config,
        [item],  # type: ignore[arg-type, list-item]
    )

    assert [marker.name for marker in item.markers] == ["plan_chain_golden"]


def test_plan_chain_marker_ignores_paths_outside_repo() -> None:
    item = _Item(Path("/tmp/test_plan_rejection_response.py"))
    config = SimpleNamespace(option=SimpleNamespace(collectonly=False))

    conftest.pytest_collection_modifyitems(
        config,
        [item],  # type: ignore[arg-type, list-item]
    )

    assert item.markers == []


def test_collect_only_skips_hypothesis_local_constant_prescan(
    monkeypatch: Any,
) -> None:
    from hypothesis.internal.conjecture import providers

    def marker() -> object:
        return object()

    monkeypatch.setattr(providers, "_get_local_constants", marker)
    config = SimpleNamespace(option=SimpleNamespace(collectonly=True))

    conftest._disable_hypothesis_local_constant_prescan_for_collect_only(config)

    assert providers._get_local_constants() is providers._local_constants
    conftest._restore_hypothesis_local_constant_prescan()
    assert providers._get_local_constants is marker


def test_non_collect_only_keeps_hypothesis_local_constant_scan(
    monkeypatch: Any,
) -> None:
    from hypothesis.internal.conjecture import providers

    def marker() -> object:
        return object()

    monkeypatch.setattr(providers, "_get_local_constants", marker)
    config = SimpleNamespace(option=SimpleNamespace(collectonly=False))

    conftest._disable_hypothesis_local_constant_prescan_for_collect_only(config)

    assert providers._get_local_constants is marker
