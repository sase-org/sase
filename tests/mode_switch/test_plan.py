from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import sase.mode_switch.plan as plan_mod
from sase.mode_switch.models import SwitchPlan
from sase.mode_switch.plan import plan_mode_switch
from sase.uv_tool.detect import UvToolInstall
from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord
from sase.version._git import GitUpstreamStatus

_PYPI_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
    { name = "sase-github" },
]
"""

_PYPI_PRIMARY_RECEIPT = """
[tool]
requirements = [
    { name = "sase" },
]
"""

_DEV_RECEIPT = """
[tool]
requirements = [
    { name = "sase", editable = "/src/sase" },
    { name = "sase-github", editable = "/src/sase-github" },
    { name = "sase-github" },
]
"""


def _install(tmp_path: Path, receipt_text: str) -> UvToolInstall:
    tool = tmp_path / "tool" / "sase"
    tool.mkdir(parents=True)
    receipt = tool / "uv-receipt.toml"
    receipt.write_text(receipt_text, encoding="utf-8")
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path / "tool",
        sase_dir=tool,
        receipt_path=receipt,
    )


def _record(name: str, role: str, version: str) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=version,
        distribution_version=version,
        source_version=None,
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=None,
        distribution_location=None,
        install_type="wheel",
        git=None,
    )


def _inventory() -> RuntimeVersionInventory:
    return RuntimeVersionInventory(
        executable="sase",
        python_executable="/venv/bin/python",
        python_version="3.12",
        packages=(
            _record("sase", "host", "0.8.0"),
            _record("sase-core-rs", "core", "0.3.1"),
            _record("sase-github", "plugin", "0.1.0"),
        ),
    )


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _configure_test_user(repo: Path) -> None:
    _git(repo, "config", "user.email", "sase-tests@example.invalid")
    _git(repo, "config", "user.name", "SASE Tests")


def _commit_python_version(repo: Path, version: str) -> str:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "sase"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    _git(repo, "add", "pyproject.toml")
    _git(repo, "commit", "-m", f"version {version}")
    return _git(repo, "rev-parse", "--short=9", "HEAD")


def _init_behind_checkout(tmp_path: Path) -> tuple[Path, str, str]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "dev" / "sase-org" / "sase"

    _git(tmp_path, "init", "--bare", "--initial-branch", "master", str(origin))
    _git(tmp_path, "init", "--initial-branch", "master", str(seed))
    _configure_test_user(seed)
    _git(seed, "remote", "add", "origin", str(origin))
    old_short = _commit_python_version(seed, "0.1.0")
    _git(seed, "push", "-u", "origin", "master")
    new_short = _commit_python_version(seed, "0.2.0")
    _git(seed, "push", "origin", "master")

    checkout.parent.mkdir(parents=True)
    _git(tmp_path, "clone", str(origin), str(checkout))
    _git(checkout, "reset", "--hard", "HEAD~1")
    return checkout, old_short, new_short


def _status(
    root: str,
    *,
    upstream: str | None = "origin/master",
    remote: str | None = "origin",
    remote_branch: str | None = "master",
    detached: bool = False,
    dirty: bool = False,
    ahead: int | None = 0,
    behind: int | None = 1,
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root=root,
        upstream=upstream,
        remote=remote,
        remote_branch=remote_branch,
        detached=detached,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def _primary_dev_plan(
    tmp_path: Path, *, which_fn: Callable[[str], str | None] | None = None
) -> SwitchPlan:
    return plan_mode_switch(
        _install(tmp_path, _PYPI_PRIMARY_RECEIPT),
        target_mode="dev",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        which_fn=which_fn
        if which_fn is not None
        else lambda name: "/usr/bin/git" if name == "git" else None,
    )


def test_plan_to_dev_builds_editable_reinstall_command(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _PYPI_RECEIPT),
        target_mode="dev",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.current_mode == "managed"
    assert plan.target_mode == "dev"
    assert [package.name for package in plan.packages] == [
        "sase",
        "sase-core-rs",
        "sase-github",
    ]
    uv_command = next(
        command for command in plan.commands if command.kind == "uv_tool_install"
    )
    assert uv_command.command[:7] == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--force",
        "--reinstall",
    )
    assert "--editable" in uv_command.command
    assert str(tmp_path / "dev" / "sase-org" / "sase") in uv_command.command
    assert "--with-editable" in uv_command.command
    assert str(tmp_path / "dev" / "sase-org" / "sase-github") in uv_command.command
    assert uv_command.command[-2] == "--overrides"
    overrides_path = Path(uv_command.command[-1])
    assert overrides_path.read_text(encoding="utf-8") == (
        f"-e {tmp_path / 'dev' / 'sase-org' / 'sase'}\n"
        f"-e {tmp_path / 'dev' / 'sase-org' / 'sase-github'}\n"
        "sase-core-rs\n"
    )

    clone_commands = {
        command.label: command.command
        for command in plan.commands
        if command.kind == "git_clone"
    }
    assert clone_commands["Clone sase"] == (
        "git",
        "clone",
        "git@github.com:sase-org/sase.git",
        str(tmp_path / "dev" / "sase-org" / "sase"),
    )
    assert clone_commands["Clone sase-core-rs"] == (
        "git",
        "clone",
        "git@github.com:sase-org/sase-core.git",
        str(tmp_path / "dev" / "sase-org" / "sase-core"),
    )
    assert clone_commands["Clone sase-github"] == (
        "git",
        "clone",
        "git@github.com:sase-org/sase-github.git",
        str(tmp_path / "dev" / "sase-org" / "sase-github"),
    )
    assert "git_merge_ff" not in [command.kind for command in plan.commands]


def test_plan_to_dev_fast_forwards_clean_existing_checkout(
    tmp_path: Path,
) -> None:
    checkout, old_short, new_short = _init_behind_checkout(tmp_path)

    plan = _primary_dev_plan(tmp_path)

    command_kinds = [command.kind for command in plan.commands]
    assert command_kinds[:3] == ["git_fetch", "git_merge_ff", "uv_tool_install"]
    assert plan.commands[0].command == (
        "git",
        "fetch",
        "--quiet",
        "--tags",
        "--force",
        "origin",
        "+refs/heads/master:refs/remotes/origin/master",
    )
    assert plan.commands[0].cwd == str(checkout)
    assert plan.commands[1].command == (
        "git",
        "merge",
        "--ff-only",
        "origin/master",
    )
    assert plan.commands[1].cwd == str(checkout)

    package = next(package for package in plan.packages if package.name == "sase")
    assert package.warning is None
    assert package.target_version is not None
    assert new_short in package.target_version
    assert old_short not in package.target_version


def test_plan_to_dev_fast_forwards_checkout_that_looks_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "dev" / "sase-org" / "sase"
    checkout.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plan_mod,
        "classify_git_upstream",
        lambda _path: _status(str(checkout), ahead=0, behind=0),
    )

    plan = _primary_dev_plan(tmp_path)

    assert [command.kind for command in plan.commands[:3]] == [
        "git_fetch",
        "git_merge_ff",
        "uv_tool_install",
    ]


@pytest.mark.parametrize(
    ("status", "warning"),
    [
        (_status("/unused", dirty=True), "checkout has local changes; reused as-is"),
        (
            _status("/unused", detached=True, upstream=None, ahead=None, behind=None),
            "checkout is detached",
        ),
        (
            _status("/unused", ahead=1, behind=1),
            "checkout has diverged from upstream; reused as-is",
        ),
        (
            _status("/unused", ahead=1, behind=0),
            "checkout is ahead of upstream; reused as-is",
        ),
        (
            _status(
                "/unused",
                upstream=None,
                remote=None,
                remote_branch=None,
                ahead=None,
                behind=None,
            ),
            "checkout has no upstream; reused as-is",
        ),
    ],
)
def test_plan_to_dev_reuses_unsafe_existing_checkouts_as_is(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: GitUpstreamStatus,
    warning: str,
) -> None:
    checkout = tmp_path / "dev" / "sase-org" / "sase"
    checkout.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plan_mod,
        "classify_git_upstream",
        lambda _path: GitUpstreamStatus(
            root=str(checkout),
            upstream=status.upstream,
            remote=status.remote,
            remote_branch=status.remote_branch,
            detached=status.detached,
            dirty=status.dirty,
            ahead=status.ahead,
            behind=status.behind,
        ),
    )

    plan = _primary_dev_plan(tmp_path)

    assert "git_merge_ff" not in [command.kind for command in plan.commands]
    fetch = next(command for command in plan.commands if command.kind == "git_fetch")
    assert fetch.cwd == str(checkout)
    assert fetch.command[:5] == ("git", "fetch", "--quiet", "--tags", "--force")
    package = next(package for package in plan.packages if package.name == "sase")
    assert package.warning == warning
    assert f"sase: {warning}" in plan.warnings


def test_plan_to_pypi_swaps_editables_for_index_specs(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _DEV_RECEIPT),
        target_mode="pypi",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        latest_fn=lambda name: {"sase": "0.8.1", "sase-core-rs": "0.3.2"}.get(name),
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.current_mode == "dev"
    uv_command = plan.commands[0]
    assert uv_command.command == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--force",
        "--reinstall",
        "sase",
        "--with",
        "sase-github",
    )
    assert plan.packages[0].target_version == "0.8.1"
    assert plan.packages[1].target_version == "0.3.2"


def test_plan_current_mode_is_noop(tmp_path: Path) -> None:
    plan = plan_mode_switch(
        _install(tmp_path, _PYPI_RECEIPT),
        target_mode="pypi",
        config={},
        inventory_fn=_inventory,
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert plan.changed is False
    assert plan.commands == ()


def test_plan_to_dev_warns_about_legacy_flat_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_checkout = tmp_path / "projects" / "git" / "sase"
    legacy_checkout.mkdir(parents=True)

    plan = plan_mode_switch(
        _install(tmp_path, _PYPI_RECEIPT),
        target_mode="dev",
        config={"update": {"dev_root": str(tmp_path / "dev")}},
        inventory_fn=_inventory,
        which_fn=lambda name: f"/usr/bin/{name}",
    )

    assert (
        f"sase: existing checkout at {legacy_checkout} is no longer used "
        f"(new location: {tmp_path / 'dev' / 'sase-org' / 'sase'})" in plan.warnings
    )
