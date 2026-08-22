"""Tests for file-hook config loading and event matching."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookEvent,
    FileHookFilters,
    _load_file_hooks,
    get_all_file_hooks,
    get_file_hook_diagnostics,
    hook_matches_event,
    match_events,
)
from sase.config.layers import ConfigLayer
from sase.artifact_providers.registry import (
    ArtifactProviderProvenance,
    ArtifactProviderRegistry,
    FileHookProviderRecord,
)


def _layer(
    name: str,
    hooks: object,
    *,
    strategy: str = "concatenate",
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=None,
        exists=True,
        list_strategy=strategy,
        data={"file_hooks": hooks},
    )


def _hook(
    *,
    projects: tuple[str, ...] | None = None,
    sidecars: tuple[str, ...] | None = None,
    path_globs: tuple[str, ...] | None = None,
    agent_name_globs: tuple[str, ...] | None = None,
    ops: tuple[str, ...] | None = None,
    causes: tuple[str, ...] | None = None,
    producers: tuple[str, ...] | None = None,
) -> FileHookConfig:
    return FileHookConfig(
        name="test-hook",
        description=None,
        command="check",
        timeout_seconds=120,
        filters=FileHookFilters(
            projects=projects,
            sidecars=sidecars,
            path_globs=path_globs,
            agent_name_globs=agent_name_globs,
            ops=ops,  # type: ignore[arg-type]
            causes=causes,
            producers=producers,  # type: ignore[arg-type]
        ),
    )


def _event(
    path: str,
    *,
    project: str = "sase",
    sidecar: str | None = "research",
    op: str = "ADD",
    agent: str | None = None,
    cause: str = "user",
) -> FileHookEvent:
    return FileHookEvent(
        project=project,
        repo_kind=f"sidecar:{sidecar}" if sidecar else "primary",
        sidecar_role=sidecar,
        rel_path=path,
        op=op,  # type: ignore[arg-type]
        cause=cause,
        agent_name=agent,
    )


def _registry_with_file_hook_provider() -> ArtifactProviderRegistry:
    provenance = ArtifactProviderProvenance(
        group="sase_file_hooks",
        name="research",
        package="sase-research-artifacts",
        version="1.0.0",
    )
    return ArtifactProviderRegistry(
        ref_providers=(),
        file_hook_providers=(
            FileHookProviderRecord(
                provider_id="research-highlights",
                template={
                    "description": "Render research highlights.",
                    "filters": {
                        "sidecars": ["research"],
                        "path_globs": ["reports/**/*.md", "!reports/drafts/**"],
                    },
                    "timeout": "30s",
                },
                required_fields=("command",),
                provenance=provenance,
            ),
        ),
        entry_kinds=(),
        diagnostics=(),
    )


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


def test_path_glob_positive_or_and_negative_veto() -> None:
    hook = _hook(path_globs=("src/*.py", "tests/*.py", "!tests/private*.py"))

    assert hook_matches_event(hook, _event("src/main.py"))
    assert hook_matches_event(hook, _event("tests/test_main.py"))
    assert not hook_matches_event(hook, _event("tests/private_test.py"))
    assert not hook_matches_event(hook, _event("docs/main.py"))


def test_negative_only_path_globs_mean_everything_except() -> None:
    hook = _hook(path_globs=("!**/*__*.md",))

    assert hook_matches_event(hook, _event("202607/report/report.md"))
    assert not hook_matches_event(hook, _event("202607/report/report__draft.md"))


def test_star_does_not_cross_slashes_and_globstar_does() -> None:
    shallow = _hook(path_globs=("src/*.py",))
    recursive = _hook(path_globs=("src/**/*.py",))

    assert hook_matches_event(shallow, _event("src/main.py"))
    assert not hook_matches_event(shallow, _event("src/nested/main.py"))
    assert hook_matches_event(recursive, _event("src/nested/main.py"))


def test_dotglob_and_posix_path_normalization() -> None:
    hook = _hook(path_globs=("src/**/*.py",))

    assert hook_matches_event(hook, _event(r".\src\.hidden\check.py"))


def test_positive_agent_name_globs_match_only_listed_agents() -> None:
    hook = _hook(agent_name_globs=("research.*.final", "bob"))

    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert hook_matches_event(hook, _event("report.md", agent="bob"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))


def test_negative_only_agent_name_globs_mean_everything_except() -> None:
    hook = _hook(agent_name_globs=("!research.*.cld", "!research.*.cdx"))

    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cdx"))
    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert hook_matches_event(hook, _event("report.md", agent="bbugyi200.athena.cld"))


def test_mixed_agent_name_globs_or_positives_then_apply_the_veto() -> None:
    hook = _hook(agent_name_globs=("research.*", "!research.*.cld"))

    assert hook_matches_event(hook, _event("report.md", agent="research.7.final"))
    assert not hook_matches_event(hook, _event("report.md", agent="research.7.cld"))
    assert not hook_matches_event(hook, _event("report.md", agent="bob"))


def test_unattributed_event_clears_only_negative_only_agent_globs() -> None:
    negative_only = _hook(agent_name_globs=("!research.*.cld",))
    with_positive = _hook(agent_name_globs=("research.*", "!research.*.cld"))

    assert hook_matches_event(negative_only, _event("report.md"))
    assert not hook_matches_event(with_positive, _event("report.md"))


def test_path_and_agent_name_filters_are_anded() -> None:
    hook = _hook(
        path_globs=("20*/**/*.md", "!20*/*/*__*.md"),
        agent_name_globs=("!research.*.cld", "!research.*.cdx"),
    )

    assert hook_matches_event(hook, _event("202608/foo.md", agent="research.7.final"))
    assert hook_matches_event(
        hook,
        _event("202608/foo/foo.md", agent="research.7.final"),
    )
    assert not hook_matches_event(hook, _event("202608/foo.md", agent="research.7.cld"))
    assert not hook_matches_event(
        hook,
        _event("202608/foo/foo__a.md", agent="research.7.final"),
    )


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


def test_project_sidecar_and_op_filters_and_unrestricted_defaults() -> None:
    restricted = _hook(
        projects=("sase",),
        sidecars=("research",),
        ops=("ADD",),
    )
    unrestricted = _hook()

    assert hook_matches_event(restricted, _event("report.md"))
    assert not hook_matches_event(restricted, _event("report.md", project="other"))
    assert not hook_matches_event(restricted, _event("report.md", sidecar="plans"))
    assert not hook_matches_event(restricted, _event("report.md", op="MODIFY"))
    assert hook_matches_event(
        unrestricted,
        _event("anything.txt", project="other", sidecar=None, op="REMOVE"),
    )


def test_non_user_causes_are_opt_in_while_user_still_matches() -> None:
    unrestricted = _hook()
    referenced_by = _hook(causes=("referenced_by",))

    assert hook_matches_event(unrestricted, _event("report.md", cause="user"))
    assert not hook_matches_event(
        unrestricted,
        _event("report.md", cause="referenced_by"),
    )
    assert hook_matches_event(
        referenced_by,
        _event("report.md", cause="referenced_by"),
    )
    assert hook_matches_event(referenced_by, _event("report.md", cause="user"))


@pytest.mark.parametrize(
    "producer",
    ["artifact", "commit", "sdd", "finalizer", "dispatch"],
)
def test_omitted_producers_filter_matches_every_producer(producer: str) -> None:
    hook = _hook()

    assert hook_matches_event(hook, _event("report.md"), producer=producer)


def test_explicit_producers_filter_is_anded_with_other_dimensions() -> None:
    hook = _hook(producers=("commit", "sdd", "finalizer"), ops=("ADD",))
    event = _event("report.md")

    assert hook_matches_event(hook, event, producer="commit")
    assert hook_matches_event(hook, event, producer="sdd")
    assert hook_matches_event(hook, event, producer="finalizer")
    assert not hook_matches_event(hook, event, producer="artifact")
    assert not hook_matches_event(hook, event, producer="dispatch")
    assert not hook_matches_event(hook, event)
    assert not hook_matches_event(
        hook,
        _event("report.md", op="MODIFY"),
        producer="commit",
    )


def test_match_events_applies_producer_filter() -> None:
    restricted = _hook(producers=("commit", "finalizer"))
    unrestricted = FileHookConfig(
        name="unrestricted",
        description=None,
        command="check-two",
        timeout_seconds=120,
        filters=FileHookFilters(),
    )
    events = [_event("one.md")]

    assert [
        (run.hook.name, run.event.rel_path)
        for run in match_events(
            [restricted, unrestricted],
            events,
            producer="artifact",
        )
    ] == [("unrestricted", "one.md")]
    assert [
        (run.hook.name, run.event.rel_path)
        for run in match_events(
            [restricted, unrestricted],
            events,
            producer="commit",
        )
    ] == [("test-hook", "one.md"), ("unrestricted", "one.md")]


def test_match_events_returns_hook_order_then_event_order() -> None:
    first = _hook(path_globs=("**/*.md",))
    second = FileHookConfig(
        name="second",
        description=None,
        command="check-two",
        timeout_seconds=120,
        filters=FileHookFilters(),
    )
    events = [_event("one.md"), _event("two.txt")]

    runs = match_events([first, second], events)

    assert [(run.hook.name, run.event.rel_path) for run in runs] == [
        ("test-hook", "one.md"),
        ("second", "one.md"),
        ("second", "two.txt"),
    ]
