"""Environment preparation tests for ``sase lsp``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from sase.integrations.xprompt_lsp import (
    SASE_DEFAULT_CONFIG_PATH_ENV,
    SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV,
    SASE_XPROMPT_BUILTIN_DIR_ENV,
    SASE_XPROMPT_DEFAULT_DIR_ENV,
    SASE_XPROMPT_GLOSSARY_CATALOG_ENV,
    SASE_XPROMPT_MODEL_CATALOG_ENV,
    SASE_XPROMPT_PACKAGE_DIR_ENV,
    SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV,
    SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV,
    SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV,
    _prepare_xprompt_lsp_environment,
)


@pytest.fixture(autouse=True)
def stub_lsp_catalog_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep LSP catalog materialization inside pytest temp directories."""
    monkeypatch.setattr(
        "sase.integrations.xprompt_lsp._default_vcs_project_catalog_path",
        lambda: tmp_path / "xprompt_lsp" / "vcs_project_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.xprompt_lsp._default_model_catalog_path",
        lambda: tmp_path / "xprompt_lsp" / "model_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.xprompt_lsp._default_artifact_ref_catalog_path",
        lambda: tmp_path / "xprompt_lsp" / "artifact_ref_catalog.json",
    )
    monkeypatch.setattr(
        "sase.integrations.xprompt_lsp._default_glossary_catalog_path",
        lambda: tmp_path / "xprompt_lsp" / "glossary_catalog.json",
    )
    monkeypatch.setattr(
        "sase.xprompt.vcs_project_completion.vcs_project_catalog_payload",
        lambda: {"schema_version": 2, "workflow_names": [], "entries": []},
    )
    monkeypatch.setattr(
        "sase.xprompt.model_completion.model_completion_catalog_payload",
        lambda: {"schema_version": 1, "entries": []},
    )
    monkeypatch.setattr(
        "sase.artifact_refs.artifact_ref_lsp_catalog_payload",
        lambda: {"schema_version": 1, "default_project": None, "projects": []},
    )
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_lsp_catalog_payload",
        lambda: {"schema_version": 1, "default_project": None, "projects": []},
    )


def test_prepare_lsp_environment_sets_package_catalog_paths(tmp_path: Path) -> None:
    package_dir = tmp_path / "sase"
    env: dict[str, str] = {
        SASE_XPROMPT_BUILTIN_DIR_ENV: "/custom/xprompts",
    }

    _prepare_xprompt_lsp_environment(env, package_dir=package_dir)

    assert env[SASE_XPROMPT_PACKAGE_DIR_ENV] == str(package_dir)
    assert env[SASE_XPROMPT_BUILTIN_DIR_ENV] == "/custom/xprompts"
    assert env[SASE_XPROMPT_DEFAULT_DIR_ENV] == str(package_dir / "default_xprompts")
    assert env[SASE_DEFAULT_CONFIG_PATH_ENV] == str(package_dir / "default_config.yml")


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
        "sase.xprompt.vcs_project_completion.vcs_project_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        "sase.xprompt.model_completion.model_completion_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        "sase.xprompt.glossary_catalog.editor_glossary_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV] == str(catalog_path)
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_vcs_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 2, "workflow_names": [], "entries": []}

    with patch(
        "sase.xprompt.vcs_project_completion.vcs_project_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV])
    assert catalog_path.name == "vcs_project_catalog.json"
    assert catalog_path.parent.name == "xprompt_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_model_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 1, "entries": []}

    with patch(
        "sase.xprompt.model_completion.model_completion_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_MODEL_CATALOG_ENV])
    assert catalog_path.name == "model_catalog.json"
    assert catalog_path.parent.name == "xprompt_lsp"
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
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_ARTIFACT_REF_CATALOG_ENV])
    assert catalog_path.name == "artifact_ref_catalog.json"
    assert catalog_path.parent.name == "xprompt_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_defaults_glossary_catalog_path(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    payload = {"schema_version": 1, "default_project": None, "projects": []}

    with patch(
        "sase.xprompt.glossary_catalog.editor_glossary_lsp_catalog_payload",
        return_value=payload,
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    catalog_path = Path(env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV])
    assert catalog_path.name == "glossary_catalog.json"
    assert catalog_path.parent.name == "xprompt_lsp"
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == payload


def test_prepare_lsp_environment_swallows_vcs_catalog_failure(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "vcs_project_catalog.json"
    env: dict[str, str] = {
        SASE_XPROMPT_VCS_PROJECT_CATALOG_ENV: str(catalog_path),
    }

    with patch(
        "sase.xprompt.vcs_project_completion.vcs_project_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        # A broken catalog build must never propagate out of env preparation.
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        "sase.xprompt.model_completion.model_completion_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
        "sase.xprompt.glossary_catalog.editor_glossary_lsp_catalog_payload",
        side_effect=RuntimeError("boom"),
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert env[SASE_XPROMPT_GLOSSARY_CATALOG_ENV] == str(catalog_path)
    assert not catalog_path.exists()


def test_prepare_lsp_environment_emits_plugin_metadata(tmp_path: Path) -> None:
    xprompt_module = ModuleType("fake_plugin.prompts")
    config_module = ModuleType("fake_plugin.config")
    xprompts_dir = tmp_path / "plugin" / "xprompts"
    config_dir = tmp_path / "plugin_config"
    xprompts_dir.mkdir(parents=True)
    config_dir.mkdir()
    config_path = config_dir / "default_config.yml"
    config_path.write_text("xprompts: {}\n", encoding="utf-8")

    def fake_resources_files(module: ModuleType) -> Path:
        if module is xprompt_module:
            return tmp_path / "plugin"
        if module is config_module:
            return config_dir
        raise AssertionError(f"unexpected module {module!r}")

    def fake_discover(group: str) -> list[ModuleType]:
        if group == "sase_xprompts":
            return [xprompt_module]
        if group == "sase_config":
            return [config_module]
        return []

    env: dict[str, str] = {}
    with (
        patch(
            "sase.integrations.xprompt_lsp.discover_plugin_resources",
            side_effect=fake_discover,
        ),
        patch(
            "sase.integrations.xprompt_lsp.importlib.resources.files",
            side_effect=fake_resources_files,
        ),
    ):
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == [
        {"module": "fake_plugin.prompts", "path": str(xprompts_dir)}
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

    _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

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
            "sase.integrations.xprompt_lsp.discover_plugin_resources",
            return_value=[module],
        ),
        patch(
            "sase.integrations.xprompt_lsp.importlib.resources.files",
            return_value=plugin_root,
        ),
    ):
        env: dict[str, str] = {}
        _prepare_xprompt_lsp_environment(env, package_dir=tmp_path / "sase")

    assert json.loads(env[SASE_XPROMPT_PLUGIN_DIRS_JSON_ENV]) == []
    assert json.loads(env[SASE_XPROMPT_PLUGIN_CONFIG_PATHS_JSON_ENV]) == []
