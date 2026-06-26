from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.plugins.catalog import PluginCatalog, PluginCatalogError
from sase.plugins.github_source import GhNotFoundError
from sase.plugins.installed import InstalledInfo
from sase.plugins.operations import (
    AlreadyInstalled,
    InstallNotFound,
    InstallReady,
    NotUvTool,
    execute_install,
    plan_install,
)
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

from ._plugin_operations_helpers import (
    _INSTALL_OUTPUT,
    _catalog,
    _install,
    _not_install,
)


def test_plan_install_not_uv_tool() -> None:
    plan = plan_install(
        "github", load_fn=lambda *, refresh: _catalog(), probe_fn=_not_install
    )
    assert isinstance(plan, NotUvTool)
    assert "uv tool install sase" in str(plan.error)


def test_plan_install_not_found_carries_suggestions(tmp_path: Path) -> None:
    plan = plan_install(
        "githubb",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallNotFound)
    assert plan.query == "githubb"
    assert "github" in {entry.name for entry in plan.suggestions}


def test_plan_install_already_installed(tmp_path: Path) -> None:
    receipt = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
]
"""
    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, receipt),
    )
    assert isinstance(plan, AlreadyInstalled)
    assert plan.spec.display_name == "github"
    assert plan.spec.requirement.name == "sase-github"


def test_plan_install_ready_builds_full_with_set(tmp_path: Path) -> None:
    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)
    # The reconstructed --with set keeps the existing plugin and adds the new one.
    assert plan.argv == [
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "sase",
        "--with",
        "sase-telegram",
        "--with",
        "sase-github",
    ]
    assert plan.spec.source == "catalog"


def test_plan_install_ready_git(tmp_path: Path) -> None:
    plan = plan_install(
        "github",
        git=True,
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)
    assert plan.spec.source == "git"
    assert "git+https://github.com/sase-org/sase-github" in plan.argv


def test_plan_install_catalog_error_propagates(tmp_path: Path) -> None:
    def _load(*, refresh: bool) -> PluginCatalog:
        raise GhNotFoundError()

    with pytest.raises(PluginCatalogError):
        plan_install("github", load_fn=_load, probe_fn=lambda: _install(tmp_path))


def test_plan_install_receipt_error_propagates(tmp_path: Path) -> None:
    from sase.uv_tool.errors import ReceiptError

    install = _install(tmp_path, "this is not toml = [")
    with pytest.raises(ReceiptError):
        plan_install(
            "github", load_fn=lambda *, refresh: _catalog(), probe_fn=lambda: install
        )


def test_plan_install_offline_forwarded_to_loader(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def _load(**kwargs: Any) -> PluginCatalog:
        seen.update(kwargs)
        return _catalog()

    plan = plan_install(
        "github",
        offline=True,
        load_fn=_load,
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)
    assert seen == {"refresh": False, "offline": True}


def test_execute_install_runs_and_collects_groups(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_INSTALL_OUTPUT)

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)

    clock = iter([10.0, 12.5])
    outcome = execute_install(
        plan,
        run_fn=_run,
        installed_index_fn=lambda: {
            "sase-github": InstalledInfo(
                installed=True, version="0.4.0", entry_point_groups=("sase_vcs",)
            )
        },
        clock=lambda: next(clock),
    )
    assert seen["argv"] == plan.argv
    assert outcome.groups == ("sase_vcs",)
    assert outcome.elapsed == 2.5
    assert outcome.change_set.get("sase-github") is not None


def test_execute_install_groups_are_best_effort(tmp_path: Path) -> None:
    def _bad_index() -> dict[str, InstalledInfo]:
        raise RuntimeError("entry-point scan blew up")

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)
    outcome = execute_install(
        plan,
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=_bad_index,
        clock=lambda: 0.0,
    )
    assert outcome.groups == ()


def test_execute_install_uv_error_propagates(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
    )
    assert isinstance(plan, InstallReady)
    with pytest.raises(UvCommandFailedError):
        execute_install(plan, run_fn=_run, clock=lambda: 0.0)
