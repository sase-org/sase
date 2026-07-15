"""Focused sidecar remote transport normalization coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase._linked_repo_config import merged_sidecar_entries_from_config
from sase.sdd.store import write_sdd_store_record


def _set_origin(path: Path, remote: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", remote],
        cwd=path,
        check=True,
    )


def _store_record(tmp_path: Path, research_remote: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "storage": "sidecar_repos",
        "sidecars": {
            "plans": {
                "repo": "widget--plans",
                "remote_url": str(tmp_path / "widget--plans.git"),
            },
            "research": {
                "repo": "acme/shared-research",
                "remote_url": research_remote,
            },
        },
    }


@pytest.mark.parametrize(
    "origin",
    [
        "git@github.com:acme/widget.git",
        "https://github.com/acme/widget.git",
    ],
)
def test_unpinned_github_sidecar_uses_canonical_ssh(
    tmp_path: Path,
    origin: str,
) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_origin(primary, origin)

    entries = merged_sidecar_entries_from_config(
        {"repos": {"sidecar": [{"name": "research"}]}},
        primary_workspace_dir=str(primary),
    )

    assert entries[0]["_sase_sidecar_repo_ref"] == "acme/widget--research"
    assert entries[0]["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--research.git"
    )


def test_enterprise_sidecar_preserves_host_and_port(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_origin(
        primary,
        "ssh://git@github.enterprise.test:2222/acme/widget.git",
    )

    entries = merged_sidecar_entries_from_config(
        {
            "github_hosts": ["github.enterprise.test:2222"],
            "repos": {
                "sidecar": [{"name": "research", "repo": "other/shared-research"}]
            },
        },
        primary_workspace_dir=str(primary),
    )

    assert entries[0]["_sase_sidecar_repo_ref"] == "other/shared-research"
    assert entries[0]["_sase_sidecar_remote_url"] == (
        "ssh://git@github.enterprise.test:2222/other/shared-research.git"
    )


def test_non_http_custom_stored_sidecar_remote_is_preserved(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_origin(primary, "https://gitlab.example/acme/widget.git")
    config = {
        "repos": {"sidecar": [{"name": "research", "repo": "acme/shared-research"}]}
    }
    write_sdd_store_record(
        primary,
        _store_record(
            tmp_path,
            "git://gitlab.example/acme/shared-research.git",
        ),
    )

    entries = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )

    assert entries[0]["_sase_sidecar_remote_url"] == (
        "git://gitlab.example/acme/shared-research.git"
    )

    local_remote = tmp_path / "shared-research.git"
    write_sdd_store_record(primary, _store_record(tmp_path, str(local_remote)))

    local_entries = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )

    assert local_entries[0]["_sase_sidecar_remote_url"] == str(local_remote)
