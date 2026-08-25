from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.pypi_source import ProjectAvailability
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason, UvToolInstall


def _all_available(_dist_name: str) -> ProjectAvailability:
    """A fake ``availability_fn``: every distribution resolves from the index.

    The default injected into existing tests so pre-existing "catalog" source
    expectations are unaffected; it never touches the network.
    """
    return ProjectAvailability.AVAILABLE


def _all_missing(_dist_name: str) -> ProjectAvailability:
    """A fake ``availability_fn``: every distribution is a definitive 404."""
    return ProjectAvailability.MISSING


def _all_available_batch(
    dist_names: Sequence[str],
) -> dict[str, ProjectAvailability]:
    """A fake ``availability_batch_fn``: every probed name resolves from the index."""
    return dict.fromkeys(dist_names, ProjectAvailability.AVAILABLE)


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
        topics=("sase--plugin",),
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
