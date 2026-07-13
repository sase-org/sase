"""Tests for provider-owned ``sase sdd init`` handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.main.sdd_handler import handle_sdd_command
from sase.workspace_provider import SddSidecarPreflight
from sase.sdd.store import SddMaterializationError, SddStore
from tests.main.sdd_handler_helpers import make_args, mark_tmp_path_as_project

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


class _Tty:
    def isatty(self) -> bool:
        return True


def _github_preflight(
    status: str = "not_found", kind: str = "plans"
) -> SddSidecarPreflight:
    return SddSidecarPreflight(
        status=status,  # type: ignore[arg-type]
        provider="GitHub",
        host="github.com",
        repo=f"acme/widget--{kind}",
        visibility="public",
    )


def _local_store(project: Path) -> SddStore:
    sdd_dir = project / ".sase" / "sdd"
    return SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)


def _split_store(project: Path) -> SddStore:
    plans = project / "sase" / "repos" / "plans"
    research = project / "sase" / "repos" / "research"
    return SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="plans-remote",
        research_dir=research,
        research_remote_url="research-remote",
    )


def _split_preflights(status: str = "not_found") -> dict[str, SddSidecarPreflight]:
    return {kind: _github_preflight(status, kind) for kind in ("plans", "research")}


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
def test_missing_github_sidecar_requires_fresh_affirmative_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    calls: list[tuple[Path, int, dict[str, bool] | None]] = []
    prompts: list[str] = []
    store = _split_store(tmp_path)
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda root, workspace_num: _split_preflights(),
    )

    def initialize(
        root: Path,
        workspace_num: int,
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> SimpleNamespace:
        calls.append((root, workspace_num, creation_authorized))
        return SimpleNamespace(store=store)

    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars", initialize
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda prompt: prompts.append(prompt) or answer

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert prompts == [
        "Create public GitHub SDD sidecar repository "
        "acme/widget--plans on github.com? [y/N] ",
        "Create public GitHub SDD sidecar repository "
        "acme/widget--research on github.com? [y/N] ",
    ]
    assert calls == [(tmp_path, 1, {"plans": True, "research": True})]


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
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda root, workspace_num: _split_preflights(),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars",
        lambda *_args, **_kwargs: pytest.fail("decline must not materialize"),
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: answer

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 1
    assert "creation cancelled" in capsys.readouterr().err
    assert not (tmp_path / "sase" / "repos").exists()


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
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda root, workspace_num: _split_preflights(),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars",
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
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda root, workspace_num: _split_preflights(),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars",
        lambda *_args, **_kwargs: pytest.fail("--yes must not materialize"),
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args.yes = True

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 1
    assert "interactive y/yes confirmation is required" in capsys.readouterr().err


def test_existing_github_sidecar_materializes_without_creation_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, bool] | None] = []
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda root, workspace_num: _split_preflights("found"),
    )

    def initialize(
        _root: Path,
        _workspace_num: int,
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> SimpleNamespace:
        calls.append(creation_authorized)
        return SimpleNamespace(store=_split_store(tmp_path))

    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars", initialize
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert calls == [{}]


def test_existing_materialized_record_skips_preflight_but_remains_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, bool] | None] = []
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.sdd_handler._split_sidecar_provider_setup_needed",
        lambda _root: False,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda *_args: pytest.fail("existing record must not probe the network"),
    )

    def initialize(
        _root: Path,
        _workspace_num: int,
        *,
        creation_authorized: dict[str, bool] | None = None,
    ) -> SimpleNamespace:
        calls.append(creation_authorized)
        return SimpleNamespace(store=_split_store(tmp_path))

    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars", initialize
    )
    args = make_args(sdd_subcommand="init", path=str(tmp_path))
    args._init_stdin = _Tty()
    args._init_input_func = lambda _prompt: pytest.fail("must not prompt")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert calls == [{}]


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
        "sase.sdd._sidecar_init.preflight_split_sdd_sidecars",
        lambda *_args: (_ for _ in ()).throw(
            SddMaterializationError("Update the provider plugin")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_split_sdd_sidecars",
        lambda *_args, **_kwargs: pytest.fail("must fail before materialization"),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert "Update the provider plugin" in capsys.readouterr().err
