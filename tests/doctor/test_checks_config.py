"""Tests for Phase 2 doctor config checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.config.core import load_config_layers
from sase.doctor.checks_config import (
    _check_config_layers,
    _check_config_model_aliases,
    _check_config_model_xprompts,
    _check_config_sdd,
    _check_config_xprompt_definitions,
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


def test_config_sdd_warns_on_deprecated_version_controlled(
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )

    check = _check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        issue["code"] == "deprecated-version-controlled"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_errors_when_separate_repo_has_no_record(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n",
        encoding="utf-8",
    )

    check = _check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "separate-repo-not-materialized"
        for issue in check.data["storage_issues"]
    )


def test_config_sdd_errors_on_orphaned_store_record(tmp_path: Path) -> None:
    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget-sdd",
            "remote_url": "git@github.com:acme/widget-sdd.git",
            "discovery": "found",
        },
    )

    check = _check_config_sdd(_doctor_context(tmp_path))

    assert check.status == "ERROR"
    assert any(
        issue["code"] == "orphaned-store-record"
        for issue in check.data["storage_issues"]
    )


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


def test_model_xprompts_warns_when_prefixed_alias_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migrated ``%model:@#agy_flash`` preset warns if the alias is missing."""
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "m_agy_flash": XPrompt(name="m_agy_flash", content="%model:@#agy_flash"),
    }
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        row["xprompt"] == "m_agy_flash"
        and "'@agy_flash' is not a known model alias" in row["message"]
        for row in check.data["problems"]
    )
    assert "'@agy_flash' is not a known model alias" in check.details[0]


def test_model_xprompts_ok_when_alias_routes_to_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the alias restored, the same preset routes cleanly with no warning."""
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "m_agy_flash": XPrompt(name="m_agy_flash", content="%model:@#agy_flash"),
    }
    _patch_model_xprompt_env(
        monkeypatch,
        xprompts,
        {
            "provider": "codex",
            "model_aliases": {
                "custom": {
                    "agy_flash": {
                        "model": "agy/Gemini 3.5 Flash (High)",
                        "description": "Antigravity flash preset.",
                    }
                }
            },
        },
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["problems"]
    assert check.data["scanned"] == 1


def test_model_xprompts_flags_bare_alias_with_migration_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy bare alias preset is surfaced instead of silently skipped."""
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "m_agy_flash": XPrompt(name="m_agy_flash", content="%model:#agy_flash"),
    }
    _patch_model_xprompt_env(
        monkeypatch,
        xprompts,
        {
            "provider": "codex",
            "model_aliases": {
                "custom": {
                    "agy_flash": {
                        "model": "agy/Gemini 3.5 Flash (High)",
                        "description": "Antigravity flash preset.",
                    }
                }
            },
        },
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        row["xprompt"] == "m_agy_flash" and "did you mean @agy_flash" in row["message"]
        for row in check.data["problems"]
    )
    assert "did you mean @agy_flash" in check.details[0]


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


def test_model_xprompts_skips_multi_segment_agent_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-agent xprompts are not model presets, even with per-agent models."""
    xprompts = {
        "m_codex": XPrompt(name="m_codex", content="%model:codex/gpt-5.5"),
        "research_swarm": XPrompt(
            name="research_swarm",
            content=(
                "%name:research.cdx %model:codex/gpt-5.5\n"
                "---\n"
                "%name:research.cld %model:claude/opus"
            ),
        ),
    }
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["problems"]
    assert check.data["scanned"] == 1


def test_model_xprompts_flags_retired_worker_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preset still emitting ``%model:@worker`` is surfaced as a broken preset.

    The worker lane was retired in epic sase-5d phase 4, so ``@worker`` is no
    longer a known alias and the directive parser rejects it outright. The
    doctor still flags the stale preset (WARN) with the parser's message instead
    of silently routing it to the default provider.
    """
    xprompts = {
        "m_worker": XPrompt(name="m_worker", content="%model:@worker"),
    }
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = _check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        row["xprompt"] == "m_worker"
        and "@worker" in row["message"]
        and "not a known model alias" in row["message"]
        for row in check.data["problems"]
    )


# --- config.xprompt_definitions ---


def test_xprompt_definitions_ok_when_no_load_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_prompts",
        lambda *_args, **_kwargs: {"review": object()},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = _check_config_xprompt_definitions(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert "1 xprompt/workflow definition(s) loaded cleanly" == check.summary
    assert check.data["issues"] == ()


def test_xprompt_definitions_warns_with_skipped_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.xprompt.load_issues import record_load_issue

    def load_prompts_with_issue(*_args: object, **_kwargs: object) -> dict[str, object]:
        record_load_issue(
            "/tmp/bad.yml", "mapping values are not allowed", kind="workflow"
        )
        return {}

    monkeypatch.setattr("sase.xprompt.loader.get_all_prompts", load_prompts_with_issue)
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )

    check = _check_config_xprompt_definitions(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert check.summary == "1 xprompt definition file(s) skipped or degraded"
    assert check.details == ("skipped: /tmp/bad.yml: mapping values are not allowed",)
    assert [dict(row) for row in check.data["issues"]] == [
        {
            "source": "/tmp/bad.yml",
            "error": "mapping values are not allowed",
            "kind": "workflow",
        }
    ]


# --- config.model_aliases ---


def test_model_aliases_warns_on_worker_models_and_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removed ``worker_models`` / ``default_model`` keys get migration warnings."""
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "worker_models": {"claude": "codex/gpt-5.5"},
            "default_model": "claude/opus",
        },
    )

    check = _check_config_model_aliases()

    assert check.status == "WARN"
    keys = {row["key"] for row in check.data["problems"]}
    assert keys == {"worker_models", "default_model"}
    detail_text = " ".join(check.details)
    assert "model_aliases" in detail_text
    assert "model_aliases.builtin.default" in detail_text


def test_model_aliases_warns_on_retired_and_unknown_alias_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values pointing at retired/unknown ``@alias`` names are flagged."""
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "coder": "@worker",
                    "phase_worker": "@nope",
                    "epic_creator": "@default",
                    "epic_lander": "claude/opus",
                }
            }
        },
    )

    check = _check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.builtin.coder" in by_key
    assert "retired" in by_key["model_aliases.builtin.coder"]
    assert "model_aliases.builtin.phase_worker" in by_key
    assert "unknown alias '@nope'" in by_key["model_aliases.builtin.phase_worker"]
    assert "model_aliases.builtin.epic_creator" not in by_key
    assert "model_aliases.builtin.epic_lander" not in by_key


def test_model_aliases_warns_on_nested_schema_misuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "blogger": "claude/haiku",
                    "shadow": "claude/haiku",
                },
                "custom": {
                    "coder": {
                        "model": "claude/opus",
                        "description": "Wrong location.",
                    },
                    "shadow": {
                        "model": "claude/opus",
                        "description": "Custom wins.",
                    },
                    "blank_description": {
                        "model": "codex/o3",
                        "description": " ",
                    },
                    "blank_model": {
                        "model": "",
                        "description": "No target.",
                    },
                },
            },
        },
    )

    check = _check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.builtin.blogger" in by_key
    assert "model_aliases.custom" in by_key["model_aliases.builtin.blogger"]
    assert "model_aliases.custom.coder" in by_key
    assert "builtin alias" in by_key["model_aliases.custom.coder"]
    assert "model_aliases.builtin.shadow" in by_key
    assert (
        "both model_aliases.builtin and model_aliases.custom"
        in by_key["model_aliases.builtin.shadow"]
    )
    assert "model_aliases.custom.blank_description.description" in by_key
    assert "model_aliases.custom.blank_model.model" in by_key


def test_model_aliases_warns_on_legacy_flat_and_top_level_custom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "coder": "@default",
                "blogger": "claude/opus",
            },
            "custom_model_aliases": {
                "researcher": {
                    "model": "codex/o3",
                    "description": "Research follow-ups.",
                }
            },
        },
    )

    check = _check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.coder" in by_key
    assert "model_aliases.builtin.coder" in by_key["model_aliases.coder"]
    assert "model_aliases.blogger" in by_key
    assert "model_aliases.custom.blogger" in by_key["model_aliases.blogger"]
    assert "custom_model_aliases" in by_key
    assert "model_aliases.custom" in by_key["custom_model_aliases"]


def test_model_aliases_ok_when_config_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {"coder": "@default"},
                "custom": {
                    "big": {
                        "model": "claude/opus",
                        "description": "Large review agents.",
                    }
                },
            },
        },
    )

    check = _check_config_model_aliases()

    assert check.status == "OK"
    assert not check.data["problems"]
