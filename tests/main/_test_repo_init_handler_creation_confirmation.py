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

import argparse
from io import StringIO

from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec


@pytest.mark.parametrize("answer", ["y", "YES", " yes "])
def test_missing_custom_private_sidecar_requires_fresh_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    mark_managed_project(tmp_path)
    specs = (
        SidecarInitSpec(
            role="artifacts",
            repo="acme/shared-artifacts",
            visibility="private",
        ),
    )
    prompts: list[str] = []
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
        lambda *_args: {
            "artifacts": make_preflight(
                "artifacts",
                visibility="private",
                repo="acme/shared-artifacts",
            )
        },
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
    args._init_input_func = lambda prompt: prompts.append(prompt) or answer

    assert run_repo_init(args) == 0
    assert prompts == [
        "Create private GitHub sidecar repository "
        "acme/shared-artifacts on github.com? [y/N] "
    ]
    assert calls == [{"artifacts": True}]


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_missing_agents_sidecar_requires_loud_role_specific_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    visibility: str,
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(
            role="agents",
            repo="acme/widget--agents",
            visibility=visibility,
        ),
    )
    prompts: list[str] = []
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
        lambda *_args: {
            "agents": make_preflight("agents", visibility=visibility),
        },
    )

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        assert selected == specs
        calls.append(creation_authorized)
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, selected)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or "yes"

    assert run_repo_init(args) == 0
    assert calls == [{"agents": True}]
    prompt = prompts[0]
    assert "PUBLISH SASE agent data" in prompt
    assert "active prompts, waiting, failed, terminal, and dismissed runs" in prompt
    assert "allowlisted metadata, commit associations" in prompt
    assert "refresh the same runs with newly available transcripts" in prompt
    assert f"Repository visibility: {visibility.upper()}." in prompt
    assert "visibility: private" in prompt
    assert "disabled: true" in prompt
    assert f"Create {visibility} GitHub agents sidecar repository" in prompt


@pytest.mark.parametrize(
    "response",
    [
        "",
        "no",
        pytest.param(EOFError(), id="eof"),
        pytest.param(KeyboardInterrupt(), id="interrupt"),
    ],
)
def test_declined_agents_sidecar_continues_other_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: str | BaseException,
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="agents"))
    calls: list[tuple[tuple[str, ...], dict[str, bool] | None]] = []
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
            "plans": make_preflight("plans", status="found"),
            "agents": make_preflight("agents"),
        },
    )

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        calls.append((tuple(spec.role for spec in selected), creation_authorized))
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, selected)

    def answer(_prompt: str) -> str:
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = answer

    assert run_repo_init(args) == 0
    assert calls == [(("plans",), {})]
    stderr = capsys.readouterr().err
    assert "continuing without the agents sidecar" in stderr


@pytest.mark.parametrize(
    "response",
    [
        "",
        "no",
        pytest.param(EOFError(), id="eof"),
        pytest.param(KeyboardInterrupt(), id="interrupt"),
    ],
)
def test_declined_attachments_private_sidecar_continues_other_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: str | BaseException,
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(
            role="attachments-private",
            repo="acme/widget--attachments-private",
            visibility="private",
        ),
    )
    prompts: list[str] = []
    calls: list[tuple[tuple[str, ...], dict[str, bool] | None]] = []
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
            "plans": make_preflight("plans", status="found"),
            "attachments-private": make_preflight(
                "attachments-private",
                visibility="private",
            ),
        },
    )

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
        publish_sidecar_changes: bool = True,
    ) -> Any:
        calls.append((tuple(spec.role for spec in selected), creation_authorized))
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, selected)

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = answer

    assert run_repo_init(args) == 0
    assert calls == [(("plans",), {})]
    assert prompts and "PRIVATE" in prompts[0]
    assert "private bead attachment bytes" in prompts[0]
    stderr = capsys.readouterr().err
    assert "continuing without the attachments-private sidecar" in stderr


def test_non_tty_refuses_only_agents_creation_and_explains_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_managed_project(tmp_path)
    patch_agents_project_key(tmp_path, monkeypatch)
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="agents"))
    calls: list[tuple[str, ...]] = []
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
            "plans": make_preflight("plans", status="found"),
            "agents": make_preflight("agents"),
        },
    )

    def initialize(
        _root: Path,
        _workspace: int,
        selected: tuple[SidecarInitSpec, ...],
        *,
        publish_sidecar_changes: bool = True,
        **_kwargs: object,
    ) -> Any:
        calls.append(tuple(spec.role for spec in selected))
        assert publish_sidecar_changes is False
        return sidecar_outcome(tmp_path, selected)

    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        initialize,
    )

    assert run_repo_init(make_args(tmp_path, yes=True)) == 0
    assert calls == [("plans",)]
    stderr = capsys.readouterr().err
    assert "interactive y/yes confirmation is required" in stderr
    assert "run `sase repo init` interactively" in stderr
    assert "continuing without the agents sidecar" in stderr


@pytest.mark.parametrize("answer", ["", "n", "no", "sure"])
def test_declined_sidecar_creation_does_not_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"),)
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
        lambda *_args: {"plans": make_preflight("plans")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("decline must not materialize"),
    )
    args = make_args(tmp_path)
    args._init_stdin = Tty()
    args._init_input_func = lambda _prompt: answer

    assert run_repo_init(args) == 1
    assert "creation cancelled" in capsys.readouterr().err
    assert not (tmp_path / "sase" / "repos").exists()


def test_non_tty_and_yes_cannot_authorize_sidecar_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"),)
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
        lambda *_args: {"plans": make_preflight("plans")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("--yes must not materialize"),
    )
    args = make_args(tmp_path)
    args.yes = True

    assert run_repo_init(args) == 1
    assert "interactive y/yes confirmation is required" in capsys.readouterr().err


def test_noninteractive_bare_init_defers_missing_sidecar_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mark_managed_project(tmp_path)
    specs = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(role="research"),
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
            "plans": make_preflight("plans", status="found"),
            "research": make_preflight("research"),
        },
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail(
            "onboarding must defer missing remote creation"
        ),
    )
    args = argparse.Namespace(
        all=False,
        check=False,
        diff=False,
        enable_project_memory=False,
        no_commit=True,
        path=str(tmp_path),
        yes=True,
    )
    spec = InitCommandSpec("repo", "Repos", plan_repo_init, run_repo_init)

    assert run_init_onboarding(args, specs=(spec,), stdin=StringIO()) == 0

    config = (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8")
    stderr = capsys.readouterr().err
    assert "      research:\n" in config
    assert "acme/widget--research is missing" in stderr
    assert "run `sase repo init` interactively" in stderr
