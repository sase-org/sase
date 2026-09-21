"""Prompt-body Jinja filters over provider-disable state."""

from __future__ import annotations

import time

import pytest

from sase.llm_provider.provider_disable import disable_provider
from sase.xprompt._jinja import get_jinja_env
from sase.xprompt.jinja_filters import _provider_disabled, _provider_enabled
from sase.xprompt.processor import _filter_conditional_xprompt_segments


def test_no_disable_state_means_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    assert _provider_disabled("grok") is False
    assert _provider_enabled("grok") is True


def test_hard_disable_matches_any_and_hard_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider("grok", 900.0, source="test")
    assert _provider_disabled("grok") is True
    assert _provider_disabled("grok", "hard") is True
    assert _provider_disabled("grok", "soft") is False
    assert _provider_enabled("grok", "soft") is True


def test_soft_disable_matches_any_and_soft_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider("grok", 900.0, source="test", mode="soft")
    assert _provider_disabled("grok") is True
    assert _provider_disabled("grok", "soft") is True
    assert _provider_disabled("grok", "hard") is False
    assert _provider_enabled("grok", "hard") is True


def test_expired_record_is_not_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider("grok", 60.0, source="test", now=time.time() - 3600.0)
    assert _provider_disabled("grok") is False
    assert _provider_enabled("grok") is True


@pytest.mark.parametrize(
    "provider", ["", "   ", "unknown-provider", None, 42, ["grok"]]
)
def test_blank_non_string_or_unknown_provider_is_not_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path, provider
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    assert _provider_disabled(provider) is False
    assert _provider_enabled(provider) is True


def test_corrupt_state_file_fails_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    (tmp_path / "llm_provider_disables.json").write_text("{not json", encoding="utf-8")
    assert _provider_disabled("grok") is False
    assert _provider_enabled("grok") is True


@pytest.mark.parametrize("helper", [_provider_disabled, _provider_enabled])
def test_invalid_mode_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path, helper
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="mode must be"):
        helper("grok", "warm")


def test_provider_name_matching_is_case_and_space_insensitive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider("grok", 900.0, source="test")
    assert _provider_disabled("  GROK  ") is True
    assert _provider_enabled("  GROK  ") is False


def _render(body: str) -> str:
    return get_jinja_env().from_string(body).render()


def test_gated_segment_survives_when_provider_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    body = (
        "First segment.\n---\n"
        '%if(should_run={{ "grok" | provider_enabled }})\n'
        "Grok segment.\n"
    )
    filtered = _filter_conditional_xprompt_segments(_render(body))
    assert "First segment." in filtered
    assert "Grok segment." in filtered


def test_gated_segment_drops_when_provider_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    disable_provider("grok", 900.0, source="test")
    body = (
        "First segment.\n---\n"
        '%if(should_run={{ "grok" | provider_enabled }})\n'
        "Grok segment.\n"
    )
    filtered = _filter_conditional_xprompt_segments(_render(body))
    assert "First segment." in filtered
    assert "Grok segment." not in filtered
