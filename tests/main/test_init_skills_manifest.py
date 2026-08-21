"""Tests for generated-skill deploy provenance and monotonicity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main._init_skills_manifest import (
    ManagedSkillFile,
    SKILLS_MANIFEST_FILENAME,
    _SkillDeployManifest,
    _skill_xprompt_set_sha256,
    prepare_skill_manifest,
    retired_skill_files_with_drift,
)
from sase.main._init_skills_rendering import RenderedSkillDeploymentTarget
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import stub_manifest_git

_OLD_SHA = "1" * 40
_NEW_SHA = "2" * 40
_OTHER_SHA = "3" * 40


def _xprompts() -> list[XPrompt]:
    return [
        XPrompt(
            name="foo",
            content="body\n",
            description="A skill",
            skill=["claude"],
        )
    ]


def _write_manifest(
    chezmoi_home: Path,
    *,
    source_commit: str,
    xprompt_hash: str = "old-hash",
) -> Path:
    path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _SkillDeployManifest(
            source_commit=source_commit,
            xprompt_set_sha256=xprompt_hash,
            deployed_at="2026-07-28T12:00:00Z",
        ).to_json(),
        encoding="utf-8",
    )
    return path


def test_fast_forward_source_is_allowed_and_records_new_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _write_manifest(chezmoi_home, source_commit=_OLD_SHA)
    stub_manifest_git(
        monkeypatch,
        tmp_path,
        incoming=_NEW_SHA,
        ancestors={(_OLD_SHA, _NEW_SHA)},
    )

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=False
    )

    assert error is None
    assert write is not None
    assert write.path == chezmoi_home / SKILLS_MANIFEST_FILENAME
    assert write.content is not None
    payload = json.loads(write.content)
    assert payload == {
        "deployed_at": "2026-07-28T13:00:00Z",
        "managed_files": [],
        "source_commit": _NEW_SHA,
        "xprompt_set_sha256": _skill_xprompt_set_sha256(_xprompts()),
    }


def test_backwards_source_is_refused_with_both_subjects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    manifest_path = _write_manifest(chezmoi_home, source_commit=_NEW_SHA)
    original = manifest_path.read_text(encoding="utf-8")
    stub_manifest_git(
        monkeypatch,
        tmp_path,
        incoming=_OLD_SHA,
        ancestors={(_OLD_SHA, _NEW_SHA)},
    )

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=False
    )

    assert write is None
    assert error is not None
    assert "move the destination backwards" in error
    assert f"recorded: {_NEW_SHA} (new source)" in error
    assert f"incoming: {_OLD_SHA} (old source)" in error
    assert "--force" in error
    assert manifest_path.read_text(encoding="utf-8") == original


def test_divergent_source_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _write_manifest(chezmoi_home, source_commit=_OTHER_SHA)
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=False
    )

    assert write is None
    assert error is not None
    assert "sources are unrelated" in error
    assert f"recorded: {_OTHER_SHA} (other source)" in error
    assert f"incoming: {_NEW_SHA} (new source)" in error


def test_identical_provenance_preserves_deploy_time_for_a_no_op(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompts = _xprompts()
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _write_manifest(
        chezmoi_home,
        source_commit=_NEW_SHA,
        xprompt_hash=_skill_xprompt_set_sha256(xprompts),
    )
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        xprompts, chezmoi_home=chezmoi_home, force=False
    )

    assert error is None
    assert write is not None
    assert write.content is None


def test_identical_source_with_changed_xprompt_set_updates_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _write_manifest(
        chezmoi_home,
        source_commit=_NEW_SHA,
        xprompt_hash="different-content",
    )
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=False
    )

    assert error is None
    assert write is not None
    assert write.content is not None
    payload = json.loads(write.content)
    assert payload["source_commit"] == _NEW_SHA
    assert payload["xprompt_set_sha256"] == _skill_xprompt_set_sha256(_xprompts())


@pytest.mark.parametrize("existing", [None, "{not json"])
def test_missing_or_unparsable_manifest_bootstraps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: str | None,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    if existing is not None:
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(existing, encoding="utf-8")
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=False
    )

    assert error is None
    assert write is not None
    assert write.content is not None
    assert json.loads(write.content)["source_commit"] == _NEW_SHA


def test_force_overrides_backwards_guard_and_records_incoming_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    _write_manifest(chezmoi_home, source_commit=_NEW_SHA)
    stub_manifest_git(
        monkeypatch,
        tmp_path,
        incoming=_OLD_SHA,
        ancestors={(_OLD_SHA, _NEW_SHA)},
    )

    write, error = prepare_skill_manifest(
        _xprompts(), chezmoi_home=chezmoi_home, force=True
    )

    assert error is None
    assert write is not None
    assert write.content is not None
    assert json.loads(write.content)["source_commit"] == _OLD_SHA


def _deployment_target(
    chezmoi_home: Path,
    home_root: Path,
    *,
    provider: str = "claude",
    skill_name: str = "foo",
) -> RenderedSkillDeploymentTarget:
    return RenderedSkillDeploymentTarget(
        source_path=chezmoi_home
        / f"dot_{provider}"
        / "skills"
        / skill_name
        / "SKILL.md",
        home_path=home_root / f".{provider}" / "skills" / skill_name / "SKILL.md",
        content="rendered\n",
        provider=provider,
        skill_name=skill_name,
    )


def test_manifest_migration_backfills_current_and_tombstones_legacy_sase_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    home_root = tmp_path / "home"
    _write_manifest(chezmoi_home, source_commit=_NEW_SHA)
    legacy = chezmoi_home / "dot_gemini" / "jetski" / "skills" / "sase_old" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("retired\n", encoding="utf-8")
    current = _deployment_target(chezmoi_home, home_root)
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        _xprompts(),
        chezmoi_home=chezmoi_home,
        force=False,
        current_targets=(current,),
        home_root=home_root,
    )

    assert error is None
    assert write is not None
    assert write.content is not None
    payload = json.loads(write.content)
    files = payload["managed_files"]
    assert {
        (item["skill_name"], item["state"], item["source_path"]) for item in files
    } == {
        ("foo", "active", "dot_claude/skills/foo/SKILL.md"),
        ("sase_old", "retired", "dot_gemini/jetski/skills/sase_old/SKILL.md"),
    }
    assert [entry.skill_name for entry in write.retired_entries] == ["sase_old"]
    assert [
        entry.skill_name
        for entry in retired_skill_files_with_drift(
            write.retired_entries,
            chezmoi_home=chezmoi_home,
            home_root=home_root,
        )
    ] == ["sase_old"]


def test_manifest_retires_missing_current_target_and_reactivates_if_current_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    home_root = tmp_path / "home"
    entry = ManagedSkillFile(
        provider="claude",
        skill_name="foo",
        source_relpath="dot_claude/skills/foo/SKILL.md",
        home_relpath=".claude/skills/foo/SKILL.md",
    )
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        _SkillDeployManifest(
            source_commit=_NEW_SHA,
            xprompt_set_sha256="old-hash",
            deployed_at="2026-07-28T12:00:00Z",
            managed_files=(entry,),
        ).to_json(),
        encoding="utf-8",
    )
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    retired_write, error = prepare_skill_manifest(
        [],
        chezmoi_home=chezmoi_home,
        force=False,
        current_targets=(),
        home_root=home_root,
    )

    assert error is None
    assert retired_write is not None
    assert retired_write.content is not None
    retired_payload = json.loads(retired_write.content)
    assert retired_payload["managed_files"][0]["state"] == "retired"

    manifest_path.write_text(retired_write.content, encoding="utf-8")
    current = _deployment_target(chezmoi_home, home_root)
    active_write, error = prepare_skill_manifest(
        _xprompts(),
        chezmoi_home=chezmoi_home,
        force=False,
        current_targets=(current,),
        home_root=home_root,
    )

    assert error is None
    assert active_write is not None
    assert active_write.content is not None
    active_payload = json.loads(active_write.content)
    assert active_payload["managed_files"][0]["state"] == "active"


def test_manifest_rejects_path_escape_in_managed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "deployed_at": "2026-07-28T12:00:00Z",
                "managed_files": [
                    {
                        "home_path": ".claude/skills/foo/SKILL.md",
                        "provider": "claude",
                        "skill_name": "foo",
                        "source_path": "../escape/SKILL.md",
                        "state": "active",
                    }
                ],
                "source_commit": _NEW_SHA,
                "xprompt_set_sha256": "old-hash",
            }
        ),
        encoding="utf-8",
    )
    stub_manifest_git(monkeypatch, tmp_path, incoming=_NEW_SHA, ancestors=set())

    write, error = prepare_skill_manifest(
        _xprompts(),
        chezmoi_home=chezmoi_home,
        force=False,
        current_targets=(),
        home_root=tmp_path / "home",
    )

    assert write is None
    assert error is not None
    assert "must not contain '..'" in error
