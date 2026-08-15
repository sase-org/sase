"""Rust-backed temporary provider-disable facade tests."""

from __future__ import annotations

import math

import pytest

import sase.llm_provider.provider_disable as provider_state
from sase.llm_provider.provider_disable import (
    ProviderDisableStateError,
    TemporaryProviderDisable,
    disable_provider,
    disable_provider_until,
    enable_provider,
    get_active_provider_disable,
    get_active_provider_disables,
)

_NOW = 1_800_000_000.0


@pytest.fixture
def registered_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex"],
    )


@pytest.fixture
def real_provider_disable_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_state,
        "get_active_provider_disables",
        get_active_provider_disables,
    )
    monkeypatch.setattr(
        provider_state,
        "get_active_provider_disable",
        get_active_provider_disable,
    )


def test_facade_round_trips_multiple_providers_and_honors_sase_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
    real_provider_disable_reads: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    claude = disable_provider("claude", 900.0, source="test", now=_NOW)
    codex = disable_provider("codex", None, source="test", now=_NOW)
    assert claude.expires_at == _NOW + 900.0
    assert codex.expires_at is None
    assert (tmp_path / "llm_provider_disables.json").is_file()

    records = get_active_provider_disables(_NOW)
    assert list(records) == ["claude", "codex"]
    assert records["claude"] == claude
    assert get_active_provider_disable("codex", _NOW) == codex


def test_facade_replacement_exact_expiry_and_idempotent_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    disable_provider("claude", None, source="test", now=_NOW)
    replacement = disable_provider_until(
        "claude",
        _NOW + 5.0,
        source="test",
        now=_NOW,
    )
    assert get_active_provider_disables(_NOW + 4.999) == {"claude": replacement}
    assert get_active_provider_disables(_NOW + 5.0) == {}
    assert enable_provider("claude") is False

    disable_provider("codex", None, source="test", now=_NOW)
    assert enable_provider("codex") is True
    assert enable_provider("codex") is False


def test_disable_validates_registered_provider_but_clear_remains_uninstall_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="unknown LLM provider"):
        disable_provider("grok", None, source="test", now=_NOW)

    disable_provider("claude", None, source="test", now=_NOW)
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: [],
    )
    assert enable_provider("claude") is True


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "version": 999,
            "provider": "claude",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "provider": " claude",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "provider": "claude",
            "created_at": 0.0,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "provider": "claude",
            "created_at": math.nan,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "provider": "claude",
            "created_at": _NOW,
            "expires_at": _NOW,
            "source": "test",
        },
    ],
)
def test_wire_rehydration_rejects_stale_or_malformed_records(payload) -> None:
    with pytest.raises(ProviderDisableStateError):
        TemporaryProviderDisable.from_wire(payload)


def test_snapshot_rehydration_rejects_bad_shape_and_unsorted_records() -> None:
    with pytest.raises(ProviderDisableStateError, match="snapshot is not an object"):
        provider_state._snapshot_from_wire(None)
    with pytest.raises(ProviderDisableStateError, match="must be a list"):
        provider_state._snapshot_from_wire({"version": 1, "disables": {}})
    with pytest.raises(ProviderDisableStateError, match="not sorted"):
        provider_state._snapshot_from_wire(
            {
                "version": 1,
                "disables": [_wire("codex"), _wire("claude")],
            }
        )


def test_facade_surfaces_binding_errors(
    monkeypatch: pytest.MonkeyPatch,
    real_provider_disable_reads: None,
) -> None:
    def binding(_name: str):
        def fail(*_args):
            raise RuntimeError("state store busy")

        return fail

    monkeypatch.setattr(provider_state, "require_rust_binding", binding)
    with pytest.raises(RuntimeError, match="state store busy"):
        get_active_provider_disables(_NOW)


def _wire(provider: str) -> dict[str, object]:
    return {
        "version": 1,
        "provider": provider,
        "created_at": _NOW,
        "expires_at": None,
        "source": "test",
    }
