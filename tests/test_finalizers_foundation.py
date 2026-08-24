"""Foundation coverage for unconditional host-owned finalizers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.config.core import ConfigLayer
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


def test_explicit_final_none_works_without_feature_flag(tmp_path: Path) -> None:
    _, directives = extract_prompt_directives("%final:none\nDo work")

    resolved = resolve_and_persist_finalizer_plan(
        directives,
        artifacts_dir=str(tmp_path),
    )

    assert resolved is not None
    assert resolved.selected_instances == ()
    assert (tmp_path / FINALIZER_PLAN_FILENAME).is_file()


def test_legacy_commit_finalizer_settings_are_ignored(
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

    assert config.defaults == ("commit",)
    assert config.instances["commit"].max_attempts == 2
    assert config.diagnostics == ()


def test_refusal_defer_is_accepted_but_fail_remains_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer = _default_finalizer_layer()
    layer.data["finalizers"]["instances"]["commit"]["refusal"] = "defer"
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [layer],
    )

    config = load_finalizer_config()

    assert config.instances["commit"].refusal == "defer"
    assert config.diagnostics == ()


def test_refusal_rejects_unknown_values_and_names_both_legal_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer = _default_finalizer_layer()
    layer.data["finalizers"]["instances"]["commit"]["refusal"] = "ignore"
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [layer],
    )

    config = load_finalizer_config()

    assert config.instances["commit"].refusal == "fail"
    assert any(
        "'fail' or 'defer'" in diagnostic.message for diagnostic in config.diagnostics
    )


def test_disable_commit_stop_hook_env_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DISABLE_COMMIT_STOP_HOOK", "1")
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [_default_finalizer_layer()],
    )

    config = load_finalizer_config()

    assert config.defaults == ("commit",)
    assert config.instances["commit"].max_attempts == 2
    assert config.diagnostics == ()


def test_default_commit_plan_is_persisted(tmp_path: Path) -> None:
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

    with pytest.raises(FinalizerPlanError, match="plugin config layers"):
        resolve_and_persist_finalizer_plan(
            PromptDirectives(),
            artifacts_dir=str(tmp_path),
        )


@patch("sase.finalizers.run_finalizers")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
def test_invocation_persists_plan_and_uses_generic_controller(
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
    (tmp_path / "agent_meta.json").write_text("{}", encoding="utf-8")

    result = invoke_agent(
        "raw",
        agent_type="test",
        suppress_output=True,
        artifacts_dir=str(tmp_path),
    )

    assert result.content == "response"
    beta_controller.assert_called_once()
    assert provider.invoke.call_args.args[0] == "processed"
    assert (tmp_path / "test_prompt.md").read_text(encoding="utf-8") == "processed"
    assert (tmp_path / FINALIZER_PLAN_FILENAME).is_file()
    meta = json.loads((tmp_path / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["finalizers"]["selected"] == ["commit"]


def _config_with_lint() -> ConfigLayer:
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
                    },
                    "lint": {
                        "use": "builtin@command",
                        "after": [],
                        "max_attempts": 1,
                        "config": {"command": ["true"], "submission": "none"},
                    },
                },
            }
        },
    )


def test_final_lint_retains_default_commit_in_dependency_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [_config_with_lint()],
    )
    _, directives = extract_prompt_directives("%final:lint\nDo work")

    resolved = resolve_and_persist_finalizer_plan(
        directives,
        artifacts_dir=str(tmp_path),
    )

    assert resolved is not None
    assert resolved.selected_instances == ("commit", "lint")


def test_unknown_and_empty_final_selectors_fail_before_plan_persistence(
    tmp_path: Path,
) -> None:
    _, unknown = extract_prompt_directives("%final:does-not-exist\nDo work")
    _, empty = extract_prompt_directives("%final\nDo work")

    with pytest.raises(FinalizerPlanError):
        resolve_and_persist_finalizer_plan(unknown, artifacts_dir=str(tmp_path))
    with pytest.raises(FinalizerPlanError, match="empty selector"):
        resolve_and_persist_finalizer_plan(empty, artifacts_dir=str(tmp_path))

    assert not (tmp_path / FINALIZER_PLAN_FILENAME).exists()


def test_required_commit_cannot_be_cleared_by_final_none(
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
                        "required": ["commit"],
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
        ],
    )
    _, directives = extract_prompt_directives("%final:none\nDo work")

    with pytest.raises(FinalizerPlanError):
        resolve_and_persist_finalizer_plan(
            directives,
            artifacts_dir=str(tmp_path),
        )

    assert not (tmp_path / FINALIZER_PLAN_FILENAME).exists()
