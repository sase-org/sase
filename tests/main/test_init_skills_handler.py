"""Tests for ``sase init skills`` command dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy
from sase.main._init_skills_manifest import SKILLS_MANIFEST_FILENAME
from sase.main.init_skills_handler import handle_init_skills_command
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import (
    make_args,
    stub_manifest_git,
    stub_skill_source,
)

_OLD_SHA = "1" * 40
_NEW_SHA = "2" * 40


def _write_newer_skill_deployment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, bytes, Path]:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    rendered = init_skills_handler.render_skill_targets(
        init_skills_handler.load_skill_sources()[0],
        provider_filter="claude",
        use_chezmoi=True,
        use_prettier=False,
    )
    assert len(rendered) == 1
    target_path = rendered[0].path
    target_path.parent.mkdir(parents=True)
    newer_content = b"newer deployment from two intervening runs\n"
    target_path.write_bytes(newer_content)

    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(
            {
                "deployed_at": "2026-07-28T12:00:00Z",
                "source_commit": _NEW_SHA,
                "xprompt_set_sha256": "newer-deployment",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stub_manifest_git(
        monkeypatch,
        tmp_path,
        incoming=_OLD_SHA,
        ancestors={(_OLD_SHA, _NEW_SHA)},
    )
    return target_path, newer_content, manifest_path


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


def test_handler_dirty_chezmoi_source_is_refused_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(
        init_skills_handler,
        "skill_source_integrity_error",
        lambda: (
            "refusing chezmoi skill deploy because xprompt sources have "
            "uncommitted changes:\n  M src/sase/skills/foo.md"
        ),
    )
    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 1
    assert not chezmoi_home.exists()
    deploy_mock.assert_not_called()
    err = capsys.readouterr().err
    assert "src/sase/skills/foo.md" in err


def test_handler_backwards_manifest_refuses_and_leaves_newer_deployment_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Block an older generated skill replacing two newer deployments."""
    target_path, newer_content, manifest_path = _write_newer_skill_deployment(
        tmp_path, monkeypatch
    )
    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(force=False, provider="claude"))

    assert exc.value.code == 1
    assert target_path.read_bytes() == newer_content
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["source_commit"]
        == _NEW_SHA
    )
    deploy_mock.assert_not_called()
    err = capsys.readouterr().err
    assert _NEW_SHA in err
    assert _OLD_SHA in err
    assert "--force" in err


def test_handler_force_overrides_backwards_manifest_and_records_incoming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path, newer_content, manifest_path = _write_newer_skill_deployment(
        tmp_path, monkeypatch
    )
    rendered_content = init_skills_handler.render_skill_targets(
        init_skills_handler.load_skill_sources()[0],
        provider_filter="claude",
        use_chezmoi=True,
        use_prettier=False,
    )[0].content.encode()
    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(force=True, provider="claude"))

    assert exc.value.code == 0
    assert target_path.read_bytes() != newer_content
    assert target_path.read_bytes() == rendered_content
    assert (
        json.loads(manifest_path.read_text(encoding="utf-8"))["source_commit"]
        == _OLD_SHA
    )
    deploy_mock.assert_called_once()


def test_handler_allow_dirty_overrides_source_integrity_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    guard_mock = MagicMock(side_effect=AssertionError("guard must be bypassed"))
    monkeypatch.setattr(init_skills_handler, "skill_source_integrity_error", guard_mock)
    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(
        init_skills_handler, "_deploy_to_chezmoi", MagicMock(return_value=0)
    )

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(allow_dirty=True))

    assert exc.value.code == 0
    guard_mock.assert_not_called()
    assert tuple(chezmoi_home.rglob("SKILL.md"))


def test_handler_diff_is_read_only_and_skips_source_integrity_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    guard_mock = MagicMock(side_effect=AssertionError("guard must be bypassed"))
    monkeypatch.setattr(init_skills_handler, "skill_source_integrity_error", guard_mock)
    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(diff=True))

    assert exc.value.code == 0
    guard_mock.assert_not_called()
    assert not chezmoi_home.exists()


def test_handler_check_skips_source_integrity_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import init_onboarding

    guard_mock = MagicMock(side_effect=AssertionError("guard must be bypassed"))
    monkeypatch.setattr(init_skills_handler, "skill_source_integrity_error", guard_mock)
    check_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_onboarding, "run_init_check", check_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(check=True))

    assert exc.value.code == 0
    guard_mock.assert_not_called()
    check_mock.assert_called_once()


def test_handler_non_chezmoi_mode_skips_source_integrity_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    guard_mock = MagicMock(side_effect=AssertionError("guard must be bypassed"))
    monkeypatch.setattr(init_skills_handler, "skill_source_integrity_error", guard_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    guard_mock.assert_not_called()


def test_handler_zero_written_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When nothing is written (e.g. no skill field), no deploy."""
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"foo": XPrompt(name="foo", content="body\n")},
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_missing_manifest_bootstraps_then_unchanged_rerun_does_not_deploy(
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
        init_skills_handler.load_skill_sources()[0],
        provider_filter="claude",
        use_chezmoi=True,
        use_prettier=False,
    )
    assert len(rendered) == 1
    target = rendered[0]
    target.path.parent.mkdir(parents=True)
    target.path.write_text(target.content, encoding="utf-8")

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(provider="claude"))

    assert exc.value.code == 0
    deploy_mock.assert_called_once()
    assert deploy_mock.call_args.args[0][0].name == ".sase-skills-manifest.json"

    deploy_mock.reset_mock()
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
    assert [path.name for path in passed_paths] == [
        "SKILL.md",
        ".sase-skills-manifest.json",
    ]


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
    assert [path.name for path in deferred.paths] == [
        "SKILL.md",
        ".sase-skills-manifest.json",
    ]


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
