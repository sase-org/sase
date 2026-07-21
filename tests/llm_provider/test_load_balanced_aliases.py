"""Load-balanced model-alias resolution and state tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_effective_effort,
    resolve_model_alias,
    resolve_model_alias_with_effort,
    validate_model_alias_pool_value,
)
from sase.llm_provider.load_balancing import (
    ModelAliasPoolError,
    parse_model_alias_pool,
)
from sase.llm_provider.registry import resolve_model_provider_with_effort
from sase.xprompt.directives import PromptDirectives
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _configure_pool(
    monkeypatch: pytest.MonkeyPatch,
    value: str = "claude/opus@medium | codex/gpt-5.5",
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"pool": value}},
        },
    )
    llm_config._get_model_aliases_for_token.cache_clear()
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )


def test_pool_parser_normalizes_and_rejects_empty_members() -> None:
    pool = parse_model_alias_pool(" claude/opus@medium|codex/gpt-5.5 ")
    assert pool is not None
    assert pool.members == ("claude/opus@medium", "codex/gpt-5.5")
    assert pool.normalized == "claude/opus@medium | codex/gpt-5.5"
    assert parse_model_alias_pool("claude/opus") is None
    with pytest.raises(ModelAliasPoolError, match="empty members"):
        parse_model_alias_pool("claude/opus || codex/gpt-5.5")


def test_peek_is_stable_and_consumes_round_robin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)

    first = resolve_model_alias_with_effort("@pool")
    assert (first.target, first.effort) == ("claude/opus", "medium")
    assert resolve_model_alias("@pool") == "claude/opus"

    assert resolve_model_alias("@pool", consume=True) == "claude/opus"
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_small_phase_and_cheapest_share_one_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    assert resolve_model_alias("@small_phase_worker", consume=True) == "claude/opus"
    assert resolve_model_alias("@cheapest", consume=True) == "codex/gpt-5.5"


def test_availability_filter_and_all_unavailable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    # A new fingerprint starts at the first member and preserves the full pool
    # when there is no viable fallback.
    _configure_pool(
        monkeypatch,
        "claude/sonnet@high | codex/o3",
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"


def test_pool_edit_fingerprint_resets_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {"builtin": {"pool": "claude/opus | codex/gpt-5.5"}},
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    cfg["model_aliases"] = {"builtin": {"pool": "codex/o3 | claude/sonnet"}}
    llm_config._get_model_aliases_for_token.cache_clear()
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"


def test_corrupt_or_locked_state_never_crashes_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    from sase.llm_provider import load_balancing

    monkeypatch.setattr(
        load_balancing,
        "_locked_state",
        MagicMock(side_effect=OSError("lock unavailable")),
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_nested_pool_fails_closed_and_validation_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "outer": "@inner | claude/opus",
                    "inner": "codex/o3 | claude/sonnet",
                }
            },
        },
    )
    assert resolve_model_alias("@outer") == "@outer"
    assert (
        "nested pool '@inner'"
        in validate_model_alias_pool_value("outer", "@inner | claude/opus")[0]
    )


def test_temporary_override_suspends_pool_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    override = MagicMock(provider="codex", model="o3")
    monkeypatch.setattr(
        llm_config,
        "_active_alias_overrides",
        lambda: {"pool": override},
    )

    assert resolve_model_alias("@pool", consume=True) == "codex/o3"
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"
    assert not (Path.home() / ".sase" / "llm_lb.json").exists()


def test_alias_effort_is_split_and_has_expected_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_effort": "low",
            "model_aliases": {"builtin": {"focused": "claude/opus@medium"}},
        },
    )
    monkeypatch.setattr(llm_config, "_get_default_effort", lambda: "low")

    assert resolve_model_alias("@focused") == "claude/opus"
    assert resolve_model_provider_with_effort("@focused") == (
        "claude",
        "opus",
        "medium",
    )
    assert resolve_effective_effort(PromptDirectives(), "medium") == (
        "medium",
        False,
    )
    assert resolve_effective_effort(
        PromptDirectives(reasoning_effort="high"), "medium"
    ) == ("high", True)


def test_rotation_state_records_alias_fingerprint_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    resolve_model_alias("@pool", consume=True)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["entries"]["pool"]["alias"] == "pool"
    assert data["entries"]["pool"]["cursor"] == 1
    assert len(data["entries"]["pool"]["fingerprint"]) == 64


def test_provider_availability_probe_is_cached_and_honors_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import registry

    monkeypatch.setattr(
        registry,
        "_llm_metadata_payload",
        lambda: {"providers": {"codex": {"autodetect_cli_name": "codex"}}},
    )
    monkeypatch.setenv("SASE_CODEX_PATH", "/opt/codex/bin/codex")
    which = MagicMock(return_value="/opt/codex/bin/codex")
    monkeypatch.setattr(registry.shutil, "which", which)
    registry.provider_cli_available.cache_clear()

    assert registry.provider_cli_available("codex") is True
    assert registry.provider_cli_available("codex") is True
    which.assert_called_once_with("/opt/codex/bin/codex")
