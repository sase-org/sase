"""Merge the plugin catalog with the locally-installed plugin inventory.

The catalog describes which plugins *exist*; this module answers which are
*installed*, at what version, and which SASE entry-point groups they contribute.
It reuses the existing inventory primitives so the matching rules stay in one
place:

- :func:`sase.plugins.inventory.collect_plugin_inventory` yields the
  distributions that contribute ``sase_*`` entry points (the distribution-match
  path), along with their versions and group lists.
- :func:`sase.version._plugins.plugin_candidates_from_distributions` additionally
  detects console-script-only plugins (e.g. a Telegram bot) that contribute no
  ``sase_*`` entry point.

A catalog repository (``sase-github``) maps to an installed distribution via
:func:`sase.version._utils.normalize_distribution_name`.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sase.plugins.inventory import PluginInventory, collect_plugin_inventory
from sase.version._plugins import (
    PluginCandidate,
    plugin_candidates_from_distributions,
)
from sase.version._sources import distribution_version
from sase.version._utils import normalize_distribution_name

#: Version sentinel used by the inventory when no real version is known.
_UNKNOWN_VERSION = "<unknown>"

InventoryFn = Callable[..., PluginInventory]
CandidatesFn = Callable[[], tuple[PluginCandidate, ...]]


@dataclass(frozen=True)
class InstalledInfo:
    """Installed status for one catalog plugin, derived at merge time."""

    installed: bool = False
    version: str | None = None
    entry_point_groups: tuple[str, ...] = ()

    @classmethod
    def not_installed(cls) -> InstalledInfo:
        return cls()


def _installed_plugin_candidates() -> tuple[PluginCandidate, ...]:
    """Detect installed SASE plugins from the live Python environment."""
    return plugin_candidates_from_distributions(importlib.metadata.distributions())


def build_installed_index(
    *,
    inventory_fn: InventoryFn = collect_plugin_inventory,
    candidates_fn: CandidatesFn = _installed_plugin_candidates,
) -> dict[str, InstalledInfo]:
    """Map normalized distribution name -> :class:`InstalledInfo`.

    Distributions that contribute ``sase_*`` entry points are indexed first (with
    their contributed groups); console-script-only plugins fill in any gaps.
    """
    index: dict[str, InstalledInfo] = {}

    inventory = inventory_fn(load_resource_entry_points=False)
    for dist in inventory.distributions:
        key = normalize_distribution_name(dist.package)
        if not key:
            continue
        groups = tuple(
            sorted({entry.split(":", 1)[0] for entry in dist.entry_points if entry})
        )
        index[key] = InstalledInfo(
            installed=True,
            version=_clean_version(dist.version),
            entry_point_groups=groups,
        )

    for candidate in candidates_fn():
        key = normalize_distribution_name(candidate.distribution_name)
        if not key or key in index:
            continue
        index[key] = InstalledInfo(
            installed=True,
            version=_clean_version(distribution_version(candidate.distribution)),
            entry_point_groups=(),
        )

    return index


# pyvision: sdd/tales/202607/onboarding_install_plugins_step.md
def installed_plugin_distributions(
    *,
    candidates_fn: CandidatesFn = _installed_plugin_candidates,
) -> tuple[str, ...]:
    """Return normalized distribution names for installed third-party plugins."""
    names: list[str] = []
    for candidate in candidates_fn():
        key = normalize_distribution_name(candidate.distribution_name)
        if key:
            names.append(key)
    return tuple(_dedupe(names))


def any_plugins_installed(
    *,
    candidates_fn: CandidatesFn = _installed_plugin_candidates,
) -> bool:
    """Return whether any third-party SASE plugin is installed locally."""
    return bool(installed_plugin_distributions(candidates_fn=candidates_fn))


def lookup_installed(
    index: dict[str, InstalledInfo],
    *,
    repo: str,
    name: str,
) -> InstalledInfo:
    """Return the :class:`InstalledInfo` for a catalog entry, or not-installed."""
    for candidate in _distribution_name_candidates(repo=repo, name=name):
        info = index.get(normalize_distribution_name(candidate))
        if info is not None:
            return info
    return InstalledInfo.not_installed()


def _distribution_name_candidates(*, repo: str, name: str) -> tuple[str, ...]:
    candidates: list[str] = []
    if repo:
        candidates.append(repo)
        if not repo.lower().startswith("sase-"):
            candidates.append(f"sase-{repo}")
    if name:
        candidates.append(f"sase-{name}")
        candidates.append(name)
    return tuple(_dedupe(candidates))


def _dedupe(values: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        yield value


def _clean_version(version: str | None) -> str | None:
    if not version or version == _UNKNOWN_VERSION:
        return None
    return version


__all__ = [
    "InstalledInfo",
    "any_plugins_installed",
    "build_installed_index",
    "installed_plugin_distributions",
    "lookup_installed",
]
