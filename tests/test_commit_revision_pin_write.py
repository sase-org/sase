"""Revision-pin write conditions and checkout-escape guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.commit_revision_pin import (
    maybe_write_revision_pin,
)


def _patch_git_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)


def test_pin_written_and_included_in_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    new_sha = "a" * 40
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )

    assert diagnostic is None
    assert evidence == f"sase-core:sase-core-revision.txt:{'b' * 12}->{'a' * 12}"
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        new_sha + "\n"
    )


def test_pin_write_recovery_resume_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    new_sha = "a" * 40
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    first, _ = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )
    second, _ = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )

    assert "->" in first
    assert "already-equal" in second
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        new_sha + "\n"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"main_is_commit": False, "commit_sha": "a" * 40},
        {"main_is_commit": True, "commit_sha": "short"},
    ],
)
def test_pin_write_skip_conditions_never_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        **kwargs,  # type: ignore[arg-type]
    )

    assert "skipped" in evidence
    assert diagnostic is not None
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        "b" * 40 + "\n"
    )


def test_pin_write_skips_when_sha_not_on_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: False
    )
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "sha-not-on-default-branch" in evidence
    assert diagnostic is not None


def test_pin_write_skips_when_pin_not_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: False)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "pin-not-ancestor" in evidence
    assert diagnostic is not None


def test_pin_write_skips_symlinked_parent_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "victim.txt"
    sentinel.write_text("untouched\n", encoding="utf-8")
    (primary / "link").symlink_to(external, target_is_directory=True)

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(tmp_path / "core"),
        pin_rel="link/sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "pin-escapes-checkout" in evidence
    assert diagnostic is not None and "pin-escapes-checkout" in diagnostic
    assert sentinel.read_text(encoding="utf-8") == "untouched\n"
    assert not (external / "sase-core-revision.txt").exists()
    assert not (primary / "link" / "sase-core-revision.txt").exists()


def test_pin_write_skips_symlinked_pin_file_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    target = external / "real-pin.txt"
    target.write_text("b" * 40 + "\n", encoding="utf-8")
    (primary / "sase-core-revision.txt").symlink_to(target)

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(tmp_path / "core"),
        pin_rel="sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "pin-escapes-checkout" in evidence
    assert diagnostic is not None
    assert target.read_text(encoding="utf-8") == "b" * 40 + "\n"
    assert (primary / "sase-core-revision.txt").is_symlink()


def test_pin_write_skips_absolute_pin_rel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    outside = tmp_path / "evil-pin.txt"
    assert not outside.exists()

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel=str(outside),
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "pin-escapes-checkout" in evidence
    assert diagnostic is not None
    assert not outside.exists()
