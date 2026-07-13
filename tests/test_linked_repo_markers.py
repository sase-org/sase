"""Tests for linked repository environment metadata and opened markers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    SIBLING_REPOS_JSON_ENV,
    linked_repo_metadata_from_env,
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_records,
    opened_repo_records,
    record_opened_external_repo,
    record_opened_linked_repo,
)


def test_metadata_from_env_prefers_linked_then_falls_back() -> None:
    linked_payload = json.dumps([{"name": "core", "env_name": "CORE"}])
    sibling_payload = json.dumps([{"name": "legacy", "env_name": "LEGACY"}])

    assert linked_repo_metadata_from_env({LINKED_REPOS_JSON_ENV: linked_payload}) == [
        {"name": "core", "env_name": "CORE"}
    ]
    # Falls back to the legacy env var when the canonical one is absent.
    assert linked_repo_metadata_from_env({SIBLING_REPOS_JSON_ENV: sibling_payload}) == [
        {"name": "legacy", "env_name": "LEGACY"}
    ]
    assert linked_repo_metadata_from_env({}) == []


def test_record_opened_writes_both_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    core = tmp_path / "sase-core_10"
    nvim = tmp_path / "sase-nvim_10"

    record_opened_linked_repo(
        "core",
        str(core),
        reason=" inspect sibling changes ",
        opened_at="2026-06-20T14:00:00+00:00",
    )
    record_opened_linked_repo(
        "nvim",
        str(nvim),
        reason="check editor integration",
        opened_at="2026-06-20T14:05:00+00:00",
    )
    record_opened_linked_repo(
        "core",
        str(core),
        reason="inspect sibling changes",
        opened_at="2026-06-20T14:00:00+00:00",
    )

    linked_marker = json.loads(
        (tmp_path / OPENED_LINKED_FILENAME).read_text(encoding="utf-8")
    )
    sibling_marker = json.loads(
        (tmp_path / OPENED_SIBLINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert linked_marker["schema_version"] == 3
    assert sibling_marker["schema_version"] == 3
    assert [item["name"] for item in linked_marker["linked_repos"]] == ["core", "nvim"]
    assert [item["name"] for item in sibling_marker["siblings"]] == ["core", "nvim"]
    assert linked_marker["linked_repos"][0]["reason"] == "inspect sibling changes"
    assert linked_marker["linked_repos"][0]["opened_at"] == (
        "2026-06-20T14:00:00+00:00"
    )
    assert opened_linked_repo_names(tmp_path) == {"core", "nvim"}
    assert opened_linked_repo_records(tmp_path)["core"] == {
        "name": "core",
        "workspace_dir": str(core.resolve()),
        "reason": "inspect sibling changes",
        "opened_at": "2026-06-20T14:00:00+00:00",
        "kind": "linked",
    }


def test_opened_names_reads_legacy_only_marker(tmp_path: Path) -> None:
    (tmp_path / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [{"name": "core", "workspace_dir": "/tmp/core"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_names(tmp_path) == {"core"}
    assert opened_linked_repo_records(tmp_path) == {
        "core": {
            "name": "core",
            "workspace_dir": "/tmp/core",
            "reason": "",
            "opened_at": "",
            "kind": "linked",
        }
    }


def test_opened_names_reads_new_only_marker(tmp_path: Path) -> None:
    (tmp_path / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "linked_repos": [{"name": "core", "workspace_dir": "/tmp/core"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_names(tmp_path) == {"core"}
    assert opened_linked_repo_records(tmp_path) == {
        "core": {
            "name": "core",
            "workspace_dir": "/tmp/core",
            "reason": "",
            "opened_at": "",
            "kind": "linked",
        }
    }


def test_opened_records_canonical_marker_wins_over_legacy(tmp_path: Path) -> None:
    (tmp_path / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "linked_repos": [
                    {
                        "name": "core",
                        "workspace_dir": "/tmp/canonical",
                        "reason": "canonical reason",
                        "opened_at": "2026-06-20T14:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [{"name": "core", "workspace_dir": "/tmp/legacy"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_records(tmp_path)["core"] == {
        "name": "core",
        "workspace_dir": "/tmp/canonical",
        "reason": "canonical reason",
        "opened_at": "2026-06-20T14:00:00+00:00",
        "kind": "linked",
    }


def test_external_marker_persists_kind_and_canonical_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    clone = (
        tmp_path
        / "workspace"
        / "sase"
        / "repos"
        / "external"
        / "gh"
        / "acme"
        / "widget"
    )

    record_opened_external_repo(
        "gh:acme/widget",
        str(clone),
        reason="inspect upstream",
        opened_at="2026-07-13T17:00:00+00:00",
    )

    marker = json.loads((tmp_path / OPENED_LINKED_FILENAME).read_text(encoding="utf-8"))
    assert marker["schema_version"] == 3
    assert marker["linked_repos"] == [
        {
            "kind": "external",
            "name": "gh:acme/widget",
            "opened_at": "2026-07-13T17:00:00+00:00",
            "reason": "inspect upstream",
            "ref": "gh:acme/widget",
            "workspace_dir": str(clone.resolve()),
        }
    ]
    assert not (tmp_path / OPENED_SIBLINGS_FILENAME).exists()
    assert opened_linked_repo_records(tmp_path) == {}
    assert opened_external_repo_records(tmp_path) == {
        "gh:acme/widget": marker["linked_repos"][0]
    }
    assert opened_repo_records(tmp_path) == opened_external_repo_records(tmp_path)


def test_opened_names_handles_missing_and_malformed(tmp_path: Path) -> None:
    assert opened_linked_repo_names(tmp_path) == set()
    assert opened_linked_repo_records(tmp_path) == {}
    assert opened_linked_repo_names(None) == set()

    (tmp_path / OPENED_LINKED_FILENAME).write_text("{", encoding="utf-8")
    assert opened_linked_repo_names(tmp_path) == set()
