"""Tests for generated-skill deploy provenance and monotonicity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main._init_skills_manifest import (
    SKILLS_MANIFEST_FILENAME,
    _SkillDeployManifest,
    _skill_xprompt_set_sha256,
    prepare_skill_manifest,
)
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
