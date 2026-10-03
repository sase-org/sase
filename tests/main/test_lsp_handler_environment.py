"""Environment preparation tests for ``sase lsp``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from sase.feature_flags import override_flags
from sase.integrations.macro_lsp import (
    SASE_DEFAULT_CONFIG_PATH_ENV,
    SASE_AGENT_HOLDS_ENV,
    SASE_MACRO_BUILTIN_DIR_ENV,
    SASE_MACRO_DEFAULT_DIR_ENV,
    SASE_MACRO_PACKAGE_DIR_ENV,
    SASE_TYPED_LAUNCH_UNITS_ENV,
    SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV,
    SASE_XPROMPT_BUILTIN_DIR_ENV,
    SASE_XPROMPT_DEFAULT_DIR_ENV,
    SASE_XPROMPT_GLOSSARY_CATALOG_ENV,
    SASE_XPROMPT_MODEL_CATALOG_ENV,
    SASE_XPROMPT_PACKAGE_DIR_ENV,
    SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV,
    SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV,
    SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV,
    _prepare_macro_lsp_environment,
)


@pytest.fixture(autouse=True)
def stub_lsp_catalog_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep LSP catalog materialization inside pytest temp directories."""
    monkeypatch.setattr(
        "sase.integrations.macro_lsp._default_vcs_project_catalog_path",
        lambda: tmp_path / "macro_lsp" / "vcs_project_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.macro_lsp._default_model_catalog_path",
        lambda: tmp_path / "macro_lsp" / "model_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.macro_lsp._default_artifact_ref_catalog_path",
        lambda: tmp_path / "macro_lsp" / "artifact_ref_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.macro_lsp._default_glossary_catalog_path",
        lambda: tmp_path / "macro_lsp" / "glossary_catalog.json",
    )
    monkeypatch.setattr(
        "sase.macro.vcs_project_completion.vcs_project_catalog_payload",
        lambda: {"schema_version": 2, "workflow_names": [], "entries": []},
    )
    monkeypatch.setattr(
        "sase.macro.model_completion.model_completion_catalog_payload",
        lambda: {"schema_version": 1, "entries": []},
    )
    monkeypatch.setattr(
        "sase.artifact_refs.artifact_ref_lsp_catalog_payload",
        lambda: {"schema_version": 1, "default_project": None, "projects": []},
    )
    monkeypatch.setattr(
        "sase.macro.glossary_catalog.editor_glossary_lsp_catalog_payload",
        lambda: {"schema_version": 1, "default_project": None, "projects": []},
    )


def test_prepare_lsp_environment_sets_package_catalog_paths(tmp_path: Path) -> None:
    package_dir = tmp_path / "sase"
    env: dict[str, str] = {
        SASE_XPROMPT_BUILTIN_DIR_ENV: "/custom/xprompts",
    }

    _prepare_macro_lsp_environment(env, package_dir=package_dir)

    assert env[SASE_XPROMPT_PACKAGE_DIR_ENV] == str(package_dir)
    assert env[SASE_XPROMPT_BUILTIN_DIR_ENV] == "/custom/xprompts"
    assert env[SASE_XPROMPT_DEFAULT_DIR_ENV] == str(package_dir / "default_macros")
    assert env[SASE_DEFAULT_CONFIG_PATH_ENV] == str(package_dir / "default_config.yml")
    assert env[SASE_MACRO_PACKAGE_DIR_ENV] == str(package_dir)
    assert env[SASE_MACRO_BUILTIN_DIR_ENV] == "/custom/xprompts"
    assert env[SASE_MACRO_DEFAULT_DIR_ENV] == str(package_dir / "default_macros")


def test_prepare_lsp_environment_adopts_legacy_catalog_override(
    tmp_path: Path,
) -> None:
    env: dict[str, str] = {
        SASE_XPROMPT_BUILTIN_DIR_ENV: "/custom/xprompts",
    }

    _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_MACRO_BUILTIN_DIR_ENV] == "/custom/xprompts"


def test_prepare_lsp_environment_materializes_vcs_project_catalog(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "vcs_project_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV: str(catalog_path),
    }
    payload = {
        "schema_version": 2,
        "workflow_names": ["gh", "git"],
        "entries": [
            {
                "name": "sase",
                "vcs_prefix": "gh",
                "display_tag": "#gh:sase",
                "provider_display": "GitHub",
                "description": "",
                "aliases": [],
                "kind": "project",
                "project": "sase",
                "status": "",
            }
        ],
    }

    with patch(
        "sase.macro.vcs_project_completion.vcs_project_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV] == str(catalog_path)
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_materializes_model_catalog(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "model_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_MODEL_CATALOG_ENV: str(catalog_path),
    }
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "value": "claude-fable-5",
                "display": "claude-fable-5",
                "description": "Claude (fable)",
                "kind": "model",
                "provider": "claude",
                "aliases": ["fable"],
            }
        ],
    }

    with patch(
        "sase.macro.model_completion.model_completion_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_MODEL_CATALOG_ENV] == str(catalog_path)
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_materializes_artifact_ref_catalog(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "artifact_ref_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV: str(catalog_path),
    }
    payload = {
        "schema_version": 1,
        "default_project": "gh_sase-org__sase",
        "projects": [
            {
                "name": "sase",
                "key": "gh_sase-org__sase",
                "aliases": [],
                "context": {
                    "document_roots": [],
                    "chats_root": "/tmp/chats",
                    "artifact_index_path": "/tmp/index.jsonl",
                    "repositories": [],
                    "projects": [],
                },
            }
        ],
    }

    with patch(
        "sase.artifact_refs.artifact_ref_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV] == str(catalog_path)
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_materializes_glossary_catalog(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "glossary_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_GLOSSARY_CATALOG_ENV: str(catalog_path),
    }
    payload = {
        "schema_version": 1,
        "default_project": "sase",
        "projects": [
            {
                "schema_version": 1,
                "project": {
                    "key": "sase",
                    "name": "sase",
                    "aliases": [],
                    "workspace_dir": "/tmp/sase",
                },
                "config_path": "/tmp/sase/sase/sase.yml",
                "config_signature": {
                    "path": "/tmp/sase/sase/sase.yml",
                    "mtime_ns": 1,
                    "size": 42,
                },
                "entries": [],
            }
        ],
    }

    with patch(
        "sase.macro.glossary_catalog.editor_glossary_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV] == str(catalog_path)
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_vcs_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 2, "workflow_names": [], "entries": []}

    with patch(
        "sase.macro.vcs_project_completion.vcs_project_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV])
    assert catalog_path.name == "vcs_project_catalog.json"
    assert catalog_path.parent.name == "macro_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_model_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 1, "entries": []}

    with patch(
        "sase.macro.model_completion.model_completion_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_MODEL_CATALOG_ENV])
    assert catalog_path.name == "model_catalog.json"
    assert catalog_path.parent.name == "macro_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_artifact_ref_catalog_path(
    tmp_path: Path,
) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 1, "default_project": None, "projects": []}

    with patch(
        "sase.artifact_refs.artifact_ref_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV])
    assert catalog_path.name == "artifact_ref_catalog.json"
    assert catalog_path.parent.name == "macro_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_glossary_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 1, "default_project": None, "projects": []}

    with patch(
        "sase.macro.glossary_catalog.editor_glossary_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV])
    assert catalog_path.name == "glossary_catalog.json"
    assert catalog_path.parent.name == "macro_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_swallows_vcs_catalog_failure(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "vcs_project_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV: str(catalog_path),
    }

    with patch(
        "sase.macro.vcs_project_completion.vcs_project_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        # A broken catalog build must never propagate out of env preparation.
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    # The path is still exported (a later rewrite is honored), but the failed
    # build leaves no file behind.
    assert env[SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV] == str(catalog_path)
    assert not catalog_path.exists()


def test_prepare_lsp_environment_swallows_model_catalog_failure(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "model_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_MODEL_CATALOG_ENV: str(catalog_path),
    }

    with patch(
        "sase.macro.model_completion.model_completion_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_MODEL_CATALOG_ENV] == str(catalog_path)
    assert not catalog_path.exists()


def test_prepare_lsp_environment_swallows_artifact_ref_catalog_failure(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "artifact_ref_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV: str(catalog_path),
    }

    with patch(
        "sase.artifact_refs.artifact_ref_lsp_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV] == str(catalog_path)
    assert not catalog_path.exists()


def test_prepare_lsp_environment_swallows_glossary_catalog_failure(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "glossary_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_GLOSSARY_CATALOG_ENV: str(catalog_path),
    }

    with patch(
        "sase.macro.glossary_catalog.editor_glossary_lsp_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV] == str(catalog_path)
    assert not catalog_path.exists()


def test_prepare_lsp_environment_emits_plugin_metadata(
    tmp_path: Path,
    real_plugin_config: None,
) -> None:
    macro_module = ModuleType("fake_plugin.prompts")
    config_module = ModuleType("fake_plugin.config")
    macros_dir = tmp_path / "plugin" / "xprompts"
    config_dir = tmp_path / "plugin_config"
    macros_dir.mkdir(parents=True)
    config_dir.mkdir()
    config_path = config_dir / "default_config.yml"
    config_path.write_text("xprompts: {}\n", encoding="utf-8")

    def fake_resources_files(module: ModuleType) -> Path:
        if module is macro_module:
            return tmp_path / "plugin"
        if module is config_module:
            return config_dir
        raise AssertionError(f"unexpected module {module!r}")

    def fake_discover(group: str) -> list[ModuleType]:
        if group == "sase_xprompts":
            return [macro_module]
        if group == "sase_config":
            return [config_module]
        return []

    env: dict[str, str] = {}
    with (
        patch(
            "sase.integrations.macro_lsp.discover_macro_plugin_modules",
            return_value=[macro_module],
        ),
        patch(
            "sase.integrations.macro_lsp.discover_plugin_resources",
            side_effect=fake_discover,
        ),
        patch(
            "sase.integrations.macro_lsp.importlib.resources.files",
            side_effect=fake_resources_files,
        ),
    ):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == [
        {"module": "fake_plugin.prompts", "path": str(macros_dir)}
    ]
    assert json.loads(env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV]) == [
        {"module": "fake_plugin.config", "path": str(config_path)}
    ]


def test_prepare_lsp_environment_preserves_plugin_metadata_overrides(
    tmp_path: Path,
) -> None:
    env = {
        SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV: '[{"module":"custom","path":"/x"}]',
        SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV: '[{"module":"custom","path":"/c"}]',
    }

    _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV] == (
        '[{"module":"custom","path":"/x"}]'
    )
    assert env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV] == (
        '[{"module":"custom","path":"/c"}]'
    )


def test_prepare_lsp_environment_respects_plugin_disable_env(
    tmp_path: Path,
) -> None:
    module = ModuleType("fake_plugin")
    plugin_root = tmp_path / "plugin"
    (plugin_root / "xprompts").mkdir(parents=True)
    (plugin_root / "default_config.yml").write_text("xprompts: {}\n", encoding="utf-8")

    with (
        patch.dict(
            os.environ,
            {
                "SASE_DISABLE_PLUGIN_XPROMPTS": "1",
                "SASE_DISABLE_PLUGIN_CONFIG": "1",
            },
        ),
        patch(
            "sase.integrations.macro_lsp.discover_plugin_resources",
            return_value=[module],
        ),
        patch(
            "sase.integrations.macro_lsp.importlib.resources.files",
            return_value=plugin_root,
        ),
    ):
        env: dict[str, str] = {}
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == []
    assert json.loads(env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV]) == []


@pytest.mark.parametrize("enabled,expected", [(False, "0"), (True, "1")])
def test_prepare_lsp_environment_pins_typed_launch_units(
    tmp_path: Path,
    enabled: bool,
    expected: str,
) -> None:
    env: dict[str, str] = {}
    with override_flags(typed_launch_units=enabled):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_TYPED_LAUNCH_UNITS_ENV] == expected


def test_prepare_lsp_environment_pins_retired_agent_holds_on(
    tmp_path: Path,
) -> None:
    env: dict[str, str] = {}
    with override_flags(agent_holds=False):
        _prepare_macro_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_AGENT_HOLDS_ENV] == "1"
