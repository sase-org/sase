"""Packaging guards for the screenshot command's PNG renderer dependency."""

from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


_REPO_ROOT = Path(__file__).resolve().parents[1]
_RENDERER = "resvg-py"


def test_screenshot_renderer_is_runtime_dependency_with_aligned_visual_pin() -> None:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    runtime_renderer = _requirement(project["dependencies"], _RENDERER)
    visual_renderer = _requirement(
        project["optional-dependencies"]["visual"],
        _RENDERER,
    )

    assert str(runtime_renderer.specifier) == "==0.3.3"
    assert str(visual_renderer.specifier) == str(runtime_renderer.specifier)


def test_lockfile_records_screenshot_renderer_as_unconditional_dependency() -> None:
    lock = tomllib.loads((_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    sase_package = next(
        package for package in lock["package"] if package["name"] == "sase"
    )

    runtime_dependencies = {
        canonicalize_name(dependency["name"])
        for dependency in sase_package["dependencies"]
    }
    visual_dependencies = {
        canonicalize_name(dependency["name"])
        for dependency in sase_package["optional-dependencies"]["visual"]
    }
    metadata_requirements = [
        dependency
        for dependency in sase_package["metadata"]["requires-dist"]
        if canonicalize_name(dependency["name"]) == _RENDERER
    ]

    assert _RENDERER in runtime_dependencies
    assert _RENDERER in visual_dependencies
    assert {"name": _RENDERER, "specifier": "==0.3.3"} in metadata_requirements
    assert {
        "name": _RENDERER,
        "marker": "extra == 'visual'",
        "specifier": "==0.3.3",
    } in metadata_requirements


def _requirement(requirements: list[str], name: str) -> Requirement:
    for requirement_text in requirements:
        requirement = Requirement(requirement_text)
        if canonicalize_name(requirement.name) == name:
            return requirement
    raise AssertionError(f"{name} missing from dependency list")
