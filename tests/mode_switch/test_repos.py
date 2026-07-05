from __future__ import annotations

from pathlib import Path

import pytest

from sase.mode_switch.repos import RepoSpec, config_dev_root, repo_for_package
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry


def _entry(
    name: str,
    *,
    owner: str = "sase-org",
    repo: str | None = None,
    url: str | None = None,
) -> PluginCatalogEntry:
    repo = repo or f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description="",
        url=url if url is not None else f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=("sase-plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries,
        from_cache=True,
        stale=False,
    )


def test_config_dev_root_uses_github_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert config_dev_root({}) == tmp_path / "projects" / "github"


def test_repo_for_known_package_uses_ssh_url() -> None:
    spec = repo_for_package("sase-core-rs")

    assert spec is not None
    assert spec.full_name == "sase-org/sase-core"
    assert spec.url == "git@github.com:sase-org/sase-core.git"
    assert spec.checkout_name == "sase-core"


def test_catalog_github_url_is_derived_as_ssh() -> None:
    spec = repo_for_package("sase-github", catalog=_catalog(_entry("github")))

    assert spec is not None
    assert spec.url == "git@github.com:sase-org/sase-github.git"


def test_catalog_non_github_url_is_preserved() -> None:
    url = "ssh://git.example.com/acme/acme-jira.git"
    spec = repo_for_package(
        "sase-jira",
        catalog=_catalog(
            _entry("jira", owner="acme", repo="acme-jira", url=url),
        ),
    )

    assert spec is not None
    assert spec.url == url


def test_repo_spec_checkout_relpath_is_owner_nested() -> None:
    spec = RepoSpec(
        full_name="acme/widgets",
        url="git@example.com:acme/widgets.git",
        checkout_name="widgets",
    )

    assert spec.checkout_relpath == Path("acme") / "widgets"
