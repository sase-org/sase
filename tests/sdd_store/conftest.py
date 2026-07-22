from __future__ import annotations

import os

import pytest

from sase.sdd.store import _record_cache
import sase.workspace_provider._registry as workspace_registry


@pytest.fixture(autouse=True)
def _configure_git_commit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "SASE Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "sase-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "SASE Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "sase-test@example.com")

    config_count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    monkeypatch.setenv(f"GIT_CONFIG_KEY_{config_count}", "commit.gpgsign")
    monkeypatch.setenv(f"GIT_CONFIG_VALUE_{config_count}", "false")
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(config_count + 1))


@pytest.fixture(autouse=True)
def _clear_store_record_cache() -> None:
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()
    yield
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()


@pytest.fixture(autouse=True)
def _pin_primary_workspace_to_tmp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin primary-workspace resolution to the test's own ``tmp_path`` tree.

    ``get_primary_workspace_dir`` normally resolves the primary checkout by
    reading the project spec under ``~/.sase`` and walking parent directories
    for a ``.sase/checkout.json`` marker. Under ``just check`` the pytest tmp
    tree lives *inside* a managed workspace, so that upward walk escapes tmp,
    resolves to the real primary checkout, and ``initialize_sidecars`` writes
    ``sdd-store.json`` there -- clobbering the developer's real SDD store with
    fabricated fixture metadata. Neutralizing both ambient lookups forces
    ``get_primary_workspace_dir`` to fall back to the workspace dir it was
    handed, keeping every store write inside the test sandbox.
    """

    monkeypatch.setattr(
        "sase.sdd._paths.resolve_primary_from_project",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.sdd._paths._resolve_primary_from_marker",
        lambda *_args, **_kwargs: None,
    )


@pytest.fixture
def provider_patch(monkeypatch: pytest.MonkeyPatch):
    def apply(detected_vcs: str | None) -> None:
        def policy(vcs_name: str) -> str | None:
            return {
                "bare_git": "in_tree",
                "github": "separate_repo",
            }.get(vcs_name)

        monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: detected_vcs)
        monkeypatch.setattr(
            "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
            policy,
        )

    return apply
