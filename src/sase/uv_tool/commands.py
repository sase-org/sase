"""Pure ``uv`` argv builders — construct command lines, never execute them.

These functions turn a parsed :class:`~sase.uv_tool.receipt.ToolReceipt` into the
exact ``uv`` argument vector for each operation, so the command shape is
unit-testable in isolation and can be previewed verbatim by ``--dry-run``. Only
:mod:`sase.uv_tool.runner` actually runs them.

Color is opt-in via *color*: callers pass ``"always"`` for a real TTY (pretty
output) and ``"never"`` when capturing/parsing, so uv's text stays deterministic.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from sase.uv_tool.detect import SASE_PACKAGE
from sase.uv_tool.receipt import Requirement, ToolReceipt

ColorChoice = Literal["always", "auto", "never"]


def build_upgrade_all(*, color: ColorChoice | None = None) -> list[str]:
    """``uv tool upgrade sase`` — re-resolve sase core *and* every plugin (D3)."""
    return ["uv", "tool", "upgrade", *_color_args(color), SASE_PACKAGE]


def build_install(
    receipt: ToolReceipt,
    *,
    add: Requirement | str | None = None,
    color: ColorChoice | None = None,
    overrides: str | None = None,
) -> list[str]:
    """``uv tool install`` re-injecting the full reconstructed ``--with`` set.

    The primary package is rendered faithfully from the receipt (``--editable
    <path>`` or a bare/pinned spec), then each deduped injected plugin is
    re-added. When *add* is given, the new plugin joins the set (finding #2:
    ``--with`` replaces rather than appends, so we must pass the *whole* set).
    """
    recon = receipt.reconstruct(add=add)
    argv = ["uv", "tool", "install", *_color_args(color)]
    argv += recon.primary.primary_args()
    for plugin in recon.plugins:
        argv += plugin.with_args()
    argv += _overrides_args(overrides)
    return argv


def build_install_many(
    receipt: ToolReceipt,
    *,
    add: Iterable[Requirement | str],
    color: ColorChoice | None = None,
    overrides: str | None = None,
) -> list[str]:
    """``uv tool install`` re-injecting the full set plus multiple additions."""
    recon = receipt.reconstruct(adds=add)
    argv = ["uv", "tool", "install", *_color_args(color)]
    argv += recon.primary.primary_args()
    for plugin in recon.plugins:
        argv += plugin.with_args()
    argv += _overrides_args(overrides)
    return argv


def build_reinstall_set(
    primary: Requirement,
    plugins: Iterable[Requirement] = (),
    *,
    color: ColorChoice | None = None,
    overrides: str | None = None,
) -> list[str]:
    """``uv tool install --force --reinstall`` for an explicit package set."""
    argv = ["uv", "tool", "install", *_color_args(color), "--force", "--reinstall"]
    argv += primary.primary_args()
    for plugin in plugins:
        argv += plugin.with_args()
    argv += _overrides_args(overrides)
    return argv


def build_uninstall(
    receipt: ToolReceipt,
    *,
    remove: str,
    color: ColorChoice | None = None,
    overrides: str | None = None,
) -> list[str]:
    """``uv tool install`` re-injecting the full ``--with`` set minus *remove*.

    The inverse of :func:`build_install`: because ``uv tool install --with``
    *replaces* the injected set rather than removing one entry, dropping a plugin
    means re-running install with the **whole** reconstructed set sans the target
    (every raw receipt row for its normalized name is removed). Editable/dev
    installs, git/url specs, receipt order, and dedupe behavior are all preserved.
    """
    recon = receipt.reconstruct(remove=remove)
    argv = ["uv", "tool", "install", *_color_args(color)]
    argv += recon.primary.primary_args()
    for plugin in recon.plugins:
        argv += plugin.with_args()
    argv += _overrides_args(overrides)
    return argv


def build_upgrade_packages(
    receipt: ToolReceipt,
    names: Iterable[str],
    *,
    color: ColorChoice | None = None,
    overrides: str | None = None,
) -> list[str]:
    """``uv tool install`` (full set) plus ``--upgrade-package`` per name.

    Upgrades exactly the named injected plugins while pinning everything else, so
    "update plugins" never silently bumps sase core (decision *D3*'s complement).
    """
    argv = build_install(receipt, color=color, overrides=overrides)
    for name in names:
        argv += ["--upgrade-package", name]
    return argv


def _color_args(color: ColorChoice | None) -> list[str]:
    return ["--color", color] if color else []


def _overrides_args(overrides: str | None) -> list[str]:
    return ["--overrides", overrides] if overrides is not None else []


__all__ = [
    "ColorChoice",
    "build_install",
    "build_install_many",
    "build_reinstall_set",
    "build_uninstall",
    "build_upgrade_all",
    "build_upgrade_packages",
]
