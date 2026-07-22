"""Machine-identity config initializer coverage."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import pytest

from sase.config import core as config_core
from sase.core.paths import machine_name_path
from sase.main import config_init_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _args(*answers: str, check: bool = False) -> argparse.Namespace:
    values = iter(answers)
    return argparse.Namespace(
        command="config",
        config_subcommand="init",
        check=check,
        _init_stdin=_TtyStringIO(),
        _init_input_func=lambda _prompt: next(values),
    )


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Path,
    *,
    use_chezmoi: bool = False,
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: use_chezmoi)
    monkeypatch.setattr(
        config_init_handler,
        "_machine_hood_collisions",
        lambda _name: (),
    )


def test_run_config_init_creates_overlay_and_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)

    assert config_init_handler.run_config_init(_args("athena")) == 0

    assert (config_dir / "sase_athena.yml").read_text() == "machine_name: athena\n"
    assert machine_name_path().read_text() == "athena\n"


def test_run_config_init_minimally_splices_existing_ordinary_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)
    overlay = config_dir / "sase_athena.yml"
    overlay.write_text("# keep this comment\nuse_chezmoi: false\n", encoding="utf-8")

    assert config_init_handler.run_config_init(_args("athena")) == 0

    assert overlay.read_text() == (
        "# keep this comment\nuse_chezmoi: false\nmachine_name: athena\n"
    )


def test_run_config_init_selects_existing_overlay_without_editing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)
    overlay = config_dir / "sase_athena.yml"
    original = "# existing\nmachine_name: athena\nvalue: 1\n"
    overlay.write_text(original, encoding="utf-8")

    assert config_init_handler.run_config_init(_args("athena")) == 0

    assert overlay.read_text() == original
    assert machine_name_path().read_text() == "athena\n"


def test_run_config_init_reprompts_and_accepts_sanitized_hostname_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)
    monkeypatch.setattr(config_init_handler.socket, "gethostname", lambda: "Host-1")

    assert config_init_handler.run_config_init(_args("bad-name", "")) == 0

    assert machine_name_path().read_text() == "host__\n"
    assert "Invalid machine name" in capsys.readouterr().err


def test_run_config_init_refuses_non_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path / "config")
    args = argparse.Namespace(check=False, _init_stdin=StringIO())

    assert config_init_handler.run_config_init(args) == 1
    assert "requires an interactive TTY" in capsys.readouterr().err


def test_run_config_init_requires_default_no_registry_collision_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)
    monkeypatch.setattr(
        config_init_handler,
        "_machine_hood_collisions",
        lambda _name: ("athena.worker",),
    )

    assert config_init_handler.run_config_init(_args("athena", "")) == 1
    assert not machine_name_path().exists()

    assert config_init_handler.run_config_init(_args("athena", "yes")) == 0
    assert machine_name_path().read_text() == "athena\n"


def test_run_config_init_surfaces_write_failure_and_clears_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare(monkeypatch, tmp_path / "config")
    clears: list[None] = []
    monkeypatch.setattr(
        config_core,
        "clear_config_cache",
        lambda: clears.append(None),
    )
    monkeypatch.setattr(
        config_init_handler,
        "_write_machine_selector",
        lambda _name: (_ for _ in ()).throw(OSError("read-only state")),
    )

    assert config_init_handler.run_config_init(_args("athena")) == 1
    assert clears == [None]
    assert "read-only state" in capsys.readouterr().err


def test_run_config_init_is_idempotent_when_selector_and_overlay_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)
    (config_dir / "sase_athena.yml").write_text(
        "machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")
    args = argparse.Namespace(check=False, _init_stdin=StringIO())

    assert config_init_handler.run_config_init(args) == 0


def test_plan_config_init_reports_missing_and_current_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _prepare(monkeypatch, config_dir)

    missing = config_init_handler.plan_config_init(argparse.Namespace())
    assert missing.command == "config"
    assert missing.label == "Config"
    assert len(missing.actions) == 1
    assert missing.actions[0].path == machine_name_path()

    (config_dir / "sase_athena.yml").write_text(
        "machine_name: athena\n", encoding="utf-8"
    )
    machine_name_path().write_text("athena\n", encoding="utf-8")
    config_core.clear_config_cache()
    current = config_init_handler.plan_config_init(argparse.Namespace())
    assert current.actions == ()
    assert "athena" in current.summary


def test_new_chezmoi_overlay_uses_direct_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    source = tmp_path / "chezmoi" / "home" / "dot_config" / "sase" / "sase_athena.yml"
    _prepare(monkeypatch, config_dir, use_chezmoi=True)
    monkeypatch.setattr(
        config_init_handler,
        "resolve_write_path",
        lambda _path, *, use_chezmoi: source if use_chezmoi else None,
    )
    deployed: list[Path] = []

    def _deploy(paths, _behavior) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(config_init_handler, "deploy_to_chezmoi", _deploy)

    assert config_init_handler.run_config_init(_args("athena")) == 0
    assert source.read_text() == "machine_name: athena\n"
    assert deployed == [source]


def test_new_chezmoi_overlay_joins_deferred_bare_init_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    source = tmp_path / "chezmoi" / "home" / "dot_config" / "sase" / "sase_athena.yml"
    _prepare(monkeypatch, config_dir, use_chezmoi=True)
    monkeypatch.setattr(
        config_init_handler,
        "resolve_write_path",
        lambda _path, *, use_chezmoi: source if use_chezmoi else None,
    )
    monkeypatch.setattr(
        config_init_handler,
        "deploy_to_chezmoi",
        lambda *_args, **_kwargs: pytest.fail("direct deploy should be deferred"),
    )

    with defer_chezmoi_deploy() as deferred:
        assert config_init_handler.run_config_init(_args("athena")) == 0

    assert deferred.paths == [source]
