from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.plugins.catalog import PluginCatalog, PluginCatalogError
from sase.plugins.github_source import GhNotFoundError
from sase.plugins.operations import (
    AlreadyAbsent,
    NotUvTool,
    UninstallReady,
    UninstallUnknown,
    execute_uninstall,
    plan_uninstall,
)
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

from ._plugin_operations_helpers import (
    _UNINSTALL_OUTPUT,
    _UPDATE_RECEIPT,
    _catalog,
    _install,
    _not_install,
)


def test_plan_uninstall_not_uv_tool() -> None:
    plan = plan_uninstall("github", probe_fn=_not_install)
    assert isinstance(plan, NotUvTool)
    assert "uv tool install sase" in str(plan.error)


def test_plan_uninstall_ready_from_receipt_without_catalog(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise AssertionError("catalog must not load for an installed plugin")

    plan = plan_uninstall(
        "github",
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UninstallReady)
    assert plan.dist_name == "sase-github"
    assert plan.display_name == "github"
    # Full set re-injected minus sase-github; sase core and sase-telegram stay.
    assert plan.argv == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-telegram",
    ]


def test_plan_uninstall_removes_all_dev_duplicates(tmp_path: Path) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase", editable = "/home/u/sase" },
    { name = "sase-github", editable = "/home/u/sase-github" },
    { name = "sase-telegram" },
    { name = "sase-github" },
]
"""
    plan = plan_uninstall(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
    )
    assert isinstance(plan, UninstallReady)
    assert "sase-github" not in plan.argv
    assert "/home/u/sase-github" not in plan.argv
    assert plan.argv[:9] == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--editable",
        "/home/u/sase",
        "--with",
        "sase-telegram",
    ]
    assert plan.argv[-2] == "--overrides"
    overrides_path = Path(plan.argv[-1])
    assert (
        overrides_path.read_text(encoding="utf-8") == "-e /home/u/sase\nsase-core-rs\n"
    )


def test_plan_uninstall_community_plugin_absent_from_catalog(tmp_path: Path) -> None:
    # A plugin injected via a raw spec but not in the catalog still resolves
    # straight from the receipt (no catalog fetch).
    receipt = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-acme" },
]
"""

    def _load(*, refresh: bool) -> PluginCatalog:
        raise AssertionError("catalog must not load for an installed plugin")

    plan = plan_uninstall(
        "sase-acme",
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path, receipt),
    )
    assert isinstance(plan, UninstallReady)
    assert plan.dist_name == "sase-acme"
    assert plan.display_name == "acme"


def test_plan_uninstall_known_but_absent_is_noop(tmp_path: Path) -> None:
    plan = plan_uninstall(
        "jira",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, AlreadyAbsent)
    assert plan.name == "jira"


def test_plan_uninstall_unknown_carries_suggestions(tmp_path: Path) -> None:
    plan = plan_uninstall(
        "githubb",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UninstallUnknown)
    assert plan.query == "githubb"
    assert "github" in {entry.name for entry in plan.suggestions}


def test_plan_uninstall_receipt_error_propagates(tmp_path: Path) -> None:
    from sase.uv_tool.errors import ReceiptError

    install = _install(tmp_path, "not = valid = toml")
    with pytest.raises(ReceiptError):
        plan_uninstall("github", probe_fn=lambda: install)


def test_plan_uninstall_catalog_error_propagates(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise GhNotFoundError()

    # A receipt miss falls through to the catalog, whose load raises.
    with pytest.raises(PluginCatalogError):
        plan_uninstall(
            "jira",
            load_fn=_load,
            probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
        )


def test_plan_uninstall_offline_forwarded_on_catalog_miss(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def _load(**kwargs: Any) -> PluginCatalog:
        seen.update(kwargs)
        return _catalog()

    plan = plan_uninstall(
        "jira",
        offline=True,
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, AlreadyAbsent)
    assert seen == {"refresh": False, "offline": True}


def test_execute_uninstall_runs_and_collects(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UNINSTALL_OUTPUT)

    plan = plan_uninstall(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UninstallReady)
    clock = iter([2.0, 3.5])
    outcome = execute_uninstall(plan, run_fn=_run, clock=lambda: next(clock))
    assert seen["argv"] == plan.argv
    assert outcome.elapsed == 1.5
    removed = outcome.change_set.get("sase-github")
    assert removed is not None
    assert removed.kind.value == "removed"


def test_execute_uninstall_uv_error_propagates(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="boom")

    plan = plan_uninstall(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UninstallReady)
    with pytest.raises(UvCommandFailedError):
        execute_uninstall(plan, run_fn=_run, clock=lambda: 0.0)
