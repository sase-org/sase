"""Tests for doctor model xprompt config checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor.checks_config_xprompts import check_config_model_xprompts
from sase.doctor.runner import DoctorContext
from sase.xprompt.models import XPrompt


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

    check = check_config_model_xprompts(_doctor_context(tmp_path))

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
                        "model": "agy/gemini-3.5-flash-high",
                        "description": "Antigravity flash preset.",
                    }
                }
            },
        },
    )

    check = check_config_model_xprompts(_doctor_context(tmp_path))

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
                        "model": "agy/gemini-3.5-flash-high",
                        "description": "Antigravity flash preset.",
                    }
                }
            },
        },
    )

    check = check_config_model_xprompts(_doctor_context(tmp_path))

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

    check = check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert not check.data["problems"]


def test_model_xprompts_skips_multi_segment_agent_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Xprompt swarms are not model presets, even with per-agent models."""
    xprompts = {
        "m_codex": XPrompt(name="m_codex", content="%model:codex/gpt-5.6-sol"),
        "research_swarm": XPrompt(
            name="research_swarm",
            content=(
                "%id:research.cdx %model:codex/gpt-5.6-sol\n"
                "---\n"
                "%id:research.cld %model:claude/opus"
            ),
        ),
    }
    _patch_model_xprompt_env(
        monkeypatch, xprompts, {"provider": "codex", "model_aliases": {}}
    )

    check = check_config_model_xprompts(_doctor_context(tmp_path))

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

    check = check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert any(
        row["xprompt"] == "m_worker"
        and "@worker" in row["message"]
        and "not a known model alias" in row["message"]
        for row in check.data["problems"]
    )


def test_model_xprompts_validate_alias_override_kwargs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "m_bad_override": XPrompt(
            name="m_bad_override",
            content="%model(opus, unknown=sonnet)",
        ),
    }
    _patch_model_xprompt_env(
        monkeypatch,
        xprompts,
        {"provider": "codex", "model_aliases": {}},
    )

    check = check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert "Unknown model alias 'unknown'" in check.details[0]


def test_model_xprompts_warn_for_unroutable_alias_override_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = {
        "m_bad_target": XPrompt(
            name="m_bad_target",
            content="%model(opus, medium_worker=not-a-model)",
        ),
    }
    _patch_model_xprompt_env(
        monkeypatch,
        xprompts,
        {"provider": "codex", "model_aliases": {}},
    )

    check = check_config_model_xprompts(_doctor_context(tmp_path))

    assert check.status == "WARN"
    assert "%model(medium_worker=not-a-model)" in check.details[0]
