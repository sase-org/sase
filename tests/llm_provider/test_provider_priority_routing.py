"""Provider-priority routing integration tests."""

from __future__ import annotations

import pytest

from sase.llm_provider.launch_selection import (
    ALIAS_ORIGIN_DEFAULT_MODEL,
    ALIAS_ORIGIN_DIRECTIVE,
    LaunchSelection,
    launch_selection_from_reservation,
    reservation_from_launch_selection,
    resolve_launch_selection,
)
from sase.llm_provider.load_balancing import MemberAvailability
from sase.llm_provider.model_alias_resolution import model_alias_selector_details
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import (
    PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
    ProviderRoutingContext,
    TemporaryProviderPriority,
    provider_routing_context_from_parts,
)
from sase.llm_provider.registry import (
    get_configured_default_provider_name,
    resolve_model_provider_with_effort,
)
from sase.xprompt.directives import PromptDirectives
from sase.xprompt.model_completion import build_model_completion_catalog
from tests._xprompt_model_completion_helpers import metadata_payload
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _disable(
    provider: str,
    *,
    mode: str = PROVIDER_DISABLE_MODE_HARD,
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
        mode=mode,
    )


def _priority(provider: str) -> TemporaryProviderPriority:
    return TemporaryProviderPriority(
        version=PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
    )


def _context(
    *,
    priority: str | None = None,
    disables: dict[str, TemporaryProviderDisable] | None = None,
) -> ProviderRoutingContext:
    return provider_routing_context_from_parts(
        disables or {},
        _priority(priority) if priority is not None else None,
        captured_at=200.0,
    )


def _pin_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = ["claude", "codex", "grok"]
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: providers,
    )
    monkeypatch.setattr("sase.llm_provider.registry._provider_names", lambda: providers)
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda _provider: True,
    )


def test_priority_pool_matches_virtual_soft_disable_and_exposes_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus | codex/gpt-5.5 | grok/grok-4.6",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    priority_context = _context(priority="codex")
    virtual_soft = {
        "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT),
        "grok": _disable("grok", mode=PROVIDER_DISABLE_MODE_SOFT),
    }

    assert resolve_model_provider_with_effort(
        "@pool",
        routing_context=priority_context,
    ) == resolve_model_provider_with_effort("@pool", provider_disables=virtual_soft)
    details = model_alias_selector_details("pool", routing_context=priority_context)

    assert details is not None
    by_provider = {member.provider: member for member in details.members}
    assert by_provider["codex"].availability == MemberAvailability.PREFERRED
    assert by_provider["codex"].provenance == ("priority",)
    assert by_provider["claude"].availability == MemberAvailability.SPARING
    assert by_provider["claude"].provenance == ("priority_backup",)
    assert by_provider["grok"].priority_backup


def test_priority_keeps_real_hard_disable_and_uses_backup_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "codex/gpt-5.5 | claude/opus",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    context = _context(
        priority="codex",
        disables={"codex": _disable("codex", mode=PROVIDER_DISABLE_MODE_HARD)},
    )

    assert resolve_model_provider_with_effort("@pool", routing_context=context) == (
        "claude",
        "opus",
        None,
    )
    details = model_alias_selector_details("pool", routing_context=context)

    assert details is not None
    by_provider = {member.provider: member for member in details.members}
    assert by_provider["codex"].availability == MemberAvailability.UNAVAILABLE
    assert by_provider["codex"].provenance == ("actual_hard_disable", "priority")
    assert by_provider["claude"].availability == MemberAvailability.SPARING
    assert by_provider["claude"].provenance == ("priority_backup",)


def test_priority_does_not_divert_fallbacks_or_last_resort_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fallback": {
                        "model": "claude/opus || codex/gpt-5.6-sol",
                        "description": "Test fallback.",
                    },
                    "tail": {
                        "model": "(claude/opus | grok/grok-4.6) || codex/gpt-5.6-sol",
                        "description": "Test last resort.",
                    },
                }
            },
        },
    )
    context = _context(priority="codex")

    assert resolve_model_provider_with_effort(
        "@fallback",
        routing_context=context,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort("@tail", routing_context=context) == (
        "claude",
        "opus",
        None,
    )


def test_priority_affects_autodetect_but_not_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    payload = metadata_payload()
    payload["provider_names"] = ["claude", "codex"]
    monkeypatch.setattr(
        "sase.llm_provider.registry._llm_metadata_payload",
        lambda: payload,
    )
    configured_context = _context(priority="codex")
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    assert (
        get_configured_default_provider_name(routing_context=configured_context)
        == "claude"
    )

    mock_provider_config(monkeypatch, {"model_aliases": {}})

    assert (
        get_configured_default_provider_name(routing_context=_context(priority="codex"))
        == "codex"
    )


def test_priority_backup_reservation_remains_redeemable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus | codex/gpt-5.6-sol",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    directives = PromptDirectives(model="@pool", model_alias="pool")
    reserved = LaunchSelection(
        provider="claude",
        model="opus",
        reasoning_effort=None,
        effort_explicit=False,
        alias_trail=("pool",),
        alias_origin=ALIAS_ORIGIN_DIRECTIVE,
        cursor_alias="pool",
    )
    reservation = reservation_from_launch_selection(reserved, alias="pool")

    assert (
        launch_selection_from_reservation(
            reservation,
            directives=directives,
            routing_context=_context(priority="codex"),
        )
        == reserved
    )


@pytest.mark.parametrize(
    ("priority", "extra_disable"),
    (
        ("grok", None),
        ("muse", None),
        ("grok", "grok"),
    ),
)
def test_actual_soft_loses_to_priority_backup_when_priority_is_outside_pool(
    monkeypatch: pytest.MonkeyPatch,
    priority: str,
    extra_disable: str | None,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "(claude/opus | codex/gpt-5.5) || grok/grok-4.6",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}
    if extra_disable is not None:
        disables[extra_disable] = _disable(
            extra_disable, mode=PROVIDER_DISABLE_MODE_HARD
        )
    context = _context(priority=priority, disables=disables)

    assert resolve_model_provider_with_effort("@pool", routing_context=context) == (
        "codex",
        "gpt-5.5",
        None,
    )
    details = model_alias_selector_details("pool", routing_context=context)
    assert details is not None
    selected = next(member for member in details.members if member.selected)
    assert selected.provider == "codex"
    assert not selected.last_resort


def test_actual_soft_reservation_is_rejected_when_non_soft_primary_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus | codex/gpt-5.6-sol",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    directives = PromptDirectives(model="@pool", model_alias="pool")
    reserved = LaunchSelection(
        provider="claude",
        model="opus",
        reasoning_effort=None,
        effort_explicit=False,
        alias_trail=("pool",),
        alias_origin=ALIAS_ORIGIN_DIRECTIVE,
        cursor_alias="pool",
    )
    reservation = reservation_from_launch_selection(reserved, alias="pool")
    context = _context(
        priority="grok",
        disables={"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
    )

    assert (
        launch_selection_from_reservation(
            reservation,
            directives=directives,
            routing_context=context,
        )
        is None
    )


def test_soft_primary_reservation_survives_healthy_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "(claude/opus | codex/gpt-5.5) || grok/grok-4.6",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    directives = PromptDirectives(model="@pool", model_alias="pool")
    reserved = LaunchSelection(
        provider="claude",
        model="opus",
        reasoning_effort="xhigh",
        effort_explicit=False,
        alias_trail=("pool",),
        alias_origin=ALIAS_ORIGIN_DIRECTIVE,
        cursor_alias="pool",
    )
    reservation = reservation_from_launch_selection(reserved, alias="pool")
    context = _context(
        disables={
            "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT),
            "codex": _disable("codex", mode=PROVIDER_DISABLE_MODE_SOFT),
        }
    )

    assert (
        launch_selection_from_reservation(
            reservation,
            directives=directives,
            routing_context=context,
        )
        == reserved
    )


def test_shipped_large_and_xlarge_prefer_codex_when_claude_is_actually_soft(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})
    context = _context(
        priority="grok",
        disables={"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
    )

    assert resolve_model_provider_with_effort("@large", routing_context=context) == (
        "codex",
        "gpt-5.6-sol",
        "xhigh",
    )
    assert resolve_model_provider_with_effort("@xlarge", routing_context=context) == (
        "codex",
        "gpt-6-astra",
        "xhigh",
    )
    default = resolve_launch_selection(
        PromptDirectives(), consume=False, routing_context=context
    )
    assert default is not None
    assert (default.provider, default.model) == ("codex", "gpt-5.6-sol")
    directed = resolve_launch_selection(
        PromptDirectives(model="@large", model_alias="large"),
        consume=False,
        routing_context=context,
    )
    assert directed is not None
    assert (directed.provider, directed.model) == ("codex", "gpt-5.6-sol")


def test_delegated_and_raw_selector_pools_use_the_same_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_model": "(claude/opus | codex/gpt-5.5) || grok/grok-4.6",
            "model_aliases": {
                "custom": {
                    "fast": {
                        "model": "@pool",
                        "description": "Delegates to pool.",
                    },
                    "pool": {
                        "model": "(claude/opus | codex/gpt-5.5) || grok/grok-4.6",
                        "description": "Test pool.",
                    },
                }
            },
        },
    )
    context = _context(
        priority="grok",
        disables={"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
    )

    assert resolve_model_provider_with_effort("@fast", routing_context=context) == (
        "codex",
        "gpt-5.5",
        None,
    )
    default = resolve_launch_selection(
        PromptDirectives(), consume=False, routing_context=context
    )
    assert default is not None
    assert (default.provider, default.model, default.cursor_alias) == (
        "codex",
        "gpt-5.5",
        "setting:default_model",
    )
    reserved = LaunchSelection(
        provider="claude",
        model="opus",
        reasoning_effort=None,
        effort_explicit=False,
        alias_trail=(),
        alias_origin=ALIAS_ORIGIN_DEFAULT_MODEL,
        cursor_alias="setting:default_model",
    )
    reservation = reservation_from_launch_selection(
        reserved, alias="setting:default_model"
    )
    assert (
        launch_selection_from_reservation(
            reservation,
            directives=PromptDirectives(),
            routing_context=context,
        )
        is None
    )


def test_completion_catalog_labels_priority_and_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_providers(monkeypatch)
    payload = metadata_payload()
    monkeypatch.setattr(
        "sase.xprompt.model_completion.get_llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(
        "sase.xprompt.model_completion.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    entries = build_model_completion_catalog(
        use_cache=False,
        overrides={},
        routing_context=_context(priority="codex"),
    )
    by_value = {entry.value: entry for entry in entries}

    assert by_value["gpt-5.6-sol"].provenance == "priority"
    assert by_value["codex/"].provenance == "priority"
    assert by_value["opus"].provenance == "backup"
    assert by_value["claude/"].provenance == "backup"


def test_conflicting_explicit_routing_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="pass routing_context or provider_disables"):
        resolve_model_provider_with_effort(
            "claude/opus",
            provider_disables={},
            routing_context=_context(priority="codex"),
        )
