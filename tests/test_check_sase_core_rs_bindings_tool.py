"""Tests for ``tools/check_sase_core_rs_bindings``.

The tool is the published-core-minimum gate: it statically collects every
binding name sase passes to ``require_rust_binding`` and verifies the
installed ``sase_core_rs`` exposes each one. Regression guard for the
sase 0.11.0 release that called the unreleased ``aggregate_clan_runtime``
binding while accepting sase-core-rs 0.6.0.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_sase_core_rs_bindings"
SRC_ROOT = ROOT / "src" / "sase"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("check_sase_core_rs_bindings_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "check_sase_core_rs_bindings_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Python 3.14 dataclasses resolve string annotations through
    # sys.modules[cls.__module__]; register before executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    """Load the standalone audit tool once for this module."""
    return _load_tool()


@pytest.fixture(scope="module")
def _real_source_scan(tool: ModuleType) -> tuple[frozenset[str], tuple[str, ...]]:
    """Share the immutable result of scanning the real source tree."""
    names, problems = tool.collect_binding_names(SRC_ROOT)
    return frozenset(names), tuple(problems)


@pytest.fixture
def real_source_scan(
    _real_source_scan: tuple[frozenset[str], tuple[str, ...]],
) -> tuple[set[str], list[str]]:
    """Give each assertion an isolated mutable view of the shared scan."""
    names, problems = _real_source_scan
    return set(names), list(problems)


def test_scan_resolves_every_call_site_statically(
    real_source_scan: tuple[set[str], list[str]],
) -> None:
    names, problems = real_source_scan
    assert problems == []
    assert names


def test_scan_finds_direct_and_forwarded_binding_names(
    real_source_scan: tuple[set[str], list[str]],
) -> None:
    names, _ = real_source_scan
    # Direct literal call site (the binding behind the 0.11.0 crash).
    assert "aggregate_clan_runtime" in names
    # Names that flow through module-local forwarder helpers.
    assert "save_dismissed_agent_group" in names


def test_dev_extension_exposes_every_collected_name(
    real_source_scan: tuple[set[str], list[str]],
) -> None:
    names, problems = real_source_scan
    assert problems == []
    module = importlib.import_module("sase_core_rs")
    missing = sorted(name for name in names if not hasattr(module, name))
    assert missing == []


def test_scan_flags_unresolvable_binding_names(
    tool: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "sample.py").write_text(
        "from sase.core.rust import require_rust_binding\n"
        "NAME = 'computed'\n"
        "binding = require_rust_binding(NAME)\n",
        encoding="utf-8",
    )
    names, problems = tool.collect_binding_names(tmp_path)
    assert names == set()
    assert len(problems) == 1
    assert "sample.py:3" in problems[0]


def test_scan_resolves_one_level_forwarders(tool: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "from sase.core.rust import require_rust_binding\n"
        "def _core(name):\n"
        "    return require_rust_binding(name)\n"
        "def use():\n"
        "    return _core('forwarded_binding')\n",
        encoding="utf-8",
    )
    names, problems = tool.collect_binding_names(tmp_path)
    assert problems == []
    assert names == {"forwarded_binding"}
