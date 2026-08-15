"""Tests for temporary overrides in alias views."""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    build_alias_views,
    clear_alias_override,
    set_alias_override,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.llm_provider.temporary_override import (
    clear_temporary_override,
    set_temporary_override,
)
from tests.llm_provider._provider_config_helpers import (
    mock_provider_config,
    patch_available_providers,
)


def test_explicit_empty_overrides_skips_authoritative_override_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.get_active_alias_overrides",
        lambda _now=None: (_ for _ in ()).throw(AssertionError("must not load")),
    )

    views = build_alias_views(overrides={})

    assert views
    assert all(view.override is None for view in views)


def test_injected_override_mapping_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3@medium",
        created_at=1.0,
        expires_at=None,
        source="test",
        effort="medium",
    )

    worker = {
        view.name: view for view in build_alias_views(overrides={"medium": override})
    }["medium"]

    assert worker.override is override
    assert (worker.provider, worker.model, worker.effort) == (
        "codex",
        "o3",
        "medium",
    )


def test_active_override_clears_alias_borne_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"medium": "claude/opus@medium"},
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("medium", "codex/o3", None, source="test")
    try:
        worker = {view.name: view for view in build_alias_views()}["medium"]
    finally:
        clear_alias_override("medium")

    assert (worker.provider, worker.model, worker.effort) == (
        "codex",
        "o3",
        None,
    )


def test_active_override_surfaces_its_own_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"medium": "claude/opus@high"},
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("medium", "codex/o3@medium", None, source="test")
    try:
        worker = {view.name: view for view in build_alias_views()}["medium"]
    finally:
        clear_alias_override("medium")

    assert (worker.provider, worker.model, worker.effort) == (
        "codex",
        "o3",
        "medium",
    )


def test_non_default_override_wins_effective_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    patch_available_providers(monkeypatch)

    set_alias_override("medium", "codex/o3", 3600.0, source="test")
    try:
        worker = {v.name: v for v in build_alias_views()}["medium"]
    finally:
        clear_alias_override("medium")

    assert worker.is_overridden is True
    assert worker.override is not None
    assert worker.provider == "codex"
    assert worker.model == "o3"


def test_launch_default_override_is_not_an_alias_view_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    set_temporary_override("codex/o3", None, source="test")
    try:
        views = {v.name: v for v in build_alias_views()}
    finally:
        clear_temporary_override()

    assert "default" not in views
    assert all(not view.is_overridden for view in views.values())
