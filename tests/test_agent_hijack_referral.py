"""Local remote-hijack referral store."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.agent.hijack import referral


def _home(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "state"
    monkeypatch.setattr(referral, "sase_subdir", lambda name: root / name)
    return root


def test_record_and_list_active_referral(monkeypatch, tmp_path: Path) -> None:
    _home(monkeypatch, tmp_path)
    recorded = referral.record_remote_hijack_referral(
        "athena", "sase-demo.1", now=1_000.0
    )
    assert recorded is not None
    assert recorded.alias == "athena"
    live = referral._list_active_remote_hijack_referrals(now=1_100.0)
    assert [(item.alias, item.agent) for item in live] == [("athena", "sase-demo.1")]


def test_expired_referral_is_pruned(monkeypatch, tmp_path: Path) -> None:
    _home(monkeypatch, tmp_path)
    referral.record_remote_hijack_referral(
        "athena",
        "sase-demo.1",
        now=1_000.0,
        ttl_seconds=30.0,
    )
    live = referral._list_active_remote_hijack_referrals(now=1_040.0)
    assert live == []


def test_apply_sets_referred_overlay_until_fleet_outcome(
    monkeypatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    referral.record_remote_hijack_referral("athena", "sase-demo.1", now=1_000.0)
    running = SimpleNamespace(
        fleet_origin_alias="athena",
        agent_name="sase-demo.1",
        status="RUNNING",
        hijack_overlay=None,
    )
    referral.apply_remote_hijack_referrals([running], now=1_010.0)
    assert running.hijack_overlay == "referred"

    hijacked = SimpleNamespace(
        fleet_origin_alias="athena",
        agent_name="sase-demo.1",
        status="HIJACKED",
        hijack_overlay=None,
    )
    referral.apply_remote_hijack_referrals([hijacked], now=1_020.0)
    assert hijacked.hijack_overlay is None
    assert referral._list_active_remote_hijack_referrals(now=1_020.0) == []
