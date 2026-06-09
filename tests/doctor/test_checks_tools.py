"""Tests for Phase 4 doctor optional-tool checks."""

from __future__ import annotations

from sase.doctor.checks_tools import _check_optional_tools


def test_optional_tools_warns_with_affected_features(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_tools.shutil.which",
        lambda command: "/usr/bin/tmux" if command == "tmux" else None,
    )

    check = _check_optional_tools()

    assert check.status == "WARN"
    assert any("terminal image artifact display" in detail for detail in check.details)
    assert check.data["tools"][0]["available"] is True
