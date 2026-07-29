"""End-to-end coverage for config-init chezmoi overlay deployment."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import subprocess

import pytest

from sase.config import core as config_core
from sase.main import config_init_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _args(*answers: str) -> argparse.Namespace:
    values = iter(answers)
    return argparse.Namespace(
        command="config",
        config_subcommand="init",
        check=False,
        no_apply=True,
        _init_stdin=_TtyStringIO(),
        _init_input_func=lambda _prompt: next(values),
    )


def _prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    use_chezmoi: bool = True,
) -> tuple[Path, Path, Path]:
    config_dir = tmp_path / "config"
    chezmoi_root = tmp_path / "chezmoi"
    chezmoi_home = chezmoi_root / "home"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: use_chezmoi)
    monkeypatch.setattr(
        config_init_handler,
        "_machine_hood_collisions",
        lambda _name: (),
    )
    monkeypatch.setattr(
        config_init_handler,
        "chezmoi_hostname",
        lambda: "Kellys-MBP",
    )

    def _resolve(path: str, *, use_chezmoi: bool) -> Path:
        target = Path(path)
        if not use_chezmoi:
            return target
        return chezmoi_home / "dot_config" / "sase" / target.name

    monkeypatch.setattr(config_init_handler, "resolve_write_path", _resolve)
    return config_dir, chezmoi_root, chezmoi_home


def _capture_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Path]:
    deployed: list[Path] = []

    def _deploy(paths, _behavior) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(config_init_handler, "deploy_to_chezmoi", _deploy)
    return deployed


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def test_applied_identity_materializes_missing_chezmoi_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    applied = config_dir / "sase_kellys_mbp.yml"
    original = "id:\n  username: alice\n  machine_name: kellys_mbp\n"
    applied.write_text(original, encoding="utf-8")
    deployed = _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp")) == 0

    source = chezmoi_home / "dot_config" / "sase" / applied.name
    assert source.read_text() == original
    assert deployed == [source, chezmoi_home / ".chezmoiignore"]


def test_real_deploy_stages_overlay_and_ignore_in_one_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir, chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    chezmoi_home.mkdir(parents=True)
    _run_git(chezmoi_root, "init")
    _run_git(chezmoi_root, "config", "user.email", "tests@example.com")
    _run_git(chezmoi_root, "config", "user.name", "SASE Tests")
    _run_git(chezmoi_root, "config", "core.hooksPath", "/dev/null")
    seed = chezmoi_root / "README.md"
    seed.write_text("seed\n", encoding="utf-8")
    _run_git(chezmoi_root, "add", "README.md")
    _run_git(chezmoi_root, "commit", "-m", "test: seed repository")

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    tracked = set(_run_git(chezmoi_root, "ls-files").stdout.splitlines())
    expected_paths = {
        "home/dot_config/sase/sase_kellys_mbp.yml",
        "home/.chezmoiignore",
    }
    assert expected_paths <= tracked
    committed = _run_git(
        chezmoi_root,
        "show",
        "--stat",
        "--format=",
        "HEAD",
    ).stdout
    assert all(path in committed for path in expected_paths)
    assert "no upstream configured; skipping pull/push" in capsys.readouterr().out


def test_missing_chezmoiignore_is_created_with_exact_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    assert (chezmoi_home / ".chezmoiignore").read_text() == (
        '{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
        ".config/sase/sase_kellys_mbp.yml\n"
        "{{ end }}\n"
    )


def test_existing_chezmoiignore_stanzas_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    existing = (
        "tags\n"
        '{{ if ne .chezmoi.fqdnHostname "bbugyi.c.googlers.com" }}\n'
        ".config/sase/sase_work.yml\n"
        "{{ end }}\n"
        '{{ if ne .chezmoi.hostname "athena" }}\n'
        ".config/sase/sase_athena.yml\n"
        "{{ end }}\n"
    )
    chezmoi_home.mkdir(parents=True)
    (chezmoi_home / ".chezmoiignore").write_text(existing, encoding="utf-8")
    _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    assert (chezmoi_home / ".chezmoiignore").read_text() == (
        f"{existing}"
        '{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
        ".config/sase/sase_kellys_mbp.yml\n"
        "{{ end }}\n"
    )


def test_existing_overlay_entry_is_left_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    existing = (
        '{{ if ne .chezmoi.fqdnHostname "legacy.example.test" }}\n'
        "  .config/sase/sase_kellys_mbp.yml  \n"
        "{{ end }}\n"
    )
    chezmoi_home.mkdir(parents=True)
    ignore_path = chezmoi_home / ".chezmoiignore"
    ignore_path.write_text(existing, encoding="utf-8")
    deployed = _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    source = chezmoi_home / "dot_config" / "sase" / "sase_kellys_mbp.yml"
    assert ignore_path.read_text() == existing
    assert ignore_path.read_text().count(".config/sase/sase_kellys_mbp.yml") == 1
    assert deployed == [source]


def test_deferred_bare_init_collects_overlay_and_ignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        config_init_handler,
        "deploy_to_chezmoi",
        lambda *_args, **_kwargs: pytest.fail("direct deploy should be deferred"),
    )

    with defer_chezmoi_deploy() as deferred:
        assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    assert deferred.paths == [
        chezmoi_home / "dot_config" / "sase" / "sase_kellys_mbp.yml",
        chezmoi_home / ".chezmoiignore",
    ]


def test_non_chezmoi_init_never_writes_or_deploys_ignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir, _chezmoi_root, chezmoi_home = _prepare(
        tmp_path,
        monkeypatch,
        use_chezmoi=False,
    )
    monkeypatch.setattr(
        config_init_handler,
        "deploy_to_chezmoi",
        lambda *_args, **_kwargs: pytest.fail("deploy should not be attempted"),
    )

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    assert (config_dir / "sase_kellys_mbp.yml").exists()
    assert not (chezmoi_home / ".chezmoiignore").exists()


def test_missing_trailing_newline_is_normalized_before_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    chezmoi_home.mkdir(parents=True)
    ignore_path = chezmoi_home / ".chezmoiignore"
    ignore_path.write_text("tags", encoding="utf-8")
    _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    assert ignore_path.read_text().startswith(
        'tags\n{{ if ne .chezmoi.hostname "Kellys-MBP" }}\n'
    )


def test_unknown_hostname_warns_and_still_deploys_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _config_dir, _chezmoi_root, chezmoi_home = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(config_init_handler, "chezmoi_hostname", lambda: None)
    deployed = _capture_deploy(monkeypatch)

    assert config_init_handler.run_config_init(_args("kellys_mbp", "alice")) == 0

    source = chezmoi_home / "dot_config" / "sase" / "sase_kellys_mbp.yml"
    assert deployed == [source]
    assert not (chezmoi_home / ".chezmoiignore").exists()
    assert (
        "could not determine the chezmoi hostname; add a `.chezmoiignore` guard"
        in capsys.readouterr().err
    )
