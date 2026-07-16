from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.plugins.catalog import PluginCatalog, PluginCatalogError
from sase.plugins.github_source import GhNotFoundError
from sase.plugins.operations import (
    NoPlugins,
    NotInstalled,
    NotUvTool,
    UpdateReady,
    UpdateUnknown,
    execute_update,
    plan_update,
)
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

from ._plugin_operations_helpers import (
    _UPDATE_RECEIPT,
    _UPGRADE_OUTPUT,
    _catalog,
    _install,
    _not_install,
)


def test_plan_update_not_uv_tool() -> None:
    plan = plan_update("github", probe_fn=_not_install)
    assert isinstance(plan, NotUvTool)
    assert "uv tool install sase" in str(plan.error)


def test_plan_update_no_plugins(tmp_path: Path) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase" },
]
"""
    plan = plan_update(
        None, all_plugins=True, probe_fn=lambda: _install(tmp_path, receipt)
    )
    assert isinstance(plan, NoPlugins)


def test_plan_update_ready_single_from_receipt(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise AssertionError("catalog must not load for an installed plugin")

    plan = plan_update(
        "github",
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UpdateReady)
    assert plan.all_plugins is False
    assert plan.targets == ("sase-github",)
    # Full set re-injected; only sase-github gets --upgrade-package (core pinned).
    assert plan.argv == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-github",
        "--with",
        "sase-telegram",
        "--upgrade-package",
        "sase-github",
    ]


def test_plan_update_ready_writes_overrides_for_editable_target_set(
    tmp_path: Path,
) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase", editable = "/src/sase" },
    { name = "sase-github", editable = "/src/sase-github" },
    { name = "sase-telegram" },
]
"""

    plan = plan_update(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
    )

    assert isinstance(plan, UpdateReady)
    assert plan.argv[-4] == "--overrides"
    overrides_path = Path(plan.argv[-3])
    assert plan.argv[-2:] == ["--upgrade-package", "sase-github"]
    assert overrides_path.read_text(encoding="utf-8") == (
        "-e /src/sase\n-e /src/sase-github\nsase-core-rs\n"
    )


def test_plan_update_ready_all(tmp_path: Path) -> None:
    plan = plan_update(
        None,
        all_plugins=True,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UpdateReady)
    assert plan.all_plugins is True
    assert plan.targets == ("sase-github", "sase-telegram")
    assert plan.argv.count("--upgrade-package") == 2


def test_plan_update_known_but_not_installed(tmp_path: Path) -> None:
    plan = plan_update(
        "jira",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, NotInstalled)
    assert plan.name == "jira"


def test_plan_update_unknown_carries_suggestions(tmp_path: Path) -> None:
    plan = plan_update(
        "githubb",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UpdateUnknown)
    assert plan.query == "githubb"
    assert "github" in {entry.name for entry in plan.suggestions}


def test_plan_update_receipt_error_propagates(tmp_path: Path) -> None:
    from sase.uv_tool.errors import ReceiptError

    install = _install(tmp_path, "not = valid = toml")
    with pytest.raises(ReceiptError):
        plan_update("github", probe_fn=lambda: install)


def test_plan_update_catalog_error_propagates(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise GhNotFoundError()

    # A miss falls through to the catalog, whose load raises.
    with pytest.raises(PluginCatalogError):
        plan_update(
            "jira",
            load_fn=_load,
            probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
        )


def test_plan_update_offline_forwarded_on_catalog_miss(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def _load(**kwargs: Any) -> PluginCatalog:
        seen.update(kwargs)
        return _catalog()

    plan = plan_update(
        "jira",
        offline=True,
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, NotInstalled)
    assert seen == {"refresh": False, "offline": True}


def test_execute_update_runs_and_collects(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    plan = plan_update(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UpdateReady)
    clock = iter([1.0, 4.5])
    outcome = execute_update(plan, run_fn=_run, clock=lambda: next(clock))
    assert seen["argv"] == plan.argv
    assert outcome.elapsed == 3.5
    assert outcome.change_set.get("sase-github") is not None


def test_execute_update_uv_error_propagates(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="boom")

    plan = plan_update(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(plan, UpdateReady)
    with pytest.raises(UvCommandFailedError):
        execute_update(plan, run_fn=_run, clock=lambda: 0.0)
