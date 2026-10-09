#!/usr/bin/env python3
"""Desired-state planning for the ``sase_install`` engine (stdlib-only).

The receipt decides *which* plugins are installed; the mode decides *where*
each one comes from. This module turns an :class:`InstallState` snapshot plus
CLI options into an :class:`InstallPlan`: per-package rows with a change kind,
a consequential flag, the parity-checked swap argv, and the overrides content.
It performs no side effects beyond PyPI metadata reads through an injected
lookup (tests pass fakes; only the entry point wires the network client).
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import _sase_install_env as install_env
import _sase_install_pypi as install_pypi
import _sase_install_state as install_state


HOST_DIST_NAME = "sase"
CORE_DIST_NAME = "sase-core-rs"

COMMAND_PYPI = "just install"
COMMAND_DEV = "just install-dev"

#: Per-package change kinds (the full set the engine renders).
CHANGE_KEEP = "keep"
CHANGE_ADD = "add"
CHANGE_UPGRADE = "upgrade"
CHANGE_DOWNGRADE = "downgrade"
CHANGE_TO_EDITABLE = "to-editable"
CHANGE_TO_PYPI = "to-pypi"
CHANGE_RETARGET = "retarget"
CHANGE_REMOVE = "remove"

_CONSEQUENTIAL_KINDS = frozenset(
    {
        CHANGE_DOWNGRADE,
        CHANGE_TO_EDITABLE,
        CHANGE_TO_PYPI,
        CHANGE_RETARGET,
        CHANGE_REMOVE,
    }
)


@dataclass(frozen=True)
class PlanOptions:
    """CLI-level choices that shape the desired package set."""

    mode: str = "pypi"
    with_specs: tuple[str, ...] = ()
    python: str | None = None
    force: bool = False
    version: str | None = None
    keep_plugin_sources: bool = False
    sync: bool = False


@dataclass(frozen=True)
class CurrentSource:
    """Where a package comes from today."""

    kind: str
    version: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class TargetSource:
    """Where a package should come from after the install."""

    kind: str
    version: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class PlanRow:
    """One package row of the install plan."""

    name: str
    role: str
    current: CurrentSource
    target: TargetSource
    kind: str
    consequential: bool
    note: str = ""


@dataclass(frozen=True)
class PythonPlan:
    """The interpreter row: the existing env is kept unless asked."""

    current: str | None
    target: str | None
    requested: bool = False
    change: bool = False


@dataclass(frozen=True)
class InstallPlan:
    """The full read-only install plan (no side effects were performed)."""

    mode: str
    command: str
    rows: tuple[PlanRow, ...]
    python: PythonPlan
    target_dir: str
    current_mode: str
    consequential: bool
    noop: bool
    warnings: tuple[str, ...]
    swap_argv: tuple[str, ...]
    overrides_lines: tuple[str, ...]
    overrides_path: str | None
    checkout_root: str
    core_dir: str
    sync_requested: bool = False
    fresh: bool = False
    force_foreign_env: bool = False


@dataclass(frozen=True)
class DesiredPlugin:
    """One plugin entry of the post-install set, with its display version."""

    requirement: install_state.InstallRequirement
    display_version: str | None


def _normalize(name: str) -> str:
    return install_state.normalize_distribution_name(name)


def dedupe_requirements(
    requirements: Sequence[install_state.InstallRequirement],
) -> tuple[tuple[install_state.InstallRequirement, ...], tuple[str, ...]]:
    """Dedupe receipt entries by normalized name (first occurrence wins)."""
    kept: dict[str, install_state.InstallRequirement] = {}
    order: list[str] = []
    warnings: list[str] = []
    for req in requirements:
        key = req.normalized_name
        existing = kept.get(key)
        if existing is None:
            kept[key] = req
            order.append(key)
        elif existing != req:
            warnings.append(
                f"plugin '{req.name}' appears multiple times in the uv receipt "
                f"with conflicting sources; keeping {existing.describe()} and "
                f"ignoring {req.describe()}."
            )
    return tuple(kept[key] for key in order), tuple(warnings)


def build_swap_argv(
    primary: install_state.InstallRequirement,
    plugins: Sequence[install_state.InstallRequirement],
    *,
    overrides: str | None = None,
) -> list[str]:
    """Build the ``uv tool install --force --reinstall`` argv for a package set.

    Mirrors ``sase.uv_tool.commands.build_reinstall_set(primary, plugins,
    color="never", overrides=...)`` exactly; parity is enforced by tests.
    """
    argv = ["uv", "tool", "install", "--color", "never", "--force", "--reinstall"]
    argv += primary.primary_args()
    for plugin in plugins:
        argv += plugin.with_args()
    if overrides is not None:
        argv += ["--overrides", overrides]
    return argv


def editable_override_lines(
    requirements: Sequence[install_state.InstallRequirement],
) -> tuple[str, ...]:
    """Return uv override lines for editable requirements.

    Mirrors ``sase.uv_tool.overrides.editable_override_lines``: one ``-e
    <path>`` line per normalized distribution name (first editable wins), plus
    a bare ``sase-core-rs`` line when the host itself is editable.
    """
    host_key = _normalize(HOST_DIST_NAME)
    seen: set[str] = set()
    lines: list[str] = []
    host_editable = False
    for requirement in requirements:
        if requirement.editable is None:
            continue
        key = requirement.normalized_name
        if key == host_key:
            host_editable = True
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"-e {requirement.editable}")
    if host_editable:
        lines.append(CORE_DIST_NAME)
    return tuple(lines)


def read_checkout_version(checkout_root: str | Path) -> str | None:
    """Return the checkout's static ``[project].version``, if declared."""
    try:
        data = tomllib.loads(
            (Path(checkout_root) / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return version if isinstance(version, str) and version else None


def resolve_sibling(
    checkout_root: str | Path,
    dist_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the durable ``<checkout>/../<dist-name>`` checkout, if suitable."""
    candidate = Path(checkout_root).parent / dist_name
    if not candidate.is_dir():
        return None
    if install_env.is_ephemeral_path(candidate, env=env):
        return None
    try:
        data = tomllib.loads(
            (candidate / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    declared = project.get("name")
    if not isinstance(declared, str) or _normalize(declared) != _normalize(dist_name):
        return None
    return candidate


def _same_path(left: str | None, right: str | Path | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return False


def _current_from_state(
    state: install_state.InstallState,
    req: install_state.InstallRequirement | None,
    dist_name: str,
    *,
    core_local: bool = False,
) -> CurrentSource:
    dist = state.find_dist(dist_name)
    editable = (dist.editable_path if dist is not None else None) or (
        req.editable if req is not None else None
    )
    if editable:
        version = dist.version if dist is not None else None
        return CurrentSource(kind="editable", version=version, path=editable)
    if req is not None and req.git is not None:
        return CurrentSource(kind="other", version=None, path=req.git)
    if req is not None and req.url is not None:
        return CurrentSource(kind="other", version=None, path=req.url)
    if dist is not None:
        kind = "local" if core_local else "pypi"
        return CurrentSource(kind=kind, version=dist.version)
    if req is not None and req.specifier:
        return CurrentSource(kind="pypi", version=None)
    return CurrentSource(kind="missing")


def _index_kind(current_version: str | None, target_version: str | None) -> str:
    if current_version and target_version:
        comparison = install_pypi.compare_versions(current_version, target_version)
        if comparison < 0:
            return CHANGE_UPGRADE
        if comparison > 0:
            return CHANGE_DOWNGRADE
    return CHANGE_KEEP


def _consequential(kind: str) -> bool:
    return kind in _CONSEQUENTIAL_KINDS


def _resolve_dev_plugin(
    *,
    state: install_state.InstallState,
    req: install_state.InstallRequirement | None,
    name: str,
    checkout_root: Path,
    keep_sources: bool,
    pinned_version: str | None,
    pypi_lookup: Callable[[str], install_pypi.PypiInfo],
    warnings: list[str],
    env: Mapping[str, str] | None,
) -> tuple[DesiredPlugin, CurrentSource, str, str]:
    """Resolve one dev-mode plugin target.

    Returns ``(desired, current, note, kind)``. The source policy is: the
    current editable path when it is durable, else a durable sibling
    ``<checkout>/../<name>`` checkout, else PyPI.
    """
    current = _current_from_state(state, req, name)
    if (
        current.kind == "editable"
        and current.path is not None
        and not install_env.is_ephemeral_path(current.path, env=env)
        and Path(current.path).exists()
    ):
        desired = DesiredPlugin(
            install_state.InstallRequirement(name=name, editable=current.path),
            current.version,
        )
        note = "kept source" if keep_sources else "editable checkout"
        return desired, current, note, CHANGE_KEEP
    if keep_sources and current.kind in ("pypi", "other"):
        kept_req = req or install_state.InstallRequirement(name=name)
        desired = DesiredPlugin(kept_req, current.version)
        return desired, current, "kept source", CHANGE_KEEP
    if current.kind == "editable" and current.path is not None:
        warnings.append(
            f"plugin '{name}' currently installs from an ephemeral or missing "
            f"checkout ({current.path}); resolving a durable source instead."
        )
    sibling = resolve_sibling(checkout_root, name, env=env)
    if sibling is not None:
        desired = DesiredPlugin(
            install_state.InstallRequirement(name=name, editable=str(sibling)),
            current.version,
        )
        if current.kind == "missing":
            return desired, current, "durable sibling checkout", CHANGE_ADD
        if current.kind == "editable":
            return desired, current, "durable sibling checkout", CHANGE_RETARGET
        return desired, current, "durable sibling checkout", CHANGE_TO_EDITABLE
    info = pypi_lookup(name)
    if info.warning is not None:
        warnings.append(info.warning)
    if pinned_version is not None:
        desired_req = install_state.InstallRequirement(
            name=name, specifier=f"=={pinned_version}"
        )
        desired = DesiredPlugin(desired_req, pinned_version)
    else:
        desired = DesiredPlugin(
            install_state.InstallRequirement(name=name), info.version
        )
    if current.kind == "missing":
        return desired, current, "PyPI", CHANGE_ADD
    if current.kind == "editable":
        return desired, current, "PyPI", CHANGE_TO_PYPI
    return desired, current, "PyPI", _index_kind(current.version, info.version)


def _resolve_pypi_plugin(
    *,
    state: install_state.InstallState,
    req: install_state.InstallRequirement | None,
    name: str,
    keep_sources: bool,
    pinned_version: str | None,
    pypi_lookup: Callable[[str], install_pypi.PypiInfo],
    warnings: list[str],
    env: Mapping[str, str] | None,
) -> tuple[DesiredPlugin, CurrentSource, str, str]:
    """Resolve one PyPI-mode plugin target; returns ``(desired, current, note, kind)``."""
    current = _current_from_state(state, req, name)
    info = pypi_lookup(name)
    if info.warning is not None:
        warnings.append(info.warning)
    if info.published is False:
        # Not on PyPI (for example bugyi-chops): stay editable with a note.
        if current.kind == "editable" and current.path is not None:
            desired = DesiredPlugin(
                install_state.InstallRequirement(name=name, editable=current.path),
                current.version,
            )
            return desired, current, "stays editable \u00b7 not on PyPI", CHANGE_KEEP
        warnings.append(
            f"plugin '{name}' is not published on PyPI and has no editable "
            "source; it will be removed."
        )
        desired = DesiredPlugin(
            install_state.InstallRequirement(name=name), current.version
        )
        return desired, current, "not on PyPI \u00b7 no source", CHANGE_REMOVE
    if info.published is None:
        # Offline: never flip a source we cannot verify; keep what is there.
        kept_req = req or install_state.InstallRequirement(name=name)
        desired = DesiredPlugin(kept_req, current.version)
        return desired, current, "PyPI unreachable \u00b7 keeping source", CHANGE_KEEP
    if keep_sources and current.kind == "editable" and current.path is not None:
        if install_env.is_ephemeral_path(
            current.path, env=env
        ) or not Path(current.path).exists():
            warnings.append(
                f"plugin '{name}' kept source is ephemeral or missing "
                f"({current.path}); moving it to PyPI."
            )
        else:
            desired = DesiredPlugin(
                install_state.InstallRequirement(name=name, editable=current.path),
                current.version,
            )
            return desired, current, "kept source", CHANGE_KEEP
    target_version = pinned_version or info.version
    if pinned_version is not None:
        desired_req = install_state.InstallRequirement(
            name=name, specifier=f"=={pinned_version}"
        )
    else:
        desired_req = install_state.InstallRequirement(name=name)
    desired = DesiredPlugin(desired_req, target_version)
    if current.kind == "editable":
        return desired, current, "PyPI", CHANGE_TO_PYPI
    if current.kind == "missing":
        return desired, current, "PyPI", CHANGE_ADD
    if current.kind == "other":
        return desired, current, "PyPI", CHANGE_TO_PYPI
    return desired, current, "PyPI", _index_kind(current.version, target_version)


def build_plan(
    *,
    options: PlanOptions,
    state: install_state.InstallState,
    checkout_root: str | Path,
    core_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    pypi_lookup: Callable[[str], install_pypi.PypiInfo] | None = None,
) -> InstallPlan:
    """Build the read-only install plan for *options* against *state*."""
    lookup = pypi_lookup or install_pypi.fetch_pypi_info
    checkout = Path(checkout_root)
    core = Path(core_dir) if core_dir is not None else install_env.resolve_core_dir(
        checkout, env=env
    )
    warnings: list[str] = []
    fresh = state.receipt is None
    command = COMMAND_DEV if options.mode == "dev" else COMMAND_PYPI

    receipt_plugins: tuple[install_state.InstallRequirement, ...] = (
        state.receipt.plugins if state.receipt is not None else ()
    )
    deduped, dedupe_warnings = dedupe_requirements(receipt_plugins)
    warnings.extend(dedupe_warnings)

    # --with entries override receipt entries by normalized name.
    with_reqs: dict[str, install_state.InstallRequirement] = {}
    with_order: list[str] = []
    for spec in options.with_specs:
        try:
            parsed = install_state.InstallRequirement.from_spec(spec)
        except ValueError:
            warnings.append(f"ignoring malformed --with spec: {spec}")
            continue
        key = parsed.normalized_name
        if key not in with_reqs:
            with_order.append(key)
        with_reqs[key] = parsed
    base_by_name: dict[str, install_state.InstallRequirement] = {
        req.normalized_name: req for req in deduped
    }
    ordered_names = [req.normalized_name for req in deduped]
    ordered_names.extend(key for key in with_order if key not in base_by_name)
    # The host and core are managed separately; a --with entry naming them is
    # ignored (dev mode: the checkout; PyPI mode: --version) with a warning.
    managed_names = {_normalize(HOST_DIST_NAME), _normalize(CORE_DIST_NAME)}
    for key in with_order:
        if key in managed_names:
            warnings.append(
                f"ignoring --with entry for '{with_reqs[key].name}': the host "
                "and core are managed by the install mode, not --with."
            )
    ordered_names = [key for key in ordered_names if key not in managed_names]

    desired_plugins: list[install_state.InstallRequirement] = []
    rows: list[PlanRow] = []

    host_req = state.receipt.primary if state.receipt is not None else None
    host_target_version: str | None
    if options.mode == "dev":
        desired_host_req = install_state.InstallRequirement(
            name=HOST_DIST_NAME, editable=str(checkout)
        )
        host_target_version = read_checkout_version(checkout)
    elif options.version is not None:
        desired_host_req = install_state.InstallRequirement(
            name=HOST_DIST_NAME, specifier=f"=={options.version}"
        )
        host_target_version = options.version
    else:
        desired_host_req = install_state.InstallRequirement(name=HOST_DIST_NAME)
        host_info = lookup(HOST_DIST_NAME)
        if host_info.warning is not None:
            warnings.append(host_info.warning)
        host_target_version = host_info.version
    host_current = _current_from_state(state, host_req, HOST_DIST_NAME)
    host_target = TargetSource(
        kind="editable" if options.mode == "dev" else "pypi",
        version=host_target_version,
        path=str(checkout) if options.mode == "dev" else None,
    )
    if fresh:
        host_kind, host_note = CHANGE_ADD, "fresh install"
    elif options.mode == "dev":
        if host_current.kind == "editable" and _same_path(host_current.path, checkout):
            host_kind, host_note = CHANGE_KEEP, "editable checkout"
        elif host_current.kind == "editable":
            host_kind, host_note = CHANGE_RETARGET, "retarget checkout"
        else:
            host_kind, host_note = CHANGE_TO_EDITABLE, "this checkout"
    elif host_current.kind == "editable":
        host_kind, host_note = CHANGE_TO_PYPI, "PyPI"
    elif host_current.kind == "missing":
        host_kind, host_note = CHANGE_ADD, "PyPI"
    elif host_current.kind == "other":
        host_kind, host_note = CHANGE_TO_PYPI, "PyPI"
    else:
        host_kind = _index_kind(host_current.version, host_target_version)
        host_note = "PyPI" if host_kind != CHANGE_KEEP else "already current"
    if host_kind == CHANGE_TO_PYPI and _downgrade_pair(
        host_current.version,
        DesiredPlugin(desired_host_req, host_target_version),
    ):
        host_note = f"{host_note} \u00b7 \u26a0 downgrade"
    rows.append(
        PlanRow(
            name=HOST_DIST_NAME,
            role="host",
            current=host_current,
            target=host_target,
            kind=host_kind,
            consequential=_consequential(host_kind),
            note=host_note,
        )
    )

    for key in ordered_names:
        base_req = base_by_name.get(key)
        pinned = with_reqs[key].specifier if key in with_reqs else None
        pinned_version = (
            pinned[2:] if pinned is not None and pinned.startswith("==") else None
        )
        display_name = (base_req or with_reqs[key]).name
        if options.mode == "dev":
            desired, current, note, kind = _resolve_dev_plugin(
                state=state,
                req=base_req,
                name=display_name,
                checkout_root=checkout,
                keep_sources=options.keep_plugin_sources,
                pinned_version=pinned_version,
                pypi_lookup=lookup,
                warnings=warnings,
                env=env,
            )
        else:
            desired, current, note, kind = _resolve_pypi_plugin(
                state=state,
                req=base_req,
                name=display_name,
                keep_sources=options.keep_plugin_sources,
                pinned_version=pinned_version,
                pypi_lookup=lookup,
                warnings=warnings,
                env=env,
            )
        if kind == CHANGE_TO_PYPI and _downgrade_pair(current.version, desired):
            note = f"{note} \u00b7 \u26a0 downgrade"
        desired_plugins.append(desired.requirement)
        target = TargetSource(
            kind="editable"
            if desired.requirement.editable is not None
            else "pypi",
            version=desired.display_version,
            path=desired.requirement.editable,
        )
        rows.append(
            PlanRow(
                name=display_name,
                role="plugin",
                current=current,
                target=target,
                kind=kind,
                consequential=_consequential(kind),
                note=note,
            )
        )

    core_current = _current_from_state(
        state,
        None,
        CORE_DIST_NAME,
        core_local=state.mode in ("dev", "mixed"),
    )
    if options.mode == "dev":
        core_target = TargetSource(kind="editable", path=str(core))
        if core_current.kind == "editable" and _same_path(core_current.path, core):
            core_kind, core_note = CHANGE_KEEP, "editable checkout"
        elif core_current.kind == "editable":
            core_kind, core_note = CHANGE_RETARGET, "retarget checkout"
        elif core_current.kind == "local":
            core_kind, core_note = CHANGE_KEEP, "local build"
        elif core_current.kind == "missing":
            core_kind, core_note = CHANGE_ADD, "editable checkout"
        else:
            core_kind, core_note = CHANGE_TO_EDITABLE, "editable checkout"
    else:
        core_info = lookup(CORE_DIST_NAME)
        if core_info.warning is not None:
            warnings.append(core_info.warning)
        core_target = TargetSource(kind="pypi", version=core_info.version)
        if core_current.kind in ("editable", "local"):
            core_kind, core_note = CHANGE_TO_PYPI, "PyPI"
            if core_current.version and core_info.version and (
                install_pypi.compare_versions(core_current.version, core_info.version)
                > 0
            ):
                core_note = "PyPI \u00b7 \u26a0 downgrade"
        elif core_current.kind == "missing":
            core_kind, core_note = CHANGE_ADD, "PyPI"
        else:
            core_kind = _index_kind(core_current.version, core_info.version)
            core_note = "PyPI" if core_kind != CHANGE_KEEP else "already current"
    rows.append(
        PlanRow(
            name=CORE_DIST_NAME,
            role="core",
            current=core_current,
            target=core_target,
            kind=core_kind,
            consequential=_consequential(core_kind),
            note=core_note,
        )
    )

    requested_python = (options.python or "").strip() or None
    python_current = state.python_version
    python_target = requested_python or python_current
    # A fresh tool env has no interpreter to preserve: picking one is not a change.
    python_change = (
        requested_python is not None
        and python_current is not None
        and requested_python != python_current
    )
    python_plan = PythonPlan(
        current=python_current,
        target=python_target,
        requested=requested_python is not None,
        change=python_change,
    )

    consequential = any(row.consequential for row in rows) or (
        python_change and state.env_exists
    )
    noop = (
        not fresh
        and not options.force
        and all(row.kind == CHANGE_KEEP for row in rows)
        and not python_change
    )

    overrides = editable_override_lines([desired_host_req, *desired_plugins])
    overrides_path = (
        str(install_env.editable_overrides_path(env)) if overrides else None
    )
    swap_argv = tuple(
        build_swap_argv(desired_host_req, desired_plugins, overrides=overrides_path)
    )

    if options.sync:
        warnings.append(
            "--sync requested: the fatal sync gate lands with dev-core-prep; "
            "this preview covers the package set only."
        )
    force_foreign_env = state.env_exists and fresh
    if force_foreign_env:
        warnings.append(
            "the tool environment exists without a receipt; installing will "
            "replace it (--force)."
        )
    if state.receipt_error is not None:
        warnings.append(f"could not read the previous receipt: {state.receipt_error}")

    return InstallPlan(
        mode=options.mode,
        command=command,
        rows=tuple(rows),
        python=python_plan,
        target_dir=str(state.tool_dir),
        current_mode=state.mode,
        consequential=consequential,
        noop=noop,
        warnings=tuple(warnings),
        swap_argv=swap_argv,
        overrides_lines=overrides,
        overrides_path=overrides_path,
        checkout_root=str(checkout),
        core_dir=str(core),
        sync_requested=options.sync,
        fresh=fresh,
        force_foreign_env=force_foreign_env,
    )


def _downgrade_pair(
    current_version: str | None, desired: DesiredPlugin
) -> bool:
    return bool(
        current_version
        and desired.display_version
        and install_pypi.compare_versions(current_version, desired.display_version) > 0
    )


__all__ = [
    "CHANGE_ADD",
    "CHANGE_DOWNGRADE",
    "CHANGE_KEEP",
    "CHANGE_RETARGET",
    "CHANGE_REMOVE",
    "CHANGE_TO_EDITABLE",
    "CHANGE_TO_PYPI",
    "CHANGE_UPGRADE",
    "COMMAND_DEV",
    "COMMAND_PYPI",
    "CORE_DIST_NAME",
    "HOST_DIST_NAME",
    "CurrentSource",
    "DesiredPlugin",
    "InstallPlan",
    "PlanOptions",
    "PlanRow",
    "PythonPlan",
    "TargetSource",
    "build_plan",
    "build_swap_argv",
    "dedupe_requirements",
    "editable_override_lines",
    "read_checkout_version",
    "resolve_sibling",
]
