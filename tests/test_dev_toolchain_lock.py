"""Keep the development tool versions aligned with the committed uv lock."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
DEV_TOOLCHAIN = frozenset({"mypy", "ruff", "textual"})


def test_dev_toolchain_pins_match_uv_lock() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_requirements = pyproject["project"]["optional-dependencies"]["dev"]
    dev_pins: dict[str, str] = {}

    for raw_requirement in dev_requirements:
        requirement = Requirement(raw_requirement)
        name = requirement.name.lower()
        if name not in DEV_TOOLCHAIN:
            continue
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1 and specifiers[0].operator == "==", (
            f"{name} must have one exact pin in the dev extra"
        )
        dev_pins[name] = specifiers[0].version

    assert set(dev_pins) == DEV_TOOLCHAIN, "dev extra must pin all lint and UI tools"

    format_requirements = pyproject["dependency-groups"]["format-tools"]
    format_ruff = next(
        Requirement(raw_requirement)
        for raw_requirement in format_requirements
        if Requirement(raw_requirement).name.lower() == "ruff"
    )
    format_ruff_pin = list(format_ruff.specifier)
    assert (
        len(format_ruff_pin) == 1
        and format_ruff_pin[0].operator == "=="
        and format_ruff_pin[0].version == dev_pins["ruff"]
    ), "the format-tools Ruff pin must match the dev extra"

    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    setup_version = re.search(
        r'^format_tools_ruff_version := "([^"]+)"$', justfile, re.MULTILINE
    )
    assert setup_version is not None, "Justfile must declare its formatter Ruff version"
    assert setup_version.group(1) == dev_pins["ruff"]

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for name, version in dev_pins.items():
        locked_versions = {
            package["version"]
            for package in lock["package"]
            if package["name"].lower() == name
        }
        assert locked_versions == {version}, (
            f"{name} dev pin {version} does not match uv.lock versions "
            f"{sorted(locked_versions)}"
        )
