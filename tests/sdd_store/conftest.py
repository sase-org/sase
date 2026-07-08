from __future__ import annotations

from typing import Any

import pytest

from sase.sdd.store import _record_cache
import sase.workspace_provider._registry as workspace_registry


@pytest.fixture(autouse=True)
def _clear_store_record_cache() -> None:
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()
    yield
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()


@pytest.fixture
def config_patch(monkeypatch: pytest.MonkeyPatch):
    def apply(config: dict[str, Any]) -> None:
        monkeypatch.setattr("sase.sdd.store.load_merged_config", lambda: config)

    return apply


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
