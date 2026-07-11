"""Tests for provider-owned ``sase sdd init`` handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.sdd_handler import handle_sdd_command
from sase.workspace_provider import SddCompanionPreflight
from sase.sdd.store import SddMaterializationError, SddStore
from tests.main.sdd_handler_helpers import make_args, mark_tmp_path_as_project

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


class _Tty:
    def isatty(self) -> bool:
        return True


def _github_preflight(status: str = "not_found") -> SddCompanionPreflight:
    return SddCompanionPreflight(
        status=status,  # type: ignore[arg-type]
        provider="GitHub",
        host="github.com",
        repo="acme/widget--sdd",
        visibility="public",
    )


def _local_store(project: Path) -> SddStore:
    sdd_dir = project / ".sase" / "sdd"
    return SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)


def test_init_materializes_provider_store_without_changing_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Path, int]] = []

    def materialize(
        path: Path,
        workspace_num: int,
        *,
        sdd_creation_authorized: bool | None = None,
    ) -> SddStore:
        assert sdd_creation_authorized is False
        calls.append((path, workspace_num))
        return _local_store(path)

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", materialize)
    config = tmp_path / "sase.yml"
    original = "is_sase_managed: true\n"
    config.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert calls == [(tmp_path, 1)]
    assert config.read_text(encoding="utf-8") == original
    readme = tmp_path / ".sase" / "sdd" / "README.md"
    assert readme.is_file()
    assert str(readme) in capsys.readouterr().out


def test_init_preserves_existing_retired_config_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "sase.yml"
    original = (
        "is_sase_managed: true\nsdd:\n  storage: local\n  version_controlled: true\n"
    )
    config.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda path, workspace_num, **_options: _local_store(path),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == original


def test_init_fails_before_generating_files_when_materialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(
        _path: Path,
        _workspace_num: int,
        **_options: object,
    ) -> SddStore:
        raise SddMaterializationError("provider unavailable")

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", fail)
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert "provider unavailable" in capsys.readouterr().err
    assert not (tmp_path / ".sase" / "sdd").exists()


@pytest.mark.parametrize("answer", ["y", "YES", " yes "])
def test_missing_github_companion_requires_fresh_affirmative_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    calls: list[tuple[Path, int, bool | None]] = []
    prompts: list[str] = []
    store = _local_store(tmp_path)
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda root, workspace_num: _github_preflight(),
    )

    def materialize(
        root: Path,
        workspace_num: int,
        *,
        sdd_creation_authorized: bool | None = None,
    ) -> SddStore:
        calls.append((root, workspace_num, sdd_creation_authorized))
        return store

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", materialize)
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or answer

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert prompts == [
        "Create public GitHub SDD companion repository "
        "acme/widget--sdd on github.com? [y/N] "
    ]
    assert calls == [(tmp_path, 1, True)]


@pytest.mark.parametrize("answer", ["", "n", "no", "sure"])
def test_declined_github_creation_has_no_materialization_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
) -> None:
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda root, workspace_num: _github_preflight(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("decline must not materialize"),
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: answer

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 1
    assert "creation cancelled" in capsys.readouterr().err
    assert not (tmp_path / ".sase" / "sdd").exists()


@pytest.mark.parametrize("failure", [EOFError, KeyboardInterrupt])
def test_github_creation_input_failure_cancels_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: type[BaseException],
) -> None:
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda root, workspace_num: _github_preflight(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("cancel must not materialize"),
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()

    def fail(_prompt: str) -> str:
        raise failure

    args._init_input_func = fail

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 1
    assert "creation cancelled" in capsys.readouterr().err


def test_non_tty_and_bare_yes_cannot_authorize_github_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda root, workspace_num: _github_preflight(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("--yes must not materialize"),
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args.yes = True

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 1
    assert "interactive y/yes confirmation is required" in capsys.readouterr().err


def test_existing_github_companion_materializes_without_creation_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool | None] = []
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda root, workspace_num: _github_preflight("found"),
    )

    def materialize(
        _root: Path,
        _workspace_num: int,
        *,
        sdd_creation_authorized: bool | None = None,
    ) -> SddStore:
        calls.append(sdd_creation_authorized)
        return _local_store(tmp_path)

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", materialize)
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert calls == [False]


def test_existing_materialized_record_skips_preflight_but_remains_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool | None] = []
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: None,
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda *_args: pytest.fail("existing record must not probe the network"),
    )

    def materialize(
        _root: Path,
        _workspace_num: int,
        *,
        sdd_creation_authorized: bool | None = None,
    ) -> SddStore:
        calls.append(sdd_creation_authorized)
        return _local_store(tmp_path)

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", materialize)
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert calls == [False]


def test_missing_preflight_support_fails_closed_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._plan_sdd_companion_repo_action",
        lambda _root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "sase.sdd.store.preflight_sdd_companion",
        lambda *_args: (_ for _ in ()).throw(
            SddMaterializationError("Update the provider plugin")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("must fail before materialization"),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert "Update the provider plugin" in capsys.readouterr().err
