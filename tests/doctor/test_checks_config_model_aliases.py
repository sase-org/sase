"""Tests for doctor model alias config checks."""

from __future__ import annotations

import pytest

from sase.doctor.checks_config_model_aliases import check_config_model_aliases


def test_model_aliases_warns_on_worker_models_and_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removed ``worker_models`` / ``default_model`` keys get migration warnings."""
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "worker_models": {"claude": "codex/gpt-5.6-sol"},
            "default_model": "claude/opus",
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    keys = {row["key"] for row in check.data["problems"]}
    assert keys == {"worker_models", "default_model"}
    detail_text = " ".join(check.details)
    assert "model_aliases" in detail_text
    assert "model_aliases.builtin.default" in detail_text


def test_model_aliases_warns_on_retired_and_unknown_alias_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values pointing at retired/unknown ``@alias`` names are flagged."""
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "coder": "@worker",
                    "phase_worker": "@nope",
                    "epic_creator": "@default",
                    "epic_lander": "claude/opus",
                }
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.builtin.coder" in by_key
    assert "retired" in by_key["model_aliases.builtin.coder"]
    assert "model_aliases.builtin.phase_worker" in by_key
    assert "medium_phase_worker" in by_key["model_aliases.builtin.phase_worker"]
    assert "remove it" in by_key["model_aliases.builtin.phase_worker"]
    assert "model_aliases.builtin.epic_creator" not in by_key
    assert "model_aliases.builtin.epic_lander" not in by_key


def test_model_aliases_accepts_reference_effort_and_parses_problem_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "medium_phase_worker": "@default@high",
                    "coder": "@nope@high",
                    "epic_lander": "@phase_worker@high",
                }
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.builtin.medium_phase_worker" not in by_key
    assert "references unknown alias '@nope'" in by_key["model_aliases.builtin.coder"]
    assert (
        "references the retired '@phase_worker' alias"
        in by_key["model_aliases.builtin.epic_lander"]
    )


def test_model_aliases_warns_on_nested_schema_misuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "blogger": "claude/haiku",
                    "shadow": "claude/haiku",
                },
                "custom": {
                    "coder": {
                        "model": "claude/opus",
                        "description": "Wrong location.",
                    },
                    "shadow": {
                        "model": "claude/opus",
                        "description": "Custom wins.",
                    },
                    "blank_description": {
                        "model": "codex/o3",
                        "description": " ",
                    },
                    "blank_model": {
                        "model": "",
                        "description": "No target.",
                    },
                },
            },
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.builtin.blogger" in by_key
    assert "model_aliases.custom" in by_key["model_aliases.builtin.blogger"]
    assert "model_aliases.custom.coder" in by_key
    assert "builtin alias" in by_key["model_aliases.custom.coder"]
    assert "model_aliases.builtin.shadow" in by_key
    assert (
        "both model_aliases.builtin and model_aliases.custom"
        in by_key["model_aliases.builtin.shadow"]
    )
    assert "model_aliases.custom.blank_description.description" in by_key
    assert "model_aliases.custom.blank_model.model" in by_key


def test_model_aliases_warns_on_legacy_flat_and_top_level_custom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "coder": "@default",
                "blogger": "claude/opus",
            },
            "custom_model_aliases": {
                "researcher": {
                    "model": "codex/o3",
                    "description": "Research follow-ups.",
                }
            },
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.coder" in by_key
    assert "model_aliases.builtin.coder" in by_key["model_aliases.coder"]
    assert "model_aliases.blogger" in by_key
    assert "model_aliases.custom.blogger" in by_key["model_aliases.blogger"]
    assert "custom_model_aliases" in by_key
    assert "model_aliases.custom" in by_key["custom_model_aliases"]


def test_model_aliases_ok_when_config_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {"coder": "@default"},
                "custom": {
                    "big": {
                        "model": "claude/opus",
                        "description": "Large review agents.",
                        "bucket": "review",
                    }
                },
                "buckets": {"review": {"description": "Review roles."}},
            },
        },
    )

    check = check_config_model_aliases()

    assert check.status == "OK"
    assert not check.data["problems"]


def test_model_aliases_allows_custom_phase_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "phase_worker": {
                        "model": "claude/sonnet",
                        "description": "Explicit custom phase role.",
                    }
                }
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "OK"
    assert not check.data["problems"]


@pytest.mark.parametrize(
    "alias",
    [
        "big_epic_lander",
        "xsmall_phase_worker",
        "xlarge_phase_worker",
        "smart",
        "cheap",
    ],
)
def test_model_aliases_recognizes_implicit_roles_as_builtin(
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    alias: {
                        "model": "claude/opus",
                        "description": "Wrong location.",
                    }
                }
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "builtin alias" in by_key[f"model_aliases.custom.{alias}"]


def test_model_aliases_warns_on_dangling_bucket_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "custom": {
                    "research_a": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Lead researcher.",
                        "bucket": "research",
                    }
                },
                "buckets": {
                    "coders": {"description": "Coder follow-up aliases."},
                    "phase_worker": {"description": "Phase worker aliases."},
                    "research": {"description": "Research roles."},
                    "unused": {"description": "No members."},
                },
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "model_aliases.buckets.coders" not in by_key
    assert "model_aliases.buckets.phase_worker" not in by_key
    assert "model_aliases.buckets.research" not in by_key
    assert "model_aliases.buckets.unused" in by_key
    assert "no custom aliases" in by_key["model_aliases.buckets.unused"]


def test_model_aliases_warns_on_malformed_and_nested_pools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {
                    "cheapest": "claude/opus || || codex/gpt-5.5",
                    "medium_phase_worker": "@nested | claude/sonnet",
                },
                "custom": {
                    "nested": {
                        "model": "codex/o3 | claude/opus",
                        "description": "Nested pool target.",
                    }
                },
            }
        },
    )

    check = check_config_model_aliases()

    assert check.status == "WARN"
    messages = " ".join(row["message"] for row in check.data["problems"])
    assert "empty members" in messages
    assert "nested load-balanced pool '@nested'" in messages


def test_model_aliases_notes_unavailable_pool_members_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {"cheapest": "claude/opus@medium | codex/gpt-5.5"}
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: False,
    )

    check = check_config_model_aliases()

    assert check.status == "OK"
    assert check.data["problems"] == ()
    assert len(check.data["notes"]) == 1
    assert "current member 'claude/opus@medium' is retained" in check.details[0]


def test_model_aliases_reports_ordered_fallback_winner_as_information(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {"smartest": ("claude/claude-fable-5 || codex/gpt-5.6-sol")}
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    check = check_config_model_aliases()

    assert check.status == "OK"
    assert check.data["problems"] == ()
    assert check.data["notes"] == (
        "model_aliases.builtin.smartest fallback candidate "
        "'claude/claude-fable-5' is currently unavailable; ordered fallback "
        "currently selects 'codex/gpt-5.6-sol'",
    )


def test_model_aliases_reports_all_unavailable_fallback_diagnostic_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {
            "model_aliases": {
                "builtin": {"smartest": ("claude/claude-fable-5 || codex/gpt-5.6-sol")}
            }
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: False,
    )

    check = check_config_model_aliases()

    assert check.status == "OK"
    assert check.data["problems"] == ()
    assert "first candidate 'claude/claude-fable-5' is retained" in check.details[0]
