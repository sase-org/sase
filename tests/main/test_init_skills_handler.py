"""Tests for ``sase init skills`` command dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy
from sase.main.init_skills_handler import handle_init_skills_command
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import make_args, stub_skill_source


def test_handler_no_use_chezmoi_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_chezmoi=False: _deploy_to_chezmoi is never called."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_dry_run_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run: no deploy even if use_chezmoi=True."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True))

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_zero_written_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When nothing is written (e.g. no skill field), no deploy."""
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"foo": XPrompt(name="foo", content="body\n")},
    )
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_unchanged_targets_do_not_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """use_chezmoi=True but byte-identical targets: no deploy is attempted."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    rendered = init_skills_handler.render_skill_targets(
        init_skills_handler.load_skill_xprompts(),
        provider_filter="claude",
        use_chezmoi=True,
        use_prettier=False,
    )
    assert len(rendered) == 1
    target = rendered[0]
    target.path.parent.mkdir(parents=True)
    target.path.write_text(target.content, encoding="utf-8")

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(provider="claude"))

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_use_chezmoi_triggers_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: use_chezmoi + wrote at least one file -> deploy is called."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_called_once()
    passed_paths = deploy_mock.call_args.args[0]
    assert len(passed_paths) == 1
    assert passed_paths[0].name == "SKILL.md"


def test_handler_deferred_chezmoi_collects_paths_without_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare init deferral records written paths and skips per-handler deploy."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with defer_chezmoi_deploy() as deferred:
        with pytest.raises(SystemExit) as exc:
            handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()
    assert len(deferred.paths) == 1
    assert deferred.paths[0].name == "SKILL.md"


def test_handler_propagates_deploy_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero return from _deploy_to_chezmoi becomes the process exit code."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(
        init_skills_handler, "_deploy_to_chezmoi", MagicMock(return_value=1)
    )

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 1
