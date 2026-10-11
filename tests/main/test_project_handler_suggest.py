"""Tests for the ``sase project suggest`` handler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.main import project_handler_onboarding
from sase.main.project_handler_onboarding import handle_suggest


def _args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "provider": None,
        "all": False,
        "json": False,
        "owner": None,
        "refresh": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def suggest_payload(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub discovery behind the handler and capture its kwargs."""

    payload = {"schema_version": 1, "providers": []}
    seen: dict[str, Any] = {}

    def fake_suggest(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return payload

    monkeypatch.setattr(project_handler_onboarding, "suggest", fake_suggest)
    return payload


class TestHandleSuggest:
    def test_human_output(
        self,
        suggest_payload: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert handle_suggest(_args()) == 0

        out = capsys.readouterr().out
        assert "No workspace providers available." in out

    def test_json_output(
        self,
        suggest_payload: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert handle_suggest(_args(json=True)) == 0

        out = capsys.readouterr().out
        assert json.loads(out) == suggest_payload

    def test_options_forward_to_discovery(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_suggest(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"schema_version": 1, "providers": []}

        monkeypatch.setattr(project_handler_onboarding, "suggest", fake_suggest)

        assert (
            handle_suggest(
                _args(provider="gh", all=True, owner=["sase-org"], refresh=True)
            )
            == 0
        )
        capsys.readouterr()

        assert seen == {
            "providers": ["gh"],
            "include_hidden": True,
            "owners": ["sase-org"],
            "refresh": True,
        }

    def test_unknown_provider_is_usage_error(
        self,
        suggest_payload: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del suggest_payload

        assert handle_suggest(_args(provider="bogus")) == 2

        err = capsys.readouterr().err
        assert "unknown provider 'bogus'" in err

    def test_discovery_failure_returns_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def boom(**kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("core exploded")

        monkeypatch.setattr(project_handler_onboarding, "suggest", boom)

        assert handle_suggest(_args()) == 1

        assert "sase project suggest failed" in capsys.readouterr().err

    def test_explicit_provider_is_remembered(
        self,
        suggest_payload: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del suggest_payload
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

        assert handle_suggest(_args(provider="gh", json=True)) == 0
        capsys.readouterr()

        from sase.project_onboarding.preferences import load_preferences

        assert load_preferences().last_provider == "gh"
