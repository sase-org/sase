"""Tests for ``sase repo init`` handling."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import pytest

from sase.main.repo_init_handler import run_repo_init
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.main.repo_init_handler import plan_repo_init
from sase.main.sdd_handler import handle_sdd_command
from sase.sdd._sidecar_init import _SidecarInitOutcome, SidecarInitSpec
from sase.sdd.store import SddMaterializationError, SddStore
from sase.workspace_provider import SddSidecarPreflight
from tests.main.sdd_handler_helpers import make_args


class _Tty:
    def isatty(self) -> bool:
        return True


def _args(path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "check": False,
        "diff": False,
        "no_commit": True,
        "path": str(path),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def _mark_managed_project(path: Path, config: str = "is_sase_managed: true\n") -> None:
    _git_init(path)
    (path / "sase.yml").write_text(config, encoding="utf-8")


def _preflight(
    role: str,
    *,
    status: str = "not_found",
    visibility: str = "public",
    repo: str | None = None,
) -> SddSidecarPreflight:
    return SddSidecarPreflight(
        status=status,  # type: ignore[arg-type]
        provider="GitHub",
        host="github.com",
        repo=repo or f"acme/widget--{role}",
        visibility=visibility,
    )


def _outcome(path: Path, specs: tuple[SidecarInitSpec, ...]) -> _SidecarInitOutcome:
    return _SidecarInitOutcome(
        store=None,
        record=None,
        created=frozenset(),
        roots={spec.role: path / "sase" / "repos" / spec.role for spec in specs},
    )


def test_repo_init_writes_plans_config_local_store_and_gitignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path, "# keep\nis_sase_managed: true\n")
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )

    assert run_repo_init(_args(tmp_path)) == 0

    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    - name: plans\n"
        "      auto_clone: true\n"
    )
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "/sase/repos/\n"
    assert (store_root / "README.md").is_file()


def test_bare_init_enable_management_also_writes_plans_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_init(tmp_path)
    monkeypatch.chdir(tmp_path)
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )
    args = argparse.Namespace(
        all=False,
        check=False,
        diff=False,
        enable_project_memory=True,
        no_commit=True,
        yes=True,
    )
    spec = InitCommandSpec("repo", "Repos", plan_repo_init, run_repo_init)

    assert run_init_onboarding(args, specs=(spec,)) == 0

    config = (tmp_path / "sase.yml").read_text(encoding="utf-8")
    assert "is_sase_managed: true" in config
    assert "name: plans" in config


def test_repo_init_appends_plans_without_losing_sidecar_comments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(
        tmp_path,
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    - name: research # shared\n"
        "      disabled: true\n",
    )
    root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", root, root),
    )

    assert run_repo_init(_args(tmp_path)) == 0

    text = (tmp_path / "sase.yml").read_text(encoding="utf-8")
    assert "# keep" in text
    assert "name: research # shared" in text
    assert text.count("name: plans") == 1


def test_repo_init_commits_only_owned_project_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "sase.yml"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
    )
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("leave me alone\n", encoding="utf-8")
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )
    monkeypatch.setattr(
        "sase.main.init_workspace_handler.run_before_commit_hook",
        lambda _root: True,
    )

    assert run_repo_init(_args(tmp_path, no_commit=False)) == 0

    subject = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    names = subprocess.run(
        ["git", "-C", str(tmp_path), "show", "--format=", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert subject == "chore: initialize SASE repositories"
    assert names == [".gitignore", "sase.yml"]
    assert unrelated.exists()


@pytest.mark.parametrize("answer", ["y", "YES", " yes "])
def test_missing_custom_private_sidecar_requires_fresh_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    _mark_managed_project(tmp_path)
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
            "artifacts": _preflight(
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
    ) -> _SidecarInitOutcome:
        calls.append(creation_authorized)
        return _outcome(tmp_path, specs)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = _args(tmp_path)
    args._init_stdin = _Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or answer

    assert run_repo_init(args) == 0
    assert prompts == [
        "Create private GitHub sidecar repository "
        "acme/shared-artifacts on github.com? [y/N] "
    ]
    assert calls == [{"artifacts": True}]


@pytest.mark.parametrize("answer", ["", "n", "no", "sure"])
def test_declined_sidecar_creation_does_not_materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    _mark_managed_project(tmp_path)
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
        lambda *_args: {"plans": _preflight("plans")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("decline must not materialize"),
    )
    args = _args(tmp_path)
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: answer

    assert run_repo_init(args) == 1
    assert "creation cancelled" in capsys.readouterr().err
    assert not (tmp_path / "sase" / "repos").exists()


def test_non_tty_and_yes_cannot_authorize_sidecar_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_managed_project(tmp_path)
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
        lambda *_args: {"plans": _preflight("plans")},
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("--yes must not materialize"),
    )
    args = _args(tmp_path)
    args.yes = True

    assert run_repo_init(args) == 1
    assert "interactive y/yes confirmation is required" in capsys.readouterr().err


def test_existing_sidecar_initializes_without_creation_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
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
        lambda *_args: {"plans": _preflight("plans", status="found")},
    )

    def initialize(
        _root: Path,
        _workspace: int,
        _specs: tuple[SidecarInitSpec, ...],
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> _SidecarInitOutcome:
        calls.append(creation_authorized)
        return _outcome(tmp_path, specs)

    monkeypatch.setattr("sase.sdd._sidecar_init.initialize_sidecars", initialize)
    args = _args(tmp_path)
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    assert run_repo_init(args) == 0
    assert calls == [{}]


def test_materialized_store_refreshes_present_sidecars_and_preserves_lazy_ones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research"))
    plans_root = tmp_path / "sase" / "repos" / "plans"
    (plans_root / ".git").mkdir(parents=True)
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._has_materialized_sidecar_store",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._materialized_compatibility_roles",
        lambda _root: frozenset({"plans", "research"}),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_materialized_sidecars",
        lambda _root, selected: (
            seen.append(tuple(spec.role for spec in selected)) or {"plans": plans_root}
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("must preserve the sidecar store"),
    )

    assert run_repo_init(_args(tmp_path)) == 0
    assert seen == [("plans",)]


def test_preflight_unavailable_fails_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_managed_project(tmp_path)
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
        lambda *_args: (_ for _ in ()).throw(
            SddMaterializationError("Update the provider plugin")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("must fail before materialization"),
    )

    assert run_repo_init(_args(tmp_path)) == 1
    assert "Update the provider plugin" in capsys.readouterr().err


def test_repo_init_check_is_read_only_and_does_not_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: (SidecarInitSpec(role="plans"),),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: pytest.fail("check must not probe the network"),
    )

    before = (tmp_path / "sase.yml").read_text(encoding="utf-8")
    assert run_repo_init(_args(tmp_path, check=True)) == 1
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == before
    assert not (tmp_path / ".gitignore").exists()


def test_sdd_init_compatibility_command_delegates_to_repo_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler.run_repo_init",
        lambda args: seen.append(args) or 7,
    )
    args = make_args(sdd_subcommand="init")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 7
    assert seen == [args]
