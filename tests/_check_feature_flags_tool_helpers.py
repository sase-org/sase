"""Shared helpers for ``tools/check_feature_flags`` tests."""

from __future__ import annotations

import importlib.util
import stat
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from sase.feature_flags import FeatureFlag, FeatureFlagDefinition
from sase.feature_flags.schema import feature_flags_schema_block


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_feature_flags"


@pytest.fixture(autouse=True)
def _restore_sys_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # The tool inserts `src` onto sys.path at import time so it keeps working
    # when run standalone. _load_tool() re-executes that module on every
    # call, so without this the insert accumulates across tests.
    monkeypatch.syspath_prepend(str(ROOT / "src"))


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_feature_flags_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "check_feature_flags_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.14) resolve annotations via sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_executable(path: Path, text: str) -> Path:
    _write(path, text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _rules(findings: list[Any]) -> list[int]:
    return [finding.rule for finding in findings]


def _broken_flag(
    key: str = "broken_flag",
    *,
    kind: str = "beta",
    bead: str | None = None,
) -> FeatureFlagDefinition:
    return FeatureFlagDefinition(
        key=cast(FeatureFlag, key),
        kind=cast(Any, kind),
        description=f"Description for {key}",
        bead=bead,
    )


def _schema_document(defs: dict[str, FeatureFlagDefinition]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"feature_flags": feature_flags_schema_block(defs)},
    }


def _bead(
    tool: ModuleType,
    *,
    bead_id: str = "sase-nb.test",
    key: str = "demo_flag",
    status: str = "open",
    issue_type: str = "task",
    remove_by_date: str = "2026-12-01",
    remove_by_release: str = "0.19.0",
    source: str = "flag",
    task_type: str = "flag",
    kind: str | None = None,
    created_at: str | None = None,
    created_by: str | None = None,
) -> Any:
    return tool.MarkerBead(
        source=source,
        id=bead_id,
        issue_type=issue_type,
        status=status,
        key=key,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
        task_type=task_type,
        kind=kind,
        created_at=created_at,
        created_by=created_by,
    )
