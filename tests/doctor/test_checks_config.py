"""Tests for Phase 2 doctor config checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.config.core import load_config_layers
from sase.doctor.checks_config import (
    _check_config_layers,
    _check_config_model_xprompts,
)
from sase.doctor.runner import DoctorContext
from sase.xprompt.models import XPrompt


def test_config_layers_report_invalid_existing_yaml(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text("invalid: yaml: [not closed", encoding="utf-8")

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        layers = load_config_layers()
        check = _check_config_layers()

    user_layer = next(layer for layer in layers if layer.name == "user")
    assert user_layer.present is True
    assert user_layer.exists is False
    assert user_layer.error is not None
    assert check.status == "WARN"
    assert "sase.yml" in check.details[0]


def test_config_layers_warns_on_deprecated_sibling_repos(tmp_path: Path) -> None:
    """A legacy ``sibling_repos:`` config triggers a non-fatal doctor warning."""
    (tmp_path / "sase.yml").write_text(
        yaml.dump(
            {
                "sibling_repos": [
                    {"name": "core", "path": "../sase-core", "description": "core"}
                ]
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "workspace"),
    ):
        check = _check_config_layers()

    assert check.status == "WARN"
    detail_text = " ".join(check.details)
    assert "deprecated" in detail_text
    assert "sibling_repos -> linked_repos" in detail_text


# --- config.model_xprompts ---


def _doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path)


def _patch_model_xprompt_env(
    monkeypatch: pytest.MonkeyPatch,
    xprompts: dict[str, XPrompt],
    config: dict[str, object],
) -> None:
    """Inject the xprompt registry and llm_provider config the guard reads.

    The guard expands each preset (``loader.get_all_xprompts``), expands any
    nested ``#`` references during that expansion (``processor.get_all_xprompts``),
    and resolves the final token against ``llm_provider`` config.
    """
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_xprompts", lambda *_a, **_k: xprompts
    )
    monkeypatch.setattr(
        "sase.xprompt.processor.get_all_xprompts", lambda *_a, **_k: xprompts
    )
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )


def test_model_xprompts_warns_when_alias_token_is_unrouted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``%model:#agy_flash`` preset warns when its alias token is missing.

    This is the regression guard for the bug where a removed ``model_aliases``
    entry silently degraded ``#m_agy_flash`` to the default provider.
    """
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "m_agy_flash": XPrompt(name="m_agy_flash", content="%model:#agy_flash"),
    }
    # Codex default, no agy_flash alias -> the bare token cannot route.
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        row["xprompt"] == "m_agy_flash" and row["token"] == "agy_flash"
        for row in check.data["problems"]
    )
    assert "m_agy_flash -> agy_flash does not resolve to a provider" in check.details[0]


def test_model_xprompts_ok_when_alias_routes_to_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the alias restored, the same preset routes cleanly with no warning."""
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "m_agy_flash": XPrompt(name="m_agy_flash", content="%model:#agy_flash"),
    }
    _patch_model_xprompt_env(
        monkeypatch,
        xprompts,
        {
            "provider": "codex",
            "model_aliases": {"agy_flash": "agy/Gemini 3.5 Flash (High)"},
        },
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["problems"]
    assert check.data["scanned"] == 1


def test_model_xprompts_ignores_explicit_provider_model_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit ``provider/model`` preset never warns, even if uninstalled.

    Presets like ``%model:jetski/jetski-default`` target a provider plugin that
    may be absent on this machine; that is intentional and must not be confused
    with the bare-token fallback bug the guard is for.
    """
    xprompts = {
        "m_jet": XPrompt(name="m_jet", content="%model:jetski/jetski-default"),
    }
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["problems"]
