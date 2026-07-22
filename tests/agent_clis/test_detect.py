from __future__ import annotations

import json
from pathlib import Path

from sase.agent_clis.detect import (
    _NpmEnvironment,
    _detect_install_method,
    _parse_version,
    _probe_npm_environment,
    detect_agent_cli_statuses,
)
from sase.agent_clis.models import InstallMethod
from sase.agent_clis.runner import CommandResult


def _result(argv: tuple[str, ...], stdout: str, returncode: int = 0) -> CommandResult:
    return CommandResult(argv, returncode, stdout=stdout)


def test_parse_version_uses_semver_and_provider_override() -> None:
    assert _parse_version("codex-cli 1.2.3") == "1.2.3"
    assert _parse_version("build=release_42", r"release_(?P<version>\d+)") == "42"
    assert _parse_version("no version here") is None


def test_npm_evidence_beats_self_update_strategy() -> None:
    npm = _NpmEnvironment(
        root="/prefix/lib/node_modules",
        prefix="/prefix",
        installed_packages=frozenset({"tool-package"}),
        root_writable=True,
    )

    method = _detect_install_method(
        "/prefix/bin/tool",
        manager="npm",
        package="tool-package",
        self_update_argv=("update",),
        npm=npm,
    )

    assert method is InstallMethod.NPM


def test_orphaned_npm_package_does_not_mask_self_managed_install() -> None:
    npm = _NpmEnvironment(
        root="/prefix/lib/node_modules",
        prefix="/prefix",
        installed_packages=frozenset({"tool-package"}),
        root_writable=True,
    )

    method = _detect_install_method(
        "/other/tool",
        manager="npm",
        package="tool-package",
        self_update_argv=("update",),
        npm=npm,
    )

    assert method is InstallMethod.SELF_MANAGED


def test_listed_npm_package_is_evidence_when_tree_location_is_unknown() -> None:
    npm = _NpmEnvironment(
        root=None,
        prefix=None,
        installed_packages=frozenset({"tool-package"}),
        root_writable=None,
    )

    method = _detect_install_method(
        "/other/tool",
        manager="npm",
        package="tool-package",
        self_update_argv=("update",),
        npm=npm,
    )

    assert method is InstallMethod.NPM


def test_unknown_install_never_becomes_self_managed_without_declared_command() -> None:
    assert (
        _detect_install_method(
            "/opt/vendor/tool", manager=None, package=None, self_update_argv=()
        )
        is InstallMethod.UNKNOWN
    )


def test_probe_npm_environment_runs_root_prefix_and_one_package_query() -> None:
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        calls.append(argv)
        if argv[1:3] == ("root", "-g"):
            return _result(argv, "/npm/root\n")
        if argv[1:3] == ("prefix", "-g"):
            return _result(argv, "/npm\n")
        return _result(
            argv,
            json.dumps({"dependencies": {"one": {"version": "1.0.0"}}}),
        )

    npm = _probe_npm_environment(
        ["one", "two", "one"], run_fn=run, writable_fn=lambda *_: False
    )

    assert calls == [
        ("npm", "root", "-g"),
        ("npm", "prefix", "-g"),
        ("npm", "ls", "-g", "--json", "one", "two"),
    ]
    assert npm.installed_packages == frozenset({"one"})
    assert npm.root_writable is False


def test_detection_honors_provider_path_override_and_parses_version(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "special-tool"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    providers = {
        "special": {
            "autodetect_cli_name": "tool",
            "install": {
                "manager": "native",
                "display_name": "Special Tool",
                "docs_url": "https://example.test/docs",
                "self_update_argv": ["update"],
            },
        }
    }

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        if argv[0] == "npm":
            return _result(argv, "", returncode=1)
        return _result(argv, "Special Tool v3.4.5")

    statuses = detect_agent_cli_statuses(
        providers,
        env={"SASE_SPECIAL_PATH": str(executable), "PATH": ""},
        run_fn=run,
    )

    assert len(statuses) == 1
    status = statuses[0]
    assert status.executable == str(executable)
    assert status.installed_version == "3.4.5"
    assert status.install_method is InstallMethod.SELF_MANAGED


def test_detection_ignores_orphaned_npm_package_for_native_executable(
    tmp_path: Path,
) -> None:
    native_bin = tmp_path / "native" / "bin"
    native_bin.mkdir(parents=True)
    executable = native_bin / "claude"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    npm_prefix = tmp_path / "npm"
    npm_root = npm_prefix / "lib" / "node_modules"
    providers = {
        "claude": {
            "autodetect_cli_name": "claude",
            "install": {
                "manager": "npm",
                "package": "@anthropic-ai/claude-code",
                "self_update_argv": ["update"],
            },
        }
    }

    def run(argv: tuple[str, ...], **_kwargs: object) -> CommandResult:
        if argv[1:3] == ("root", "-g"):
            return _result(argv, f"{npm_root}\n")
        if argv[1:3] == ("prefix", "-g"):
            return _result(argv, f"{npm_prefix}\n")
        if argv[:4] == ("npm", "ls", "-g", "--json"):
            return _result(
                argv,
                json.dumps(
                    {
                        "dependencies": {
                            "@anthropic-ai/claude-code": {"version": "1.0.0"}
                        }
                    }
                ),
            )
        return _result(argv, "Claude Code v2.0.0")

    statuses = detect_agent_cli_statuses(
        providers,
        env={"PATH": str(native_bin)},
        run_fn=run,
    )

    assert statuses[0].executable == str(executable)
    assert statuses[0].install_method is InstallMethod.SELF_MANAGED


def test_not_installed_provider_does_not_probe_npm() -> None:
    providers = {
        "missing": {
            "autodetect_cli_name": "missing-cli",
            "install": {"manager": "npm", "package": "missing-package"},
        }
    }

    statuses = detect_agent_cli_statuses(
        providers,
        env={"PATH": ""},
        run_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not invoke a subprocess")
        ),
    )

    assert statuses[0].install_method is InstallMethod.NOT_INSTALLED
