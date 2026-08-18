"""Resolve and enforce a project's ``plugins.required`` declaration.

A linked or sidecar checkout is not an install. Each PEP 508 entry is checked
against distributions discovered by :mod:`sase.plugins.inventory`, and every
non-``builtin`` ``<plugin>@`` prefix in the project config must appear in the
required list.

Agent and non-interactive callers use :func:`fail_closed_required_plugins`.
That helper never attempts an install: ``sase plugin install`` refuses to run
from a dev-checkout virtualenv and restarts axe on success.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from sase.plugins.inventory import PluginInventory, collect_plugin_inventory
from sase.plugins.qualified_id import (
    BUILTIN_PLUGIN_PREFIX,
    PluginQualifiedIdError,
    parse_plugin_qualified_id,
)
from sase.version._utils import normalize_distribution_name

if TYPE_CHECKING:
    from collections.abc import Callable

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNKNOWN_VERSION = "<unknown>"

_RequiredPluginIssueKind = Literal[
    "invalid",
    "duplicate",
    "missing",
    "version_mismatch",
    "undeclared_prefix",
]


@dataclass(frozen=True)
class _RequiredPluginRequirement:
    """One parsed ``plugins.required`` entry."""

    raw: str
    name: str
    normalized_name: str
    index: int


@dataclass(frozen=True)
class _RequiredPluginUsePrefix:
    """One non-builtin ``<plugin>@`` prefix found in project config."""

    path: str
    plugin: str
    normalized_plugin: str
    spec_id: str


@dataclass(frozen=True)
class _RequiredPluginIssue:
    """One problem found while resolving ``plugins.required``."""

    kind: _RequiredPluginIssueKind
    message: str
    requirement: str | None = None
    config_path: str | None = None
    name: str | None = None
    install_command: str | None = None


@dataclass(frozen=True)
class RequiredPluginsReport:
    """Structured result of resolving ``plugins.required`` against inventory."""

    requirements: tuple[_RequiredPluginRequirement, ...]
    prefixes: tuple[_RequiredPluginUsePrefix, ...]
    satisfied: tuple[_RequiredPluginRequirement, ...]
    issues: tuple[_RequiredPluginIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def missing(self) -> tuple[_RequiredPluginIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "missing")

    @property
    def version_mismatched(self) -> tuple[_RequiredPluginIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "version_mismatch")

    @property
    def config_errors(self) -> tuple[_RequiredPluginIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.kind in {"invalid", "duplicate", "undeclared_prefix"}
        )

    @property
    def installable(self) -> tuple[_RequiredPluginIssue, ...]:
        """Missing or version-mismatched requirements an install can fix."""
        return tuple(
            issue
            for issue in self.issues
            if issue.kind in {"missing", "version_mismatch"}
            and issue.requirement
            and issue.name
            and issue.install_command
        )


class RequiredPluginError(RuntimeError):
    """Raised when required plugins are unsatisfied in a fail-closed context."""

    def __init__(self, report: RequiredPluginsReport) -> None:
        self.report = report
        super().__init__(_fail_closed_required_plugins_text(report))


def _plugin_install_command(name: str) -> str:
    """Return the human-directed install command for a distribution *name*."""
    return f"sase plugin install {name}"


def missing_required_plugin_message(name: str) -> str:
    """Return the hard-error text for a missing required plugin."""
    return (
        f"required plugin `{name}` is not installed; "
        f"run `{_plugin_install_command(name)}`"
    )


_missing_required_plugin_message = missing_required_plugin_message


def _fail_closed_required_plugins_text(report: RequiredPluginsReport) -> str:
    """Render the human-directed fail-closed message for *report*."""
    if report.ok:
        return ""
    return "\n".join(issue.message for issue in report.issues)


def fail_closed_required_plugins(report: RequiredPluginsReport) -> None:
    """Raise :class:`RequiredPluginError` when *report* is unsatisfied.

    Never attempts an install: ``sase plugin install`` refuses to run from a
    dev-checkout virtualenv and restarts axe on success.
    """
    if report.ok:
        return
    raise RequiredPluginError(report)


def _installed_plugin_versions(
    inventory: PluginInventory | None = None,
    *,
    inventory_fn: Callable[..., PluginInventory] = collect_plugin_inventory,
) -> dict[str, str]:
    """Return normalized distribution name to version from *inventory*."""
    if inventory is None:
        inventory = inventory_fn(load_resource_entry_points=False)
    versions: dict[str, str] = {}
    for dist in inventory.distributions:
        key = normalize_distribution_name(dist.package)
        if not key or dist.package == "<unknown>":
            continue
        if not dist.version or dist.version == _UNKNOWN_VERSION:
            continue
        versions.setdefault(key, dist.version)
    return versions


def _iter_plugin_qualified_use_values(
    data: Any, *, path: str = ""
) -> tuple[tuple[str, str, str], ...]:
    """Yield ``(config_path, plugin, id)`` for each valid ``use:`` prefix."""
    found: list[tuple[str, str, str]] = []

    def walk(node: Any, current: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, value in node.items():
                child = _join_config_path(current, raw_key)
                if raw_key == "use" and isinstance(value, str):
                    stripped = value.strip()
                    try:
                        plugin, spec_id = parse_plugin_qualified_id(stripped)
                    except PluginQualifiedIdError:
                        pass
                    else:
                        found.append((child, plugin, spec_id))
                walk(value, child)
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{current}[{index}]")

    walk(data, path)
    return tuple(found)


def resolve_required_plugins(
    config: Mapping[str, Any] | None,
    *,
    installed_versions: Mapping[str, str] | None = None,
    inventory: PluginInventory | None = None,
) -> RequiredPluginsReport:
    """Parse, resolve, and cross-check ``plugins.required`` in *config*."""
    issues: list[_RequiredPluginIssue] = []
    requirements, parse_issues = _parse_required_entries(config)
    issues.extend(parse_issues)
    prefixes = _collect_use_prefixes(config)
    issues.extend(_undeclared_prefix_issues(prefixes, requirements))

    versions = (
        dict(installed_versions)
        if installed_versions is not None
        else _installed_plugin_versions(inventory)
    )
    satisfied: list[_RequiredPluginRequirement] = []
    for requirement in requirements:
        parsed = _requirement_or_none(requirement.raw)
        if parsed is None:
            continue
        if parsed.marker is not None and not parsed.marker.evaluate():
            satisfied.append(requirement)
            continue
        installed = versions.get(requirement.normalized_name)
        if installed is None:
            issues.append(
                _RequiredPluginIssue(
                    kind="missing",
                    message=_missing_required_plugin_message(requirement.name),
                    requirement=requirement.raw,
                    name=requirement.name,
                    install_command=_plugin_install_command(requirement.name),
                )
            )
            continue
        if parsed.specifier:
            if not _specifier_contains(parsed, installed):
                issues.append(
                    _RequiredPluginIssue(
                        kind="version_mismatch",
                        message=(
                            f"required plugin `{requirement.raw}` is installed "
                            f"as {installed}; run "
                            f"`{_plugin_install_command(requirement.name)}`"
                        ),
                        requirement=requirement.raw,
                        name=requirement.name,
                        install_command=_plugin_install_command(requirement.name),
                    )
                )
                continue
        satisfied.append(requirement)

    return RequiredPluginsReport(
        requirements=requirements,
        prefixes=prefixes,
        satisfied=tuple(satisfied),
        issues=tuple(issues),
    )


def required_plugin_blockers(
    config: Mapping[str, Any] | None,
    *,
    command_label: str = "init memory",
    installed_versions: Mapping[str, str] | None = None,
    inventory: PluginInventory | None = None,
) -> tuple[str, ...]:
    """Return hard-error lines for memory init / validate, or empty."""
    report = resolve_required_plugins(
        config,
        installed_versions=installed_versions,
        inventory=inventory,
    )
    try:
        fail_closed_required_plugins(report)
    except RequiredPluginError as exc:
        return tuple(
            f"{command_label}: {line}" for line in str(exc).splitlines() if line
        )
    return ()


def _parse_required_entries(
    config: Mapping[str, Any] | None,
) -> tuple[tuple[_RequiredPluginRequirement, ...], tuple[_RequiredPluginIssue, ...]]:
    if not isinstance(config, Mapping) or "plugins" not in config:
        return (), ()
    plugins = config.get("plugins")
    if plugins is None:
        return (), ()
    if not isinstance(plugins, Mapping):
        return (
            (),
            (
                _RequiredPluginIssue(
                    kind="invalid",
                    message="plugins must be a mapping",
                    config_path="plugins",
                ),
            ),
        )
    if "required" not in plugins:
        return (), ()
    raw_required = plugins.get("required")
    if raw_required is None:
        return (), ()
    if not isinstance(raw_required, list):
        return (
            (),
            (
                _RequiredPluginIssue(
                    kind="invalid",
                    message="plugins.required must be a list of PEP 508 requirement strings",
                    config_path="plugins.required",
                ),
            ),
        )

    requirements: list[_RequiredPluginRequirement] = []
    issues: list[_RequiredPluginIssue] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(raw_required):
        path = f"plugins.required[{index}]"
        if not isinstance(item, str) or not item.strip():
            issues.append(
                _RequiredPluginIssue(
                    kind="invalid",
                    message=(f"{path}: {item!r} is not a valid PEP 508 requirement"),
                    config_path=path,
                    requirement=item if isinstance(item, str) else None,
                )
            )
            continue
        raw = item.strip()
        try:
            parsed = Requirement(raw)
        except InvalidRequirement as exc:
            issues.append(
                _RequiredPluginIssue(
                    kind="invalid",
                    message=f"{path}: {raw!r} is not a valid PEP 508 requirement: {exc}",
                    config_path=path,
                    requirement=raw,
                )
            )
            continue
        normalized = normalize_distribution_name(parsed.name)
        if normalized in seen:
            issues.append(
                _RequiredPluginIssue(
                    kind="duplicate",
                    message=(
                        f"{path}: duplicated distribution name "
                        f"{parsed.name!r} (also listed at "
                        f"plugins.required[{seen[normalized]}])"
                    ),
                    config_path=path,
                    requirement=raw,
                    name=parsed.name,
                )
            )
            continue
        seen[normalized] = index
        requirements.append(
            _RequiredPluginRequirement(
                raw=raw,
                name=parsed.name,
                normalized_name=normalized,
                index=index,
            )
        )
    return tuple(requirements), tuple(issues)


def _collect_use_prefixes(
    config: Mapping[str, Any] | None,
) -> tuple[_RequiredPluginUsePrefix, ...]:
    if not isinstance(config, Mapping):
        return ()
    prefixes: list[_RequiredPluginUsePrefix] = []
    for path, plugin, spec_id in _iter_plugin_qualified_use_values(config):
        if plugin.casefold() == BUILTIN_PLUGIN_PREFIX:
            continue
        prefixes.append(
            _RequiredPluginUsePrefix(
                path=path,
                plugin=plugin,
                normalized_plugin=normalize_distribution_name(plugin),
                spec_id=spec_id,
            )
        )
    return tuple(prefixes)


def _undeclared_prefix_issues(
    prefixes: tuple[_RequiredPluginUsePrefix, ...],
    requirements: tuple[_RequiredPluginRequirement, ...],
) -> tuple[_RequiredPluginIssue, ...]:
    required_names = {item.normalized_name for item in requirements}
    issues: list[_RequiredPluginIssue] = []
    seen: set[tuple[str, str]] = set()
    for prefix in prefixes:
        key = (prefix.path, prefix.normalized_plugin)
        if key in seen:
            continue
        seen.add(key)
        if prefix.normalized_plugin in required_names:
            continue
        issues.append(
            _RequiredPluginIssue(
                kind="undeclared_prefix",
                message=(
                    f"{prefix.path}: plugin {prefix.plugin!r} is not listed in "
                    f"plugins.required; add {prefix.plugin!r}"
                ),
                config_path=prefix.path,
                name=prefix.plugin,
                requirement=prefix.plugin,
                install_command=_plugin_install_command(prefix.plugin),
            )
        )
    return tuple(issues)


def _requirement_or_none(raw: str) -> Requirement | None:
    try:
        return Requirement(raw)
    except InvalidRequirement:
        return None


def _specifier_contains(parsed: Requirement, installed: str) -> bool:
    try:
        Version(installed)
    except InvalidVersion:
        return False
    return parsed.specifier.contains(installed, prereleases=True)


def _join_config_path(parent: str, key: object) -> str:
    text = str(key)
    if not parent:
        return text
    if _IDENTIFIER_RE.fullmatch(text):
        return f"{parent}.{text}"
    return f"{parent}[{text!r}]"


def load_project_required_plugins_config(
    root: Path,
) -> tuple[Mapping[str, Any] | None, Path | None, str | None]:
    """Load the project-local config used for ``plugins.required``.

    Returns ``(config, path, error)``. ``config`` is ``None`` when *root* is
    not inside a project. A missing config file yields an empty mapping.
    """
    from sase.content_layout import (
        LayoutCollisionError,
        discover_project_root,
        resolve_project_config_read_path,
    )
    from sase.project_management import load_local_config

    project_root = discover_project_root(root)
    if project_root is None:
        return None, None, None
    try:
        path = resolve_project_config_read_path(project_root)
    except LayoutCollisionError as exc:
        return None, None, str(exc)
    if path is None or not path.is_file():
        return {}, path, None
    loaded = load_local_config(path)
    if not loaded.valid:
        return None, path, loaded.error
    return loaded.config, path, None


__all__ = [
    "RequiredPluginError",
    "RequiredPluginsReport",
    "fail_closed_required_plugins",
    "load_project_required_plugins_config",
    "missing_required_plugin_message",
    "required_plugin_blockers",
    "resolve_required_plugins",
]
