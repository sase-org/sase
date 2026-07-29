"""Existing-repository reconciliation coverage for sidecar initialization."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.sdd._sidecar_init import SidecarInitSpec, initialize_sidecars
from sase.sdd._store_records import write_sdd_store_record

from ._sidecar_init_helpers import bare_remote, configure_git_environment, git


def test_split_init_normalizes_legacy_https_clone_and_record_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    clone = tmp_path / "research-clone"
    clone.mkdir()
    git(clone, "init")
    git(
        clone,
        "remote",
        "add",
        "origin",
        "https://github.com/acme/widget--research.git",
    )
    local = clone / "local.md"
    local.write_text("preserve this checkout\n", encoding="utf-8")
    git(clone, "add", "local.md")
    git(clone, "commit", "-m", "Local research commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    record_path = project / ".sase" / "sdd-store.json"
    record_path.parent.mkdir()
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "provider": "github",
                "host": "github.com",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": "git@github.com:acme/widget--plans.git",
                    },
                    "research": {
                        "repo": "acme/widget--research",
                        "remote_url": "https://github.com/acme/widget--research.git",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    captured: list[dict[str, object]] = []

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        captured.append(options)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget--research",
            "remote_url": "git@github.com:acme/widget--research.git",
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )
    monkeypatch.setattr(
        "sase.sdd._store_link._pull_sdd_clone",
        lambda _root, **_kwargs: True,
    )
    monkeypatch.setattr("sase.sdd._sidecar_init._seed_sidecars", lambda *_a, **_k: None)

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="acme/widget--research",
                remote_url="git@github.com:acme/widget--research.git",
            ),
        ),
    )

    assert captured[0]["sdd_remote_url"] == ("git@github.com:acme/widget--research.git")
    assert local.read_text(encoding="utf-8") == "preserve this checkout\n"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == head
    )
    assert (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "git@github.com:acme/widget--research.git"
    )
    assert outcome.record is not None
    research = outcome.record.sidecar_for_kind("research")
    assert research is not None
    assert research.remote_url == ("git@github.com:acme/widget--research.git")
    persisted = json.loads(record_path.read_text(encoding="utf-8"))
    assert persisted["sidecars"]["research"]["remote_url"] == (
        "git@github.com:acme/widget--research.git"
    )


def test_split_init_cuts_over_changed_pinned_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    old_remote = bare_remote(tmp_path, "widget--research")
    shared_remote = bare_remote(tmp_path, "shared-research")
    clone = tmp_path / "research-clone"
    git(tmp_path, "clone", str(old_remote), str(clone))
    captured: list[dict[str, object]] = []
    write_sdd_store_record(
        project,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "host": "github.com",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": str(old_remote),
                },
            },
        },
    )

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        captured.append(options)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "sase-org/shared-research",
            "remote_url": str(shared_remote),
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="sase-org/shared-research",
                remote_url=str(shared_remote),
            ),
        ),
    )

    assert captured[0]["sdd_repo"] == "sase-org/shared-research"
    assert captured[0]["sdd_remote_url"] == str(shared_remote)
    assert outcome.record is not None
    research = outcome.record.sidecar_for_kind("research")
    assert research is not None
    assert research.repo == "sase-org/shared-research"
    assert research.remote_url == str(shared_remote)
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert origin == str(shared_remote)
    assert (clone / "README.md").is_file()


def test_split_init_re_records_stale_research_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_git_environment(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    research_remote = bare_remote(tmp_path, "widget--research")
    clone = tmp_path / "research-clone"
    write_sdd_store_record(
        project,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "host": "github.com",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:sase-org/sase--research.git",
                },
            },
        },
    )

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        assert options["sdd_repo"] == "acme/widget--research"
        assert options["sdd_remote_url"] == str(research_remote)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget--research",
            "remote_url": str(research_remote),
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="acme/widget--research",
                remote_url=str(research_remote),
            ),
        ),
    )

    assert outcome.record is not None
    assert outcome.record.plans is not None
    assert outcome.record.plans.repo == "acme/widget--plans"
    research = outcome.record.sidecar_for_kind("research")
    assert research is not None
    assert research.repo == "acme/widget--research"
    assert research.remote_url == str(research_remote)
