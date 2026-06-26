"""Tests for the console-free plugin operations layer (``operations.py``).

These exercise the ``plan_*`` / ``execute_*`` split directly — the same seam the
CLI handlers and the future TUI both consume — covering every typed outcome,
the exact ``uv`` argv each plan builds, the receipt-first update resolution, and
the two failure modes (catalog error, malformed receipt) that propagate as
exceptions rather than typed outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
)
from sase.plugins.github_source import GhNotFoundError
from sase.plugins.installed import InstalledInfo
from sase.plugins.operations import (
    AlreadyAbsent,
    AlreadyInstalled,
    InstallNotFound,
    InstallReady,
    NoPlugins,
    NotInstalled,
    NotUvTool,
    UninstallReady,
    UninstallUnknown,
    UpdateReady,
    UpdateUnknown,
    execute_install,
    execute_uninstall,
    execute_update,
    plan_install,
    plan_uninstall,
    plan_update,
    resolve_install_spec,
)
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _entry(
    name: str,
    owner: str = "sase-org",
    *,
    repo: str | None = None,
    installed: bool = False,
) -> PluginCatalogEntry:
    repo = repo if repo is not None else f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description="desc",
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=("sase-plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
        installed=InstalledInfo(installed=installed),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries
        or (
            _entry("github"),
            _entry("telegram"),
            _entry("jira", "acme", repo="acme-jira"),
        ),
        from_cache=True,
        stale=False,
    )


_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-telegram" },
]
"""

_UPDATE_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
    { name = "sase-telegram" },
]
"""


def _install(tmp_path: Path, receipt: str = _RECEIPT) -> UvToolInstall:
    sase_dir = tmp_path / "sase"
    sase_dir.mkdir(parents=True, exist_ok=True)
    path = sase_dir / "uv-receipt.toml"
    path.write_text(receipt, encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=sase_dir,
        receipt_path=path,
    )


def _not_install() -> NotUvToolInstall:
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=Path("/home/u/sase/.venv"),
        expected_sase_dir=Path("/t/sase"),
        receipt_path=Path("/t/sase/uv-receipt.toml"),
        uv_path="/usr/bin/uv",
    )


_INSTALL_OUTPUT = """\
Resolved 2 packages in 120ms
 + sase-github==0.4.0
"""

_UPGRADE_OUTPUT = """\
Resolved 3 packages in 90ms
 - sase-github==0.3.2
 + sase-github==0.4.0
"""

_UNINSTALL_OUTPUT = """\
Resolved 1 package in 50ms
 - sase-github==0.4.0
Uninstalled 1 package
"""


# --------------------------------------------------------------------------- #
# resolve_install_spec (public)
# --------------------------------------------------------------------------- #


def test_resolve_install_spec_catalog() -> None:
    spec = resolve_install_spec(_catalog(), "github")
    assert spec is not None
    assert spec.source == "catalog"
    assert spec.display_name == "github"
    assert spec.requirement.requirement_argument() == "sase-github"
    assert spec.normalized_name == "sase-github"


def test_resolve_install_spec_git_forces_repo_url() -> None:
    spec = resolve_install_spec(_catalog(), "github", git=True)
    assert spec is not None
    assert spec.source == "git"
    assert (
        spec.requirement.requirement_argument()
        == "git+https://github.com/sase-org/sase-github"
    )


def test_resolve_install_spec_passthrough_and_unknown() -> None:
    passthrough = resolve_install_spec(_catalog(), "sase-foo==1.2")
    assert passthrough is not None
    assert passthrough.source == "passthrough"
    assert resolve_install_spec(_catalog(), "nope") is None


# --------------------------------------------------------------------------- #
# plan_install
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# execute_install
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# plan_update
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# execute_update
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# plan_uninstall
# --------------------------------------------------------------------------- #


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
    assert plan.argv == [
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


# --------------------------------------------------------------------------- #
# execute_uninstall
# --------------------------------------------------------------------------- #


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
