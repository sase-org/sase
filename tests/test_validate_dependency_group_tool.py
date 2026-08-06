from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def _load_validate_dependency_group() -> ModuleType:
    script = ROOT / "tools" / "validate_dependency_group"
    loader = SourceFileLoader("validate_dependency_group_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "validate_dependency_group_tool",
        script,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependency_group_validation_passes_for_installed_dev_group() -> None:
    validator = _load_validate_dependency_group()

    assert validator.validate_dependency_group("dev")


def test_dependency_group_validation_fails_for_unknown_group() -> None:
    validator = _load_validate_dependency_group()

    assert not validator.validate_dependency_group("missing-group")


def test_dependency_group_validation_fails_for_missing_dependency(
    tmp_path: Path,
) -> None:
    validator = _load_validate_dependency_group()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project.optional-dependencies]
dev = ["definitely-missing-sase-test-dependency>=1"]
""".lstrip(),
        encoding="utf-8",
    )

    assert not validator.validate_dependency_group("dev", pyproject)
