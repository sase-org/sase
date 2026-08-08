"""Tests for file-hook config loading and event matching."""

from __future__ import annotations

import logging
from typing import Any

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookEvent,
    _load_file_hooks,
    get_all_file_hooks,
    hook_matches_event,
    match_events,
)
from sase.config.layers import ConfigLayer


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
) -> FileHookConfig:
    return FileHookConfig(
        name="test-hook",
        description=None,
        command="check",
        projects=projects,
        sidecars=sidecars,
        path_globs=path_globs,
        agent_name_globs=agent_name_globs,
        ops=ops,  # type: ignore[arg-type]
        timeout_seconds=120,
    )


def _event(
    path: str,
    *,
    project: str = "sase",
    sidecar: str | None = "research",
    op: str = "ADD",
    agent: str | None = None,
) -> FileHookEvent:
    return FileHookEvent(
        project=project,
        repo_kind=f"sidecar:{sidecar}" if sidecar else "primary",
        sidecar_role=sidecar,
        rel_path=path,
        op=op,  # type: ignore[arg-type]
        agent_name=agent,
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
                    "projects": ["other"],
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

    assert hooks[0].projects == ("sase",)
    assert hooks[1].projects == ("other",)


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
                    "name": "modern",
                    "command": "run",
                    "path_globs": ["20*/**/*.md", "!20*/*/*__*.md"],
                    "agent_name_globs": ["!research.*.cld"],
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
    assert "'globs' was renamed to 'path_globs'" in caplog.text
    assert "unknown field(s): agent_globs" in caplog.text
    assert hooks[0].path_globs == ("20*/**/*.md", "!20*/*/*__*.md")
    assert hooks[0].agent_name_globs == ("!research.*.cld",)


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


def test_match_events_returns_hook_order_then_event_order() -> None:
    first = _hook(path_globs=("**/*.md",))
    second = FileHookConfig(
        name="second",
        description=None,
        command="check-two",
        projects=None,
        sidecars=None,
        path_globs=None,
        agent_name_globs=None,
        ops=None,
        timeout_seconds=120,
    )
    events = [_event("one.md"), _event("two.txt")]

    runs = match_events([first, second], events)

    assert [(run.hook.name, run.event.rel_path) for run in runs] == [
        ("test-hook", "one.md"),
        ("second", "one.md"),
        ("second", "two.txt"),
    ]
