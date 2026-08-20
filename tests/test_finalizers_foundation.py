"""Foundation coverage for beta pluggable finalizers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.config.core import ConfigLayer
from sase.feature_flags import override_flags
from sase.finalizers.config import load_finalizer_config
from sase.finalizers.plan import (
    FINALIZER_PLAN_FILENAME,
    FinalizerPlanError,
    resolve_and_persist_finalizer_plan,
)
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


def _default_finalizer_layer() -> ConfigLayer:
    return ConfigLayer(
        name="default",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "finalizers": {
                "defaults": ["commit"],
                "required": [],
                "instances": {
                    "commit": {
                        "use": "builtin@commit",
                        "after": [],
                        "max_attempts": 2,
                        "refusal": "fail",
                    }
                },
            }
        },
    )


def test_explicit_final_requires_pluggable_finalizers_flag(tmp_path: Path) -> None:
    _, directives = extract_prompt_directives("%final:none\nDo work")

    with override_flags(pluggable_finalizers=False):
        with pytest.raises(FinalizerPlanError, match="pluggable_finalizers"):
            resolve_and_persist_finalizer_plan(
                directives,
                artifacts_dir=str(tmp_path),
            )

    assert not (tmp_path / FINALIZER_PLAN_FILENAME).exists()


def test_legacy_commit_finalizer_config_maps_when_no_new_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            _default_finalizer_layer(),
            ConfigLayer(
                name="user",
                path="/home/user/.config/sase/sase.yml",
                exists=True,
                list_strategy="replace",
                data={
                    "commit": {
                        "finalizer": {
                            "enabled": False,
                            "max_passes": 5,
                        }
                    }
                },
            ),
        ],
    )

    config = load_finalizer_config()

    assert config.defaults == ()
    assert config.instances["commit"].max_attempts == 5
    assert {(item.code, item.layer, item.path) for item in config.diagnostics} == {
        ("legacy_commit_finalizer_mapped", "user", "commit.finalizer.enabled"),
        ("legacy_commit_finalizer_mapped", "user", "commit.finalizer.max_passes"),
    }


def test_new_finalizer_policy_wins_over_legacy_commit_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            _default_finalizer_layer(),
            ConfigLayer(
                name="project",
                path="/repo/sase/sase.yml",
                exists=True,
                list_strategy="replace",
                data={
                    "commit": {"finalizer": {"enabled": False}},
                    "finalizers": {
                        "defaults": ["commit"],
                        "instances": {"commit": {"max_attempts": 3}},
                    },
                },
            ),
        ],
    )

    config = load_finalizer_config()

    assert config.defaults == ("commit",)
    assert config.instances["commit"].max_attempts == 3
    assert [(item.code, item.layer, item.path) for item in config.diagnostics] == [
        ("legacy_commit_finalizer_ignored", "project", "commit.finalizer.enabled")
    ]


def test_disable_commit_stop_hook_env_maps_only_without_explicit_finalizers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DISABLE_COMMIT_STOP_HOOK", "1")
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [_default_finalizer_layer()],
    )

    config = load_finalizer_config()

    assert config.defaults == ()
    assert config.diagnostics[-1].code == "legacy_commit_finalizer_env_mapped"

    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            _default_finalizer_layer(),
            ConfigLayer(
                name="project",
                path="/repo/sase/sase.yml",
                exists=True,
                list_strategy="replace",
                data={
                    "finalizers": {
                        "defaults": ["commit"],
                        "instances": {"commit": {"max_attempts": 4}},
                    }
                },
            ),
        ],
    )

    explicit = load_finalizer_config()

    assert explicit.defaults == ("commit",)
    assert explicit.instances["commit"].max_attempts == 4
    assert explicit.diagnostics[-1].code == "legacy_commit_finalizer_env_ignored"


def test_default_commit_plan_is_persisted_when_flag_enabled(tmp_path: Path) -> None:
    with override_flags(pluggable_finalizers=True):
        resolved = resolve_and_persist_finalizer_plan(
            PromptDirectives(),
            artifacts_dir=str(tmp_path),
        )

    assert resolved is not None
    assert resolved.selected_instances == ("commit",)
    payload = json.loads((tmp_path / FINALIZER_PLAN_FILENAME).read_text())
    assert payload["raw_operations"] == []
    assert payload["plan"]["entries"][0]["instance_id"] == "commit"
    assert payload["plan"]["plan_digest"] == resolved.plan.plan_digest


def test_final_none_clears_default_commit_selection(tmp_path: Path) -> None:
    _, directives = extract_prompt_directives("%final:none\nDo work")

    with override_flags(pluggable_finalizers=True):
        resolved = resolve_and_persist_finalizer_plan(
            directives,
            artifacts_dir=str(tmp_path),
        )

    assert resolved is not None
    assert resolved.selected_instances == ()


def test_invalid_finalizer_config_from_plugin_layer_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            ConfigLayer(
                name="default",
                path=None,
                exists=True,
                list_strategy="concatenate",
                data={
                    "finalizers": {
                        "defaults": ["commit"],
                        "instances": {"commit": {"use": "builtin@commit"}},
                    }
                },
            ),
            ConfigLayer(
                name="plugin:example",
                path=None,
                exists=True,
                list_strategy="concatenate",
                data={"finalizers": {"defaults": ["plugin-check"]}},
            ),
        ],
    )

    with override_flags(pluggable_finalizers=True):
        with pytest.raises(FinalizerPlanError, match="plugin config layers"):
            resolve_and_persist_finalizer_plan(
                PromptDirectives(),
                artifacts_dir=str(tmp_path),
            )


@patch("sase.llm_provider._invoke.run_commit_finalizer")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
def test_flag_off_invocation_uses_legacy_commit_finalizer(
    preprocess: MagicMock,
    get_provider: MagicMock,
    legacy_finalizer: MagicMock,
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")
    provider.resolve_model_name.return_value = "model"
    get_provider.return_value = provider
    legacy_finalizer.side_effect = lambda **kwargs: kwargs["invoke_result"]
    preprocess.return_value = _PreprocessResult(prompt="processed")

    with override_flags(pluggable_finalizers=False):
        result = invoke_agent(
            "raw",
            agent_type="test",
            suppress_output=True,
            artifacts_dir=str(tmp_path),
        )

    assert result.content == "response"
    legacy_finalizer.assert_called_once()
    assert provider.invoke.call_args.args[0] == "processed"


@patch("sase.finalizers.run_finalizers")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
def test_flag_on_invocation_persists_plan_and_uses_beta_controller(
    preprocess: MagicMock,
    get_provider: MagicMock,
    beta_controller: MagicMock,
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")
    provider.resolve_model_name.return_value = "model"
    get_provider.return_value = provider
    beta_controller.side_effect = lambda **kwargs: kwargs["invoke_result"]
    preprocess.return_value = _PreprocessResult(prompt="processed")

    with override_flags(pluggable_finalizers=True):
        result = invoke_agent(
            "raw",
            agent_type="test",
            suppress_output=True,
            artifacts_dir=str(tmp_path),
        )

    assert result.content == "response"
    beta_controller.assert_called_once()
    assert "/sase_final" in provider.invoke.call_args.args[0]
    assert (tmp_path / FINALIZER_PLAN_FILENAME).is_file()
