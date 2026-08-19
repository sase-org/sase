"""Rust-backed temporary provider-disable facade tests."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

import sase.llm_provider.provider_disable as provider_state
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    ProviderDisableStateError,
    ProviderDisableWriteOutcome,
    TemporaryProviderDisable,
    disable_provider,
    disable_provider_until,
    enable_provider,
    get_active_provider_disable,
    get_active_provider_disables,
    try_disable_provider,
    try_disable_provider_until,
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
    assert claude.is_hard
    assert claude.mode == PROVIDER_DISABLE_MODE_HARD
    assert not claude.is_soft


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


def test_facade_try_disable_is_first_writer_and_preserves_siblings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
    real_provider_disable_reads: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    sibling = disable_provider("codex", 1_200.0, source="sibling", now=_NOW)
    first = try_disable_provider("claude", 900.0, source="usage_limit", now=_NOW)
    lost = try_disable_provider_until(
        "claude",
        _NOW + 3_600.0,
        source="ace",
        now=_NOW,
    )

    assert first.inserted is True
    assert lost.inserted is False
    assert lost.record == first.record
    assert first.record.expires_at == _NOW + 900.0
    assert get_active_provider_disables(_NOW) == {
        "claude": first.record,
        "codex": sibling,
    }


def test_facade_try_disable_one_winner_under_process_contention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registered_providers: None,
    real_provider_disable_reads: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    sibling = disable_provider("codex", 1_200.0, source="sibling", now=_NOW)
    start = tmp_path / "start"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "\n".join(
            [
                "import json, sys, time",
                "from pathlib import Path",
                "from sase.llm_provider.provider_disable import try_disable_provider",
                f"start = Path({str(start)!r})",
                "for _ in range(400):",
                "    if start.exists():",
                "        break",
                "    time.sleep(0.005)",
                "else:",
                "    raise SystemExit('start file never appeared')",
                "index = int(sys.argv[1])",
                "outcome = try_disable_provider(",
                '    "claude",',
                "    60.0 + index,",
                '    source=f"contender-{index}",',
                f"    now={_NOW} + index,",
                ")",
                'print(json.dumps({"inserted": outcome.inserted, '
                '"source": outcome.record.source}))',
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SASE_HOME"] = str(tmp_path)
    processes = [
        subprocess.Popen(
            [sys.executable, str(worker), str(index)],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(6)
    ]
    start.write_text("go\n", encoding="utf-8")
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        outcomes.append(json.loads(stdout))
    winners = [row for row in outcomes if row["inserted"] is True]
    assert len(winners) == 1
    assert all(row["source"] == winners[0]["source"] for row in outcomes)
    stored = get_active_provider_disables(_NOW)
    assert stored["codex"] == sibling
    assert stored["claude"].source == winners[0]["source"]


def test_facade_try_disable_replaces_expired_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider_until("claude", _NOW + 5.0, source="usage_limit", now=_NOW)
    replacement = try_disable_provider(
        "claude",
        60.0,
        source="usage_limit",
        now=_NOW + 5.0,
    )
    assert replacement.inserted is True
    assert replacement.record.created_at == _NOW + 5.0
    assert replacement.record.expires_at == _NOW + 65.0
    assert get_active_provider_disables(_NOW + 5.0) == {"claude": replacement.record}


def test_write_outcome_rehydration_rejects_stale_or_malformed_payloads() -> None:
    record = _wire("claude")
    with pytest.raises(ProviderDisableStateError, match="not an object"):
        ProviderDisableWriteOutcome.from_wire(None)
    with pytest.raises(ProviderDisableStateError, match="unknown extra"):
        ProviderDisableWriteOutcome.from_wire(
            {
                "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
                "inserted": True,
                "record": record,
                "extra": True,
            }
        )
    with pytest.raises(ProviderDisableStateError, match="unsupported"):
        ProviderDisableWriteOutcome.from_wire(
            {"version": 3, "inserted": True, "record": record}
        )
    with pytest.raises(ProviderDisableStateError, match="boolean"):
        ProviderDisableWriteOutcome.from_wire(
            {
                "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
                "inserted": 1,
                "record": record,
            }
        )
    with pytest.raises(ProviderDisableStateError):
        ProviderDisableWriteOutcome.from_wire(
            {
                "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
                "inserted": True,
                "record": {"version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION},
            }
        )


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
            "mode": PROVIDER_DISABLE_MODE_HARD,
        },
        {
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "provider": " claude",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
            "mode": PROVIDER_DISABLE_MODE_HARD,
        },
        {
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "provider": "claude",
            "created_at": 0.0,
            "expires_at": None,
            "source": "test",
            "mode": PROVIDER_DISABLE_MODE_HARD,
        },
        {
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "provider": "claude",
            "created_at": math.nan,
            "expires_at": None,
            "source": "test",
            "mode": PROVIDER_DISABLE_MODE_HARD,
        },
        {
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "provider": "claude",
            "created_at": _NOW,
            "expires_at": _NOW,
            "source": "test",
            "mode": PROVIDER_DISABLE_MODE_HARD,
        },
        {
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "provider": "claude",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
            "mode": "warm",
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
        provider_state._snapshot_from_wire(
            {"version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION, "disables": {}}
        )
    with pytest.raises(ProviderDisableStateError, match="not sorted"):
        provider_state._snapshot_from_wire(
            {
                "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
                "disables": [_wire("codex"), _wire("claude")],
            }
        )
    with pytest.raises(ProviderDisableStateError, match="unsupported"):
        provider_state._snapshot_from_wire({"version": 1, "disables": []})


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


def test_mode_round_trips_defaults_to_hard_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    registered_providers: None,
    real_provider_disable_reads: None,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    defaulted = disable_provider("claude", 900.0, source="test", now=_NOW)
    assert defaulted.is_hard
    assert not defaulted.is_soft
    assert defaulted.mode == PROVIDER_DISABLE_MODE_HARD

    soft = disable_provider(
        "codex",
        1_200.0,
        source="test",
        mode=PROVIDER_DISABLE_MODE_SOFT,
        now=_NOW,
    )
    assert soft.is_soft
    assert not soft.is_hard
    stored = get_active_provider_disables(_NOW)
    assert stored["claude"].is_hard
    assert stored["codex"] == soft

    with pytest.raises(ValueError, match="mode must be hard or soft"):
        disable_provider("claude", 60.0, source="test", mode="warm", now=_NOW)
    assert get_active_provider_disable("claude", _NOW) == defaulted


def test_snapshot_from_wire_accepts_v2_hard_disable_from_ace() -> None:
    """Regression: Ace crashed when Rust started returning schema version 2."""
    payload = {
        "version": 2,
        "disables": [
            {
                "version": 2,
                "provider": "codex",
                "created_at": 1786962179.1084504,
                "expires_at": 1787223600.0,
                "source": "ace",
                "mode": "hard",
            }
        ],
    }
    records = provider_state._snapshot_from_wire(payload)
    assert list(records) == ["codex"]
    assert records["codex"].is_hard
    assert records["codex"].source == "ace"


def _wire(
    provider: str, *, mode: str = PROVIDER_DISABLE_MODE_HARD
) -> dict[str, object]:
    return {
        "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        "provider": provider,
        "created_at": _NOW,
        "expires_at": None,
        "source": "test",
        "mode": mode,
    }
