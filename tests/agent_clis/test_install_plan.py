"""Plan/classifier tests for provider-declared agent-CLI install scripts."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from sase.agent_clis.install import (
    AgentCliInstallError,
    AgentCliInstallsPlanned,
    InstallScript,
    describe_agent_cli_install,
    plan_agent_cli_install_status,
    plan_agent_cli_installs,
)
from sase.agent_clis.models import (
    AgentCliUnknownName,
    InstallRoute,
)

from .install_helpers import (
    SCRIPT_DIGEST,
    SCRIPT_URL,
    _fetch,
    _never_run,
    _npm_bin,
    _npm_probe,
    _npm_status,
    _status,
)


def test_plan_skips_a_cli_with_no_runnable_installer() -> None:
    status = replace(
        _status("antigravity", install_script_url=None),
        install_manager="native",
        install_hint="install from https://example.test/antigravity",
        docs_url="https://example.test/antigravity",
    )

    entry = plan_agent_cli_install_status(
        status,
        fetch_fn=lambda _url: (_ for _ in ()).throw(AssertionError("must not fetch")),
        run_fn=_never_run,
    )

    assert entry.ready is False
    assert entry.route is InstallRoute.MANUAL
    assert entry.script is None
    assert entry.skip_reason is not None
    assert "install from https://example.test/antigravity" in entry.skip_reason


def test_classifier_routes_script_npm_manual_and_bundled() -> None:
    script = describe_agent_cli_install(_status())
    assert script.route is InstallRoute.SCRIPT
    assert script.installable is True
    assert script.source == SCRIPT_URL
    assert script.reason is None

    npm = describe_agent_cli_install(_npm_status())
    assert npm.route is InstallRoute.NPM
    assert npm.installable is True
    assert npm.source == "@qwen-code/qwen-code"
    assert npm.command_hint == "npm install -g @qwen-code/qwen-code"
    assert npm.reason is None

    manual = describe_agent_cli_install(
        replace(_npm_status(), install_manager="native", package=None)
    )
    assert manual.route is InstallRoute.MANUAL
    assert manual.installable is False
    assert manual.source is None
    assert manual.reason is not None
    assert "https://example.test/qwen" in manual.reason

    bundled = describe_agent_cli_install(
        replace(_npm_status(), install_manager="bundled")
    )
    assert bundled.route is InstallRoute.BUNDLED
    assert bundled.installable is False
    assert bundled.source is None


def test_classifier_ignores_whether_the_cli_is_installed() -> None:
    installed = describe_agent_cli_install(
        _npm_status(executable="/opt/bin/qwen", installed_version="0.8.0")
    )

    assert installed.route is InstallRoute.NPM
    assert installed.installable is True


def test_npm_plan_builds_argv_target_and_path_status(tmp_path: Path) -> None:
    bin_dir = _npm_bin(tmp_path)
    prefix = tmp_path / "npm-global"
    (prefix / "lib" / "node_modules").mkdir(parents=True)
    env = {"PATH": f"{bin_dir}{os.pathsep}{prefix / 'bin'}"}

    entry = plan_agent_cli_install_status(
        _npm_status(),
        env=env,
        run_fn=_npm_probe(str(prefix), str(prefix / "lib" / "node_modules")),
        writable_fn=lambda *_args: True,
    )

    assert entry.route is InstallRoute.NPM
    assert entry.ready is True
    assert entry.argv == ("npm", "install", "-g", "@qwen-code/qwen-code")
    assert entry.install_dir == str(prefix / "bin")
    assert entry.install_dir_on_path is True


def test_npm_plan_marks_an_off_path_target(tmp_path: Path) -> None:
    bin_dir = _npm_bin(tmp_path)
    prefix = tmp_path / "npm-global"
    (prefix / "lib" / "node_modules").mkdir(parents=True)

    entry = plan_agent_cli_install_status(
        _npm_status(),
        env={"PATH": str(bin_dir)},
        run_fn=_npm_probe(str(prefix), str(prefix / "lib" / "node_modules")),
        writable_fn=lambda *_args: True,
    )

    assert entry.ready is True
    assert entry.install_dir_on_path is False


def test_npm_plan_skips_when_npm_is_missing() -> None:
    entry = plan_agent_cli_install_status(
        _npm_status(), env={"PATH": ""}, run_fn=_never_run
    )

    assert entry.ready is False
    assert entry.route is InstallRoute.NPM
    assert entry.skip_reason is not None
    assert "npm is not on PATH" in entry.skip_reason
    assert "Node.js" in entry.skip_reason
    assert "https://example.test/qwen" in entry.skip_reason


def test_npm_plan_skips_when_the_global_root_is_not_writable(
    tmp_path: Path,
) -> None:
    bin_dir = _npm_bin(tmp_path)
    prefix = tmp_path / "npm-global"
    (prefix / "lib" / "node_modules").mkdir(parents=True)

    entry = plan_agent_cli_install_status(
        _npm_status(),
        env={"PATH": str(bin_dir)},
        run_fn=_npm_probe(str(prefix), str(prefix / "lib" / "node_modules")),
        writable_fn=lambda *_args: False,
    )

    assert entry.ready is False
    assert entry.skip_reason is not None
    assert "npm global root is not writable" in entry.skip_reason
    assert "npm install -g @qwen-code/qwen-code" in entry.skip_reason
    assert "never runs sudo" in entry.skip_reason


def test_npm_plan_uses_a_writable_ancestor_for_a_fresh_prefix(
    tmp_path: Path,
) -> None:
    bin_dir = _npm_bin(tmp_path)
    prefix = tmp_path / "fresh"
    prefix.mkdir()
    missing_root = prefix / "lib" / "node_modules"

    entry = plan_agent_cli_install_status(
        _npm_status(),
        env={"PATH": str(bin_dir)},
        run_fn=_npm_probe(str(prefix), str(missing_root)),
        writable_fn=lambda *_args: True,
    )

    assert entry.ready is True
    assert entry.argv == ("npm", "install", "-g", "@qwen-code/qwen-code")
    assert entry.install_dir == os.path.join(str(prefix), "bin")


def test_npm_plan_skips_an_installed_cli_unless_forced(tmp_path: Path) -> None:
    bin_dir = _npm_bin(tmp_path)
    prefix = tmp_path / "npm-global"
    (prefix / "lib" / "node_modules").mkdir(parents=True)
    env = {"PATH": str(bin_dir)}
    run_fn = _npm_probe(str(prefix), str(prefix / "lib" / "node_modules"))
    status = _npm_status(executable="/opt/bin/qwen", installed_version="0.8.0")

    skipped = plan_agent_cli_install_status(
        status, env=env, run_fn=run_fn, writable_fn=lambda *_args: True
    )
    forced = plan_agent_cli_install_status(
        status, force=True, env=env, run_fn=run_fn, writable_fn=lambda *_args: True
    )

    assert skipped.ready is False
    assert skipped.route is InstallRoute.NPM
    assert skipped.skip_reason is not None
    assert "already installed (0.8.0)" in skipped.skip_reason
    assert "--force" in skipped.skip_reason
    assert forced.ready is True
    assert forced.argv == ("npm", "install", "-g", "@qwen-code/qwen-code")


def test_plan_skips_an_installed_cli_unless_forced(tmp_path: Path) -> None:
    status = _status(executable="/opt/bin/muse", installed_version="0.1.0-R708.1")

    skipped = plan_agent_cli_install_status(status, fetch_fn=_fetch(tmp_path))
    forced = plan_agent_cli_install_status(
        status, force=True, fetch_fn=_fetch(tmp_path)
    )

    assert skipped.ready is False
    assert skipped.skip_reason is not None
    assert "already installed (0.1.0-R708.1)" in skipped.skip_reason
    assert "--force" in skipped.skip_reason
    assert forced.ready is True
    assert forced.script is not None


def test_plan_carries_the_declared_env_and_resolved_target(tmp_path: Path) -> None:
    status = _status(install_dir="~/.local/bin", install_dir_env="MUSE_INSTALL_DIR")
    env = {"MUSE_INSTALL_DIR": str(tmp_path / "bin"), "PATH": ""}

    entry = plan_agent_cli_install_status(status, env=env, fetch_fn=_fetch(tmp_path))

    assert entry.argv == ("bash", str(tmp_path / "install.sh"))
    assert entry.env_overlay == (("MUSE_UPGRADE_MODE", "1"),)
    assert entry.install_dir == str(tmp_path / "bin")
    assert entry.install_dir_on_path is False
    assert entry.script is not None
    assert entry.script.digest == SCRIPT_DIGEST


def test_plan_records_a_fetch_failure_instead_of_raising() -> None:
    def failing_fetch(_url: str) -> InstallScript:
        raise AgentCliInstallError("install script URL is not HTTPS: ftp://x")

    entry = plan_agent_cli_install_status(_status(), fetch_fn=failing_fetch)

    assert entry.ready is False
    assert entry.error == "install script URL is not HTTPS: ftp://x"


def test_plan_reports_an_unknown_name_with_suggestions(tmp_path: Path) -> None:
    plan = plan_agent_cli_installs(
        ["mus3"],
        status_fn=lambda **_kwargs: (_status(),),
        fetch_fn=_fetch(tmp_path),
    )

    assert isinstance(plan, AgentCliUnknownName)
    assert plan.query == "mus3"
    assert plan.suggestions == ("muse",)


def test_cleanup_removes_every_fetched_script(tmp_path: Path) -> None:
    plan = plan_agent_cli_installs(
        ["muse"],
        status_fn=lambda **_kwargs: (_status(),),
        fetch_fn=_fetch(tmp_path),
    )
    assert isinstance(plan, AgentCliInstallsPlanned)
    script = plan.entries[0].script
    assert script is not None and script.path.exists()

    plan.cleanup()
    plan.cleanup()

    assert not script.path.exists()
