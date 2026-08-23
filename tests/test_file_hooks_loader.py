"""Tests for file-hook config loading.

Event-matching coverage lives in ``test_file_hooks_matching.py``.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.config.file_hooks import (
    FileHookFilters,
    _load_file_hooks,
    get_all_file_hooks,
    get_file_hook_diagnostics,
)
from tests._file_hooks_helpers import _layer, _registry_with_file_hook_provider


def test_loader_preserves_merge_sources_and_parses_timeout(
    monkeypatch: Any,
) -> None:
    layers = [
        _layer(
            "default",
            [{"name": "packaged", "command": "packaged-command"}],
        ),
        _layer(
            "user",
            [
                {
                    "name": "user-hook",
                    "description": "From user config",
                    "command": "user-command",
                    "timeout": "250ms",
                }
            ],
            strategy="replace",
        ),
        _layer(
            "overlay:sase_athena.yml",
            [{"name": "overlay-hook", "command": "overlay-command"}],
        ),
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    hooks = _load_file_hooks()

    assert [hook.name for hook in hooks] == ["user-hook", "overlay-hook"]
    assert hooks[0].timeout_seconds == 0.25
    assert hooks[0].source_layer == "user"
    assert hooks[1].timeout_seconds == 120
    assert hooks[1].source_layer == "overlay:sase_athena.yml"
    assert _load_file_hooks() is hooks


def test_loader_parses_nested_filters(monkeypatch: Any) -> None:
    layers = [
        _layer(
            "user",
            [
                {
                    "name": "research-highlights",
                    "command": "bob highlights create",
                    "filters": {
                        "projects": ["sase"],
                        "sidecars": ["research"],
                        "path_globs": ["20*/**/*.md", "!20*/*/*__*.md"],
                        "agent_name_globs": [
                            "!research.*.cld",
                            "!research.*.cdx",
                        ],
                        "ops": ["ADD"],
                        "causes": ["referenced_by"],
                        "producers": ["commit", "sdd", "finalizer"],
                    },
                }
            ],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    hooks = _load_file_hooks()

    assert len(hooks) == 1
    filters = hooks[0].filters
    assert filters.projects == ("sase",)
    assert filters.sidecars == ("research",)
    assert filters.path_globs == ("20*/**/*.md", "!20*/*/*__*.md")
    assert filters.agent_name_globs == ("!research.*.cld", "!research.*.cdx")
    assert filters.ops == ("ADD",)
    assert filters.causes == ("referenced_by",)
    assert filters.producers == ("commit", "sdd", "finalizer")


def test_loader_resolves_file_hook_provider_templates(monkeypatch: Any) -> None:
    layers = [
        _layer(
            "local",
            [
                {
                    "use": "sase-research-artifacts@research-highlights",
                    "command": "bob highlights create",
                    "filters": {"path_globs": ["final/**/*.md"]},
                }
            ],
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "sase")
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        _registry_with_file_hook_provider,
    )

    hooks = _load_file_hooks()

    assert len(hooks) == 1
    hook = hooks[0]
    assert hook.name == "research-highlights"
    assert hook.command == "bob highlights create"
    assert hook.timeout_seconds == 30
    assert hook.filters.projects == ("sase",)
    assert hook.filters.sidecars == ("research",)
    assert hook.filters.path_globs == ("final/**/*.md",)


def test_loader_skips_provider_hook_missing_required_local_field(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [{"use": "sase-research-artifacts@research-highlights"}],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        _registry_with_file_hook_provider,
    )

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert hooks == []
    assert "requires local field 'command'" in caplog.text


def test_loader_rejects_use_without_plugin_prefix(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [_layer("user", [{"use": "research-highlights"}], strategy="replace")]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        _registry_with_file_hook_provider,
    )

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert hooks == []
    assert "sase-research-artifacts@research-highlights" in caplog.text

    diagnostics = get_file_hook_diagnostics()
    assert len(diagnostics) == 1
    assert diagnostics[0].hook_name == "research-highlights"
    assert "missing its plugin prefix" in diagnostics[0].message


def test_loader_rejects_use_with_mismatched_plugin_prefix(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [{"use": "builtin@research-highlights", "command": "run"}],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        _registry_with_file_hook_provider,
    )

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert hooks == []
    assert "sase-research-artifacts@research-highlights" in caplog.text
    diagnostics = get_file_hook_diagnostics()
    assert len(diagnostics) == 1
    assert "is provided by" in diagnostics[0].message


def test_file_hook_filters_validate_direct_operation_names() -> None:
    with pytest.raises(ValueError, match="unknown operation"):
        FileHookFilters(ops=("CREATE",))  # type: ignore[arg-type]


def test_file_hook_filters_validate_direct_producer_names() -> None:
    with pytest.raises(ValueError, match="unknown producer"):
        FileHookFilters(producers=("copy",))  # type: ignore[arg-type]


def test_loader_warns_and_skips_invalid_and_duplicate_entries(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [
                {"name": "good", "command": "run"},
                {"name": "bad op", "command": "run"},
                {"name": "good", "command": "duplicate"},
                {"name": "bad-timeout", "command": "run", "timeout": "soon"},
                "not-a-mapping",
            ],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert [hook.name for hook in hooks] == ["good"]
    assert "duplicate hook name 'good'" in caplog.text
    assert "bad-timeout" in caplog.text
    assert "<unknown>" in caplog.text


def test_loader_auto_scopes_project_local_hooks(monkeypatch: Any) -> None:
    layers = [
        _layer(
            "local",
            [
                {"name": "auto", "command": "run"},
                {
                    "name": "explicit",
                    "command": "run",
                    "filters": {"projects": ["other"]},
                },
            ],
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "sase")

    hooks = _load_file_hooks()

    assert hooks[0].filters.projects == ("sase",)
    assert hooks[1].filters.projects == ("other",)


def test_loader_auto_scopes_empty_project_local_filters(monkeypatch: Any) -> None:
    layers = [_layer("local", [{"name": "auto", "command": "run", "filters": {}}])]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)
    monkeypatch.setattr("sase.xprompt.loader.detect_project", lambda: "sase")

    hooks = _load_file_hooks()

    assert hooks[0].filters.projects == ("sase",)


def test_public_loader_fails_soft(monkeypatch: Any, caplog: Any) -> None:
    monkeypatch.setattr(
        "sase.config.file_hooks._load_file_hooks",
        lambda: (_ for _ in ()).throw(ValueError("broken config")),
    )

    with caplog.at_level(logging.WARNING):
        assert get_all_file_hooks() == []

    assert "Failed to load file hooks: broken config" in caplog.text


@pytest.mark.parametrize(
    ("legacy_key", "value"),
    [
        ("projects", ["sase"]),
        ("sidecars", ["research"]),
        ("path_globs", ["*.md"]),
        ("agent_name_globs", ["research.*"]),
        ("ops", ["ADD"]),
        ("causes", ["referenced_by"]),
        ("producers", ["commit"]),
    ],
)
def test_loader_rejects_legacy_top_level_filter_fields(
    legacy_key: str,
    value: object,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [{"name": "legacy", "command": "run", legacy_key: value}],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert hooks == []
    assert "file-hook filter field(s) must be nested under 'filters'" in caplog.text
    assert legacy_key in caplog.text


def test_loader_rejects_legacy_globs_key_and_unknown_fields(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [
                {"name": "legacy", "command": "run", "globs": ["*.md"]},
                {"name": "typo", "command": "run", "agent_globs": ["bob"]},
                {
                    "name": "nested-typo",
                    "command": "run",
                    "filters": {"agent_globs": ["bob"]},
                },
                {
                    "name": "modern",
                    "command": "run",
                    "filters": {
                        "path_globs": ["20*/**/*.md", "!20*/*/*__*.md"],
                        "agent_name_globs": ["!research.*.cld"],
                    },
                },
            ],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert [hook.name for hook in hooks] == ["modern"]
    assert "'globs' was renamed to 'filters.path_globs'" in caplog.text
    assert "unknown field(s): agent_globs" in caplog.text
    assert "unknown filters field(s): agent_globs" in caplog.text
    assert hooks[0].filters.path_globs == ("20*/**/*.md", "!20*/*/*__*.md")
    assert hooks[0].filters.agent_name_globs == ("!research.*.cld",)


def test_loader_rejects_malformed_filters_and_nested_values(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    layers = [
        _layer(
            "user",
            [
                {"name": "null-filters", "command": "run", "filters": None},
                {"name": "bad-filters", "command": "run", "filters": []},
                {
                    "name": "bad-paths",
                    "command": "run",
                    "filters": {"path_globs": "*.md"},
                },
                {
                    "name": "bad-op",
                    "command": "run",
                    "filters": {"ops": ["CREATE"]},
                },
                {
                    "name": "bad-producer",
                    "command": "run",
                    "filters": {"producers": ["copy"]},
                },
            ],
            strategy="replace",
        )
    ]
    monkeypatch.setattr(
        "sase.config.file_hooks.current_config_token", lambda: ("token",)
    )
    monkeypatch.setattr("sase.config.file_hooks.load_config_layers", lambda: layers)

    with caplog.at_level(logging.WARNING):
        hooks = _load_file_hooks()

    assert hooks == []
    assert "'filters' must be a mapping" in caplog.text
    assert "'filters.path_globs' must be a list of strings" in caplog.text
    assert "'filters.ops' contains unknown operation(s): CREATE" in caplog.text
    assert "'filters.producers' contains unknown producer(s): copy" in caplog.text
