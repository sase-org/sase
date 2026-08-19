"""Model-alias resolution trail tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.llm_provider.config import resolve_model_alias_with_effort
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=1,
        provider=provider,
        created_at=1.0,
        expires_at=None,
        source="test",
    )


def test_direct_alias_records_one_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {"model_aliases": {"custom": {"fast": {"model": "codex/o3"}}}},
    )

    result = resolve_model_alias_with_effort("@fast")

    assert result.target == "codex/o3"
    assert result.alias_trail == ("fast",)


def test_alias_chain_records_hops_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "custom": {
                    "entry": {"model": "@middle"},
                    "middle": {"model": "@final"},
                    "final": {"model": "claude/opus"},
                }
            }
        },
    )

    result = resolve_model_alias_with_effort("@entry")

    assert result.target == "claude/opus"
    assert result.alias_trail == ("entry", "middle", "final")


def test_round_robin_selector_keeps_only_selected_member_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "custom": {
                    "pool": {"model": "@winner | @loser"},
                    "winner": {"model": "claude/opus"},
                    "loser": {"model": "codex/o3"},
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.load_balancing.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    result = resolve_model_alias_with_effort("@pool", consume=True)

    assert result.target == "claude/opus"
    assert result.alias_trail == ("pool", "winner")


def test_ordered_fallback_selector_records_selected_member_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "custom": {
                    "fallback": {"model": "@down || @up"},
                    "down": {"model": "claude/opus"},
                    "up": {"model": "codex/o3"},
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    result = resolve_model_alias_with_effort("@fallback")

    assert result.target == "codex/o3"
    assert result.alias_trail == ("fallback", "up")


def test_temporary_override_short_circuit_still_records_alias_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import config as llm_config

    mock_provider_config(
        monkeypatch,
        {"model_aliases": {"builtin": {"medium": "claude/sonnet"}}},
    )
    override = MagicMock(provider="codex", model="o3", effort=None)
    monkeypatch.setattr(
        llm_config, "_active_alias_overrides", lambda: {"medium": override}
    )

    result = resolve_model_alias_with_effort("@medium")

    assert result.target == "codex/o3"
    assert result.alias_trail == ("medium",)


def test_paused_temporary_override_records_underlying_alias_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import config as llm_config

    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "builtin": {"medium": "@fast"},
                "custom": {"fast": {"model": "claude/sonnet"}},
            }
        },
    )
    override = MagicMock(provider="codex", model="o3", effort=None)
    monkeypatch.setattr(
        llm_config, "_active_alias_overrides", lambda: {"medium": override}
    )

    result = resolve_model_alias_with_effort(
        "@medium",
        provider_disables={"codex": _disable("codex")},
    )

    assert result.target == "claude/sonnet"
    assert result.alias_trail == ("medium", "fast")


def test_launch_alias_override_records_redirect_and_target_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "builtin": {"medium": "claude/sonnet"},
                "custom": {"fast": {"model": "codex/o3"}},
            }
        },
    )

    result = resolve_model_alias_with_effort("@medium", {"medium": "@fast"})

    assert result.target == "codex/o3"
    assert result.alias_trail == ("medium", "fast")


def test_concrete_model_has_empty_alias_trail() -> None:
    result = resolve_model_alias_with_effort("opus")

    assert result.target == "opus"
    assert result.alias_trail == ()


def test_cycle_has_empty_alias_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "model_aliases": {
                "custom": {
                    "a": {"model": "@b"},
                    "b": {"model": "@a"},
                }
            }
        },
    )

    result = resolve_model_alias_with_effort("@a")

    assert not result.valid
    assert result.alias_trail == ()


def test_depth_limit_overflow_has_empty_alias_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aliases = {f"a{index}": {"model": f"@a{index + 1}"} for index in range(18)}
    aliases["a18"] = {"model": "claude/opus"}
    mock_provider_config(monkeypatch, {"model_aliases": {"custom": aliases}})

    result = resolve_model_alias_with_effort("@a0")

    assert not result.valid
    assert result.alias_trail == ()
