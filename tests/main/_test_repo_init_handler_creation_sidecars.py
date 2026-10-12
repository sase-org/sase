"""Tests for repo-init sidecar creation behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main.repo_init_handler import plan_repo_init, run_repo_init
from sase.sdd._sidecar_init import SidecarInitSpec
from tests.main._repo_init_handler_creation_helpers import (
    Tty,
    make_args,
    mark_managed_project,
    patch_agents_project_key,
    make_preflight,
    sidecar_outcome,
)


def test_existing_sidecar_initializes_without_creation_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"),)
    calls: list[dict[str, bool] | None] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {"plans": make_preflight("plans", status="found")},
    )

    def initialize(
        _root: Path,
        _workspace: int,
        _specs: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        calls.append(creation_authorized)
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, specs)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    assert run_repo_init(args) == 0
    assert calls == [{}]


def test_public_sidecar_prompt_defaults_yes_and_names_public(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(
            role="attachments", repo="acme/widget--attachments", visibility="public"
        ),
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {
            "attachments": make_preflight("attachments", visibility="public")
        },
    )
    monkeypatch.setattr(
        "sase.bead.attachments.remote_visibility.resolve_remote_visibility",
        lambda _url: "public",
    )
    monkeypatch.setattr(
        "sase.main._repo_init_sidecars._beads_remote_for_public_probe",
        lambda: "https://github.com/acme/widget--beads.git",
    )

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        assert creation_authorized == {"attachments": True}
        return sidecar_outcome(tmp_path, selected)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or ""
    assert run_repo_init(args) == 0
    assert prompts and "Repository visibility: PUBLIC." in prompts[0]
    assert "[Y/n]" in prompts[0]


def test_public_sidecar_refused_when_beads_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(
            role="attachments", repo="acme/widget--attachments", visibility="public"
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {
            "attachments": make_preflight("attachments", visibility="public")
        },
    )
    monkeypatch.setattr(
        "sase.bead.attachments.remote_visibility.resolve_remote_visibility",
        lambda _url: "private",
    )
    monkeypatch.setattr(
        "sase.main._repo_init_sidecars._beads_remote_for_public_probe",
        lambda: "https://github.com/acme/widget--beads.git",
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda _r, _w, selected, **_k: sidecar_outcome(tmp_path, selected),
    )
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda prompt: ""
    assert run_repo_init(args) == 0
    stderr = capsys.readouterr().err
    assert "repos.sidecar.builtin.beads.visibility: private" in stderr


def test_private_primary_forces_private_sidecar_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.sdd._sidecar_visibility import PrimaryRepoVisibility

    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(role="plans", repo="acme/widget--plans", visibility="public"),
        SidecarInitSpec(
            role="attachments",
            repo="acme/widget--attachments",
            visibility="public",
        ),
    )
    preflight_specs: list[tuple[SidecarInitSpec, ...]] = []
    selected: list[tuple[SidecarInitSpec, ...]] = []
    prompts: list[str] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
    )

    def preflight(
        _root: Path, _workspace: int, received: tuple[SidecarInitSpec, ...]
    ) -> dict[str, object]:
        preflight_specs.append(received)
        return {
            spec.role: make_preflight(spec.role, visibility="private")
            for spec in received
        }

    monkeypatch.setattr("sase.sdd._sidecar_init.preflight_sidecars", preflight)

    def initialize(
        _root: Path,
        _workspace: int,
        received: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        selected.append(received)
        assert creation_authorized == {"plans": True}
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, received)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or "y"

    assert run_repo_init(args) == 0

    assert preflight_specs
    assert {spec.role for spec in preflight_specs[0]} == {"plans"}
    assert all(spec.visibility == "private" for spec in preflight_specs[0])
    assert prompts == [
        "Create private GitHub sidecar repository "
        "acme/widget--plans on github.com? [y/N] "
    ]
    assert [spec.role for spec in selected[0]] == ["plans"]
    stderr = capsys.readouterr().err
    assert (
        stderr.count(
            "note: acme/widget is private, so SASE creates its sidecar "
            "repositories as private"
        )
        == 1
    )
    assert "skipping the public attachments sidecar" in stderr
    assert "visibility: private" in (tmp_path / "sase" / "sase.yml").read_text(
        encoding="utf-8"
    )


def test_private_primary_rerun_without_missing_sidecars_stays_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.sdd._sidecar_visibility import PrimaryRepoVisibility

    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(role="plans", repo="acme/widget--plans", visibility="private"),
        SidecarInitSpec(
            role="agents", repo="acme/widget--agents", visibility="private"
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {
            "plans": make_preflight("plans", status="found", visibility="private"),
            "agents": make_preflight("agents", status="found", visibility="private"),
        },
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda _r, _w, received, **_k: sidecar_outcome(tmp_path, received),
    )
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    assert run_repo_init(args) == 0
    assert "note:" not in capsys.readouterr().err


def test_unverifiable_primary_creates_private_sidecars_without_config_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd._sidecar_visibility import PrimaryRepoVisibility

    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(role="plans", repo="acme/widget--plans", visibility="public"),
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: PrimaryRepoVisibility(repo="acme/widget", visibility="unknown"),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: {"plans": make_preflight("plans", visibility="private")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda _r, _w, received, **_k: sidecar_outcome(tmp_path, received),
    )
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or "y"

    assert run_repo_init(args) == 0
    assert prompts == [
        "Create private GitHub sidecar repository "
        "acme/widget--plans on github.com? [y/N] "
    ]
    assert "visibility" not in (tmp_path / "sase" / "sase.yml").read_text(
        encoding="utf-8"
    )


def test_private_primary_plan_declares_private_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd._sidecar_visibility import PrimaryRepoVisibility

    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(role="plans", repo="acme/widget--plans", visibility="public"),
        SidecarInitSpec(
            role="agents",
            repo="acme/widget--agents",
            visibility="public",
            description="Commit-associated agents.",
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._primary_repo_visibility",
        lambda _root: PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
    )

    plan = plan_repo_init(make_args(tmp_path))

    config_action = next(
        action for action in plan.actions if action.path.name == "sase.yml"
    )
    assert config_action.new_content is not None
    assert "visibility: private" in config_action.new_content
    assert "(private: acme/widget is private)" in config_action.detail
    agents_connection = next(
        action
        for action in plan.actions
        if "agents sidecar repository" in action.detail
    )
    assert "with private visibility" in agents_connection.detail
    assert all(
        "attachments sidecar repository" not in action.detail for action in plan.actions
    )
