"""Provider-CLI resolution, version probing, and install-method detection."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.llm_provider import registry as llm_registry

from .models import AgentCliStatus, EnvOverlay, InstallMethod, VersionCompare
from .runner import (
    PROBE_TIMEOUT_SECONDS,
    AgentCliRunnerError,
    CommandResult,
    run_command,
)

RunnerFn = Callable[..., CommandResult]
WritableFn = Callable[[str, int], bool]
WhichFn = Callable[..., str | None]

_SEMVER_RE = re.compile(
    r"(?<![0-9A-Za-z])v?(?P<version>\d+\.\d+\.\d+"
    r"(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?)"
)
_BREW_PREFIXES = (
    Path("/opt/homebrew"),
    Path("/usr/local/Cellar"),
    Path("/home/linuxbrew/.linuxbrew"),
)


@dataclass(frozen=True)
class _VersionProbe:
    version: str | None
    error: str | None = None


@dataclass(frozen=True)
class _NpmEnvironment:
    root: str | None
    prefix: str | None
    installed_packages: frozenset[str]
    root_writable: bool | None


def _resolve_provider_executable(
    provider_name: str,
    cli_name: str | None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve a provider CLI, honoring its ``SASE_<PROVIDER>_PATH`` override."""
    environment = os.environ if env is None else env
    override = _optional_str(
        environment.get(llm_registry.provider_path_env_var(provider_name))
    )
    return resolve_executable(override or cli_name, env=environment)


def resolve_executable(
    command: str | None,
    *,
    env: Mapping[str, str] | None = None,
    which_fn: WhichFn | None = None,
) -> str | None:
    """Resolve a command name or explicit executable path."""
    if not command:
        return None
    expanded = os.path.expanduser(command)
    path = (os.environ if env is None else env).get("PATH")
    resolved = (
        shutil.which(expanded, path=path) if which_fn is None else which_fn(expanded)
    )
    if resolved:
        return resolved
    if os.sep in expanded:
        candidate = Path(expanded)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _parse_version(output: str, version_regex: str | None = None) -> str | None:
    """Parse the first semantic version, or a provider-declared regex match."""
    pattern = _compile_version_regex(version_regex)
    match = pattern.search(output)
    if match is None:
        return None
    if "version" in match.groupdict():
        value = match.group("version")
    elif match.lastindex:
        value = match.group(1)
    else:
        value = match.group(0)
    return value.removeprefix("v") if value else None


def probe_version(
    executable: str,
    *,
    version_argv: Sequence[str] = ("--version",),
    version_regex: str | None = None,
    run_fn: RunnerFn = run_command,
) -> _VersionProbe:
    argv = (executable, *version_argv)
    try:
        result = run_fn(argv, timeout=PROBE_TIMEOUT_SECONDS)
    except AgentCliRunnerError as exc:
        return _VersionProbe(None, str(exc))
    if result.returncode != 0:
        detail = _first_output_line(result) or f"exited {result.returncode}"
        return _VersionProbe(None, detail)
    version = _parse_version(result.output, version_regex)
    if version is None:
        return _VersionProbe(
            None, "version output did not contain a recognized version"
        )
    return _VersionProbe(version)


def _probe_npm_environment(
    packages: Sequence[str],
    *,
    run_fn: RunnerFn = run_command,
    writable_fn: WritableFn = os.access,
) -> _NpmEnvironment:
    """Probe npm root/prefix and declared packages once for one detection run."""
    root = _probe_single_line(("npm", "root", "-g"), run_fn=run_fn)
    prefix = _probe_single_line(("npm", "prefix", "-g"), run_fn=run_fn)
    installed: set[str] = set()
    unique_packages = tuple(dict.fromkeys(package for package in packages if package))
    if unique_packages:
        try:
            result = run_fn(
                ("npm", "ls", "-g", "--json", *unique_packages),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except AgentCliRunnerError:
            result = None
        if result is not None:
            try:
                payload = json.loads(result.stdout)
            except (TypeError, ValueError):
                payload = {}
            dependencies = (
                payload.get("dependencies") if isinstance(payload, dict) else {}
            )
            if isinstance(dependencies, dict):
                installed.update(
                    package for package in unique_packages if package in dependencies
                )
    writable_path = root or prefix
    root_writable = (
        writable_fn(writable_path, os.W_OK) if writable_path is not None else None
    )
    return _NpmEnvironment(root, prefix, frozenset(installed), root_writable)


def _detect_install_method(
    executable: str | None,
    *,
    manager: str | None,
    package: str | None,
    self_update_argv: Sequence[str] = (),
    npm: _NpmEnvironment | None = None,
    brew_prefixes: Sequence[Path] = _BREW_PREFIXES,
) -> InstallMethod:
    """Classify an install using conservative, precedence-ordered evidence."""
    if manager == "bundled":
        return InstallMethod.BUNDLED
    if executable is None:
        return InstallMethod.NOT_INSTALLED
    if (
        package
        and npm is not None
        and (
            _path_under(executable, npm.root)
            or _path_under(executable, npm.prefix)
            or (
                package in npm.installed_packages
                and npm.root is None
                and npm.prefix is None
            )
        )
    ):
        return InstallMethod.NPM
    if _is_homebrew_path(executable, brew_prefixes):
        return InstallMethod.HOMEBREW
    if self_update_argv:
        return InstallMethod.SELF_MANAGED
    return InstallMethod.UNKNOWN


def detect_agent_cli_statuses(
    providers: Mapping[str, Mapping[str, Any]],
    *,
    env: Mapping[str, str] | None = None,
    run_fn: RunnerFn = run_command,
    writable_fn: WritableFn = os.access,
) -> tuple[AgentCliStatus, ...]:
    """Detect all registered provider CLIs without any network access."""
    environment = os.environ if env is None else env
    records: list[
        tuple[str, Mapping[str, Any], Mapping[str, Any], str, str | None]
    ] = []
    npm_packages: list[str] = []
    for name, metadata in sorted(providers.items()):
        binary = _optional_str(metadata.get("autodetect_cli_name"))
        if binary is None:
            continue
        install = metadata.get("install")
        install_metadata = install if isinstance(install, Mapping) else {}
        executable = _resolve_provider_executable(name, binary, env=environment)
        records.append((name, metadata, install_metadata, binary, executable))
        package = _optional_str(install_metadata.get("package"))
        if executable and package:
            npm_packages.append(package)

    npm = (
        _probe_npm_environment(npm_packages, run_fn=run_fn, writable_fn=writable_fn)
        if npm_packages
        else _NpmEnvironment(None, None, frozenset(), None)
    )
    statuses: list[AgentCliStatus] = []
    for name, _metadata, install, binary, executable in records:
        manager = _optional_str(install.get("manager"))
        package = _optional_str(install.get("package"))
        display_name = _optional_str(install.get("display_name")) or name
        docs_url = _optional_str(install.get("docs_url"))
        self_update_argv = _string_tuple(install.get("self_update_argv"))
        version_argv = _string_tuple(install.get("version_argv")) or ("--version",)
        version_regex = _optional_str(install.get("version_regex"))
        method = _detect_install_method(
            executable,
            manager=manager,
            package=package,
            self_update_argv=self_update_argv,
            npm=npm,
        )
        if executable is not None and method is not InstallMethod.BUNDLED:
            version = probe_version(
                executable,
                version_argv=version_argv,
                version_regex=version_regex,
                run_fn=run_fn,
            )
        else:
            version = _VersionProbe(None)
        statuses.append(
            AgentCliStatus(
                name=name,
                display_name=display_name,
                binary=binary,
                executable=executable,
                installed_version=version.version,
                latest_version=None,
                install_method=method,
                update_available=False,
                docs_url=docs_url,
                install_hint=_install_hint(
                    name,
                    display_name,
                    manager=manager,
                    package=package,
                    docs_url=docs_url,
                ),
                package=package,
                latest_version_package=_optional_str(
                    install.get("latest_version_package")
                ),
                self_update_argv=self_update_argv,
                version_argv=version_argv,
                version_regex=version_regex,
                brew_package=_optional_str(install.get("brew_package")),
                npm_root_writable=(
                    npm.root_writable if method is InstallMethod.NPM else None
                ),
                version_error=version.error,
                install_manager=manager,
                install_script_url=_optional_str(install.get("install_script_url")),
                install_dir=_optional_str(install.get("install_dir")),
                install_dir_env=_optional_str(install.get("install_dir_env")),
                install_env=_string_map(install.get("install_env")),
                self_update_env=_string_map(install.get("self_update_env")),
                latest_version_url=_optional_str(install.get("latest_version_url")),
                latest_version_json_field=_optional_str(
                    install.get("latest_version_json_field")
                ),
                version_compare=_version_compare(install.get("version_compare")),
            )
        )
    return tuple(statuses)


def _probe_single_line(argv: tuple[str, ...], *, run_fn: RunnerFn) -> str | None:
    try:
        result = run_fn(argv, timeout=PROBE_TIMEOUT_SECONDS)
    except AgentCliRunnerError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if stripped := line.strip():
            return stripped
    return None


def _compile_version_regex(version_regex: str | None) -> re.Pattern[str]:
    if not version_regex:
        return _SEMVER_RE
    try:
        return re.compile(version_regex)
    except re.error:
        return _SEMVER_RE


def _path_under(executable: str, root: str | None) -> bool:
    if not root:
        return False
    root_path = Path(root).expanduser()
    executable_path = Path(executable).expanduser()
    candidates = (executable_path, executable_path.resolve(strict=False))
    roots = (root_path, root_path.resolve(strict=False))
    return any(
        candidate.is_relative_to(parent) for candidate in candidates for parent in roots
    )


def _is_homebrew_path(executable: str, prefixes: Sequence[Path]) -> bool:
    path = Path(executable).expanduser()
    candidates = (path, path.resolve(strict=False))
    if any(
        candidate.is_relative_to(prefix)
        for candidate in candidates
        for prefix in prefixes
    ):
        return True
    normalized = str(path).replace("\\", "/")
    return "/Cellar/" in normalized or "/homebrew/" in normalized


def _install_hint(
    name: str,
    display_name: str,
    *,
    manager: str | None,
    package: str | None,
    docs_url: str | None,
) -> str:
    if manager == "bundled":
        return "bundled with SASE — nothing to install"
    if manager == "npm" and package:
        return f"npm install -g {package}"
    if manager == InstallMethod.SCRIPT:
        return f"run `sase agent-cli install {name}`"
    if docs_url:
        return f"install from {docs_url}"
    return f"install the {display_name} CLI"


def _first_output_line(result: CommandResult) -> str | None:
    for text in (result.stderr, result.stdout):
        for line in text.splitlines():
            if stripped := line.strip():
                return stripped
    return None


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _string_map(value: Any) -> EnvOverlay:
    """Normalize a provider-declared env dict into sorted string pairs."""
    if not isinstance(value, Mapping):
        return ()
    pairs = {
        key.strip(): str(item)
        for key, item in value.items()
        if isinstance(key, str) and key.strip()
    }
    return tuple(sorted(pairs.items()))


def _version_compare(value: Any) -> VersionCompare:
    """Select a declared comparator, defaulting to today's PEP 440 rules."""
    if isinstance(value, str) and value.strip() == VersionCompare.EXACT:
        return VersionCompare.EXACT
    return VersionCompare.PEP440


__all__ = [
    "detect_agent_cli_statuses",
    "probe_version",
    "resolve_executable",
]
