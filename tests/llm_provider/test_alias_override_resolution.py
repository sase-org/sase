"""Resolution precedence for compact model aliases and launch overrides."""

from __future__ import annotations

import pytest

from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.registry import (
    resolve_model_provider,
    resolve_model_provider_with_effort,
)
from sase.llm_provider.temporary_override import (
    clear_alias_override,
    resolve_effective_default_provider_model,
    resolve_effective_default_provider_model_with_effort,
    set_alias_override,
    set_temporary_override,
)
from tests._model_alias_defaults_fixture import (
    frozen_selector_member,
    frozen_selector_provider_model_effort,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_override_on_size_alias_changes_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_alias_override("medium", "codex/o3", None, source="panel")

    assert resolve_model_alias("medium") == "codex/o3"
    assert resolve_model_alias("@medium") == "codex/o3"
    assert resolve_model_provider("medium") == ("codex", "o3")


def test_override_beats_configured_size_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium": "claude/sonnet"}},
        },
    )

    assert resolve_model_alias("medium") == "claude/sonnet"

    set_alias_override("medium", "codex/o3", None, source="panel")
    assert resolve_model_alias("medium") == "codex/o3"


def test_size_override_effort_and_outer_suffix_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium": "claude/opus@high"}},
        },
    )
    set_alias_override("medium", "codex/gpt-5.6-sol@medium", None, source="panel")

    assert resolve_model_provider_with_effort("@medium") == (
        "codex",
        "gpt-5.6-sol",
        "medium",
    )
    assert resolve_model_provider_with_effort("@medium@xhigh") == (
        "codex",
        "gpt-5.6-sol",
        "xhigh",
    )


def test_retired_worker_override_has_no_builtin_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("claude/"),
    )

    set_alias_override("worker", "codex/o3", None, source="panel")

    assert resolve_model_alias("@worker") == "worker"
    assert resolve_model_provider_with_effort("@xsmall") == (
        "claude",
        "sonnet",
        "medium",
    )
    assert resolve_model_provider_with_effort("@small") == (
        "claude",
        "sonnet",
        "high",
    )
    assert resolve_model_provider_with_effort("@medium") == (
        "claude",
        "sonnet",
        "xhigh",
    )
    assert resolve_model_provider_with_effort("@large") == (
        "claude",
        "opus",
        "xhigh",
    )
    assert resolve_model_provider_with_effort("@xlarge") == (
        "claude",
        "opus",
        "max",
    )


def test_size_alias_override_is_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium": "claude/sonnet"}},
        },
    )

    set_alias_override("large", "codex/o3", None, source="panel")

    assert resolve_model_provider_with_effort(
        "@small"
    ) == frozen_selector_provider_model_effort("small", 0)
    assert resolve_model_provider("medium") == ("claude", "sonnet")
    assert resolve_model_provider("large") == ("codex", "o3")


def test_unconfigured_provider_coder_alias_override_has_no_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    set_alias_override("codex_coder", "codex/o3", None, source="panel")

    assert resolve_model_alias("@codex_coder") == "codex_coder"


def test_configured_provider_coder_alias_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "codex_coder": {
                        "model": "claude/sonnet",
                        "description": "Explicit legacy alias.",
                    }
                }
            },
        },
    )

    set_alias_override("codex_coder", "codex/o3", None, source="panel")
    assert resolve_model_provider("codex_coder") == ("codex", "o3")


def test_retired_coder_override_does_not_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.load_balancing.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    set_alias_override("coder", "codex/o3@medium", None, source="panel")

    assert resolve_model_alias("@claude_coder") == "claude_coder"
    assert resolve_model_alias("@codex_coder@xhigh") == "codex_coder"
    assert resolve_model_provider_with_effort(
        "@medium"
    ) == frozen_selector_provider_model_effort("medium", 0)


def test_custom_default_alias_is_separate_from_launch_default_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "default": {
                        "model": "claude/opus",
                        "description": "Explicit custom default alias.",
                    }
                }
            },
        },
    )

    set_temporary_override("codex/o3", None, source="panel")

    assert resolve_model_alias("@default") == "claude/opus"
    assert resolve_effective_default_provider_model() == ("codex", "o3")


def test_default_launch_override_effort_drives_no_directive_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    set_temporary_override("codex/gpt-5.6-sol@medium", None, source="panel")

    assert resolve_effective_default_provider_model_with_effort() == (
        "codex",
        "gpt-5.6-sol",
        "medium",
    )
    assert resolve_model_provider_with_effort("@default") == (None, "default", None)


def test_concrete_model_token_is_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    set_alias_override("medium", "codex/o3", None, source="panel")
    assert resolve_model_alias("some-bare-model") == "some-bare-model"


def test_override_clears_back_to_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"medium": "claude/sonnet"}},
        },
    )

    set_alias_override("medium", "codex/o3", None, source="panel")
    assert resolve_model_alias("medium") == "codex/o3"

    clear_alias_override("medium")
    assert resolve_model_alias("medium") == "claude/sonnet"


def test_launch_default_setting_override_beats_machine_temporary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", None, source="panel")

    assert resolve_effective_default_provider_model(
        model_alias_overrides={
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): "claude/sonnet"
        }
    ) == ("codex", "o3")


def test_default_override_does_not_move_explicit_size_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.load_balancing.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    set_temporary_override("codex/o3", None, source="panel")

    xlarge = resolve_model_alias_with_effort("@xlarge")
    medium = resolve_model_alias_with_effort("@medium")
    small = resolve_model_alias_with_effort("@small")

    assert (xlarge.target, xlarge.effort) == frozen_selector_member("xlarge", 0)
    assert (medium.target, medium.effort) == frozen_selector_member("medium", 0)
    assert (small.target, small.effort) == frozen_selector_member("small", 0)
