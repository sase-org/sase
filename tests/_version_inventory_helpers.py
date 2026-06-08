"""Helpers for version inventory tests."""

from __future__ import annotations

import json
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

import pytest

from sase.version import inventory as inv


class _FakeDistribution:
    def __init__(
        self,
        *,
        name: str,
        version: str,
        location: Path,
        direct_url: str | None = None,
        entry_points: tuple[_FakeEntryPoint, ...] = (),
        top_level_text: str | None = None,
    ) -> None:
        self.metadata = {"Name": name, "Version": version}
        self.version = version
        self._location = location
        self._direct_url = direct_url
        self.entry_points = entry_points
        self._top_level_text = top_level_text

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self._direct_url
        if filename == "top_level.txt":
            return self._top_level_text
        return None

    def locate_file(self, path: object) -> Path:
        return self._location / str(path)


class _FakeEntryPoint:
    def __init__(self, *, group: str, name: str, value: str) -> None:
        self.group = group
        self.name = name
        self.value = value
        self.load_calls = 0

    def load(self) -> object:
        self.load_calls += 1
        raise AssertionError("version inventory must not load plugin entry points")


def _patch_distribution(
    monkeypatch: pytest.MonkeyPatch,
    distribution: _FakeDistribution,
) -> None:
    def fake_distribution(name: str) -> _FakeDistribution:
        if name == distribution.metadata["Name"]:
            return distribution
        raise inv.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inv.importlib.metadata, "distribution", fake_distribution)


def _patch_distribution_map(
    monkeypatch: pytest.MonkeyPatch,
    distributions: list[_FakeDistribution],
) -> None:
    by_name = {
        inv._normalize_distribution_name(dist.metadata["Name"]): dist
        for dist in distributions
    }

    def fake_distribution(name: str) -> _FakeDistribution:
        dist = by_name.get(inv._normalize_distribution_name(name))
        if dist is not None:
            return dist
        raise inv.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inv.importlib.metadata, "distribution", fake_distribution)


def _patch_distributions(
    monkeypatch: pytest.MonkeyPatch,
    distributions: list[_FakeDistribution],
) -> None:
    monkeypatch.setattr(inv.importlib.metadata, "distributions", lambda: distributions)


def _package_spec(name: str, package_dir: Path) -> ModuleSpec:
    spec = ModuleSpec(
        name,
        loader=None,
        origin=str(package_dir / "__init__.py"),
        is_package=True,
    )
    spec.submodule_search_locations = [str(package_dir)]
    return spec


def _module_spec(name: str, origin: Path) -> ModuleSpec:
    return ModuleSpec(name, loader=None, origin=str(origin))


def _patch_find_spec(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, ModuleSpec],
) -> None:
    def fake_find_spec(name: str, *_args: Any, **_kwargs: Any) -> ModuleSpec | None:
        return mapping.get(name)

    monkeypatch.setattr(inv.importlib.util, "find_spec", fake_find_spec)


def _editable_direct_url(source_root: Path) -> str:
    return json.dumps(
        {
            "url": source_root.as_uri(),
            "dir_info": {"editable": True},
        }
    )
