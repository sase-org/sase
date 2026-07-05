"""Repository and config helpers for install-mode switching."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sase.plugins.catalog import PluginCatalog, load_plugin_catalog
from sase.version._utils import normalize_distribution_name

DEFAULT_DEV_ROOT = "~/projects/github"
LEGACY_FLAT_DEV_ROOT = "~/projects/git"
SASE_ORG = "sase-org"


@dataclass(frozen=True)
class RepoSpec:
    """Resolved source repository for one editable package."""

    full_name: str
    url: str
    checkout_name: str

    @property
    def checkout_relpath(self) -> Path:
        """Return the owner-nested checkout path relative to ``dev_root``."""
        owner, separator, _repo = self.full_name.partition("/")
        if not separator:
            return Path(self.checkout_name)
        return Path(owner) / self.checkout_name


def config_dev_root(config: dict[str, Any] | None) -> Path:
    """Return configured ``update.dev_root``, falling back to the default."""
    value: object = None
    if isinstance(config, dict):
        update = config.get("update")
        if isinstance(update, dict):
            value = update.get("dev_root")
    raw = value if isinstance(value, str) and value.strip() else DEFAULT_DEV_ROOT
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def repo_for_package(
    dist_name: str,
    *,
    catalog: PluginCatalog | None = None,
) -> RepoSpec | None:
    """Resolve the GitHub repository for a known SASE package."""
    key = normalize_distribution_name(dist_name)
    if key == "sase":
        return _repo(SASE_ORG, "sase")
    if key == "sase-core-rs":
        return _repo(SASE_ORG, "sase-core")

    if catalog is not None:
        for entry in catalog.entries:
            candidates = {
                normalize_distribution_name(entry.repo),
                normalize_distribution_name(f"sase-{entry.name}"),
            }
            if key in candidates and entry.full_name:
                return RepoSpec(
                    full_name=entry.full_name,
                    url=_catalog_clone_url(entry.full_name, entry.url),
                    checkout_name=entry.repo or entry.full_name.rsplit("/", 1)[-1],
                )

    if key.startswith("sase-"):
        return _repo(SASE_ORG, key)
    return None


def load_catalog_best_effort() -> PluginCatalog | None:
    """Load the cached plugin catalog if possible; never fail a switch plan."""
    try:
        return load_plugin_catalog(offline=True)
    except Exception:
        return None


def _repo(owner: str, repo: str) -> RepoSpec:
    full_name = f"{owner}/{repo}"
    return RepoSpec(
        full_name=full_name,
        url=_ssh_url(full_name),
        checkout_name=repo,
    )


def _catalog_clone_url(full_name: str, url: str) -> str:
    if not url or _is_github_url(url):
        return _ssh_url(full_name)
    return url


def _ssh_url(full_name: str) -> str:
    return f"git@github.com:{full_name}.git"


def _is_github_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").casefold() == "github.com"
