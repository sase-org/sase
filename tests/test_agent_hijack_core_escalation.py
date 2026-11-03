"""Tests for hijack escalation policy, continuation prompts, and config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.hijack import core as hijack_core
from sase.agent.hijack.config import (
    DEFAULT_ESCALATION_LADDER,
    DEFAULT_SUCCESSOR_CONTEXT,
    agent_hijack_config,
    build_alias_candidates,
)

from ._rust_extension_module_helpers import install_fake_rust_extension


def test_escalation_wrapper_calls_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fake_target(request: object) -> dict[str, object]:
        calls.append(request)
        return {
            "schema_version": 1,
            "available": True,
            "kind": "escalate",
            "from_rung": "@large",
            "to_rung": "@xlarge",
            "concrete": "claude/opus@xhigh",
            "reason": None,
        }

    install_fake_rust_extension(monkeypatch, agent_hijack_escalation_target=fake_target)
    request = {
        "schema_version": 1,
        "model_facts": {"alias": "large"},
        "ladder": ["@large", "@xlarge"],
        "alias_candidates": {},
        "lineage_to_rung": None,
        "stalled_concrete": "claude/opus@high",
    }
    result = hijack_core.hijack_escalation_target(request)
    assert result["available"] is True
    assert result["concrete"] == "claude/opus@xhigh"
    assert calls == [request]


def test_continuation_wrapper_calls_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_prompt(request: object) -> str:
        assert isinstance(request, dict)
        return "%model:x\n#fork:n\nframe\nbody"

    install_fake_rust_extension(
        monkeypatch, agent_hijack_continuation_prompt=fake_prompt
    )
    out = hijack_core.hijack_continuation_prompt({"schema_version": 1})
    assert out.startswith("%model:x")


def test_strip_wrapper_calls_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_rust_extension(
        monkeypatch,
        strip_hijack_launch_directives=lambda prompt: "cleaned",
    )
    assert hijack_core.strip_hijack_launch_directives("anything") == "cleaned"


def test_normalize_wrapper_calls_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch, normalize_hijack_rung=lambda value: "@large"
    )
    assert hijack_core.normalize_hijack_rung("large") == "@large"


def test_config_defaults_match_plan() -> None:
    assert DEFAULT_ESCALATION_LADDER == ("@large", "@xlarge")
    assert DEFAULT_SUCCESSOR_CONTEXT == "fork"


def test_config_accessor_reads_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.agent.hijack.config._merged_config", lambda: {})
    config = agent_hijack_config()
    assert config.escalation_ladder == ("@large", "@xlarge")
    assert config.successor_context == "fork"


def test_config_accessor_rejects_unknown_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.hijack.config._merged_config",
        lambda: {
            "agent_hijack": {
                "escalation_ladder": ["@nope"],
                "successor_context": "fork",
            }
        },
    )
    config = agent_hijack_config()
    assert config.escalation_ladder == ("@large", "@xlarge")


def test_config_accessor_rejects_bad_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.hijack.config._merged_config",
        lambda: {
            "agent_hijack": {
                "escalation_ladder": ["@large", "@xlarge"],
                "successor_context": "brief-extra",
            }
        },
    )
    config = agent_hijack_config()
    assert config.successor_context == "fork"


def test_build_alias_candidates_uses_shipped_pools() -> None:
    candidates = build_alias_candidates(("@large", "@xlarge"))
    assert set(candidates) == {"@large", "@xlarge"}
    # Both shipped rungs resolve to non-empty ordered candidate lists with
    # concrete provider/model@effort targets (availability-filtered, so the
    # exact set depends on installed providers).
    assert candidates["@large"]
    assert candidates["@xlarge"]
    for rung_targets in candidates.values():
        for target in rung_targets:
            assert "/" in target
            assert "@" in target


def test_default_config_has_hijack_section() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "sase" / "default_config.yml").read_text(encoding="utf-8")
    assert "agent_hijack:" in text
    assert 'escalation_ladder: ["@large", "@xlarge"]' in text
    assert "successor_context: fork" in text


def test_schema_has_hijack_section() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "src" / "sase" / "config" / "sase.schema.json").read_text(
            encoding="utf-8"
        )
    )
    section = schema["properties"]["agent_hijack"]
    assert section["additionalProperties"] is False
    ladder = section["properties"]["escalation_ladder"]
    assert ladder["minItems"] == 1
    assert ladder["uniqueItems"] is True
    assert ladder["default"] == ["@large", "@xlarge"]
    successor = section["properties"]["successor_context"]
    assert successor["enum"] == ["fork", "brief"]
    assert successor["default"] == "fork"
