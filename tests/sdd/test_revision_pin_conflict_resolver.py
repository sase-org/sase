"""Revision-pin semantic conflict resolver coverage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.sdd._revision_pin_conflict_resolver import (
    is_revision_pin_conflict_path,
    resolve_revision_pin_conflicts,
)
from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts

PIN_PATH = "sase-core-revision.txt"
LINKED_NAME = "sase-core"
PINS = {LINKED_NAME: PIN_PATH}


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _write_pin(repo: Path, content: str, path: str = PIN_PATH) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", path)


def _pin_text(sha: str) -> str:
    return f"{sha}\n"


def _build_rebase_conflict(
    repo: Path,
    *,
    base: str | None,
    local: str,
    upstream: str,
    path: str = PIN_PATH,
) -> None:
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    if base is not None:
        _write_pin(repo, base, path)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "upstream")
    _write_pin(repo, upstream, path)
    _git(repo, "commit", "-m", "upstream")

    _git(repo, "checkout", "master")
    _write_pin(repo, local, path)
    _git(repo, "commit", "-m", "local")

    rebase = _git(repo, "rebase", "upstream", check=False)
    assert rebase.returncode != 0


def _linear_sibling(sibling: Path) -> tuple[str, str]:
    _init_repo(sibling)
    (sibling / "payload.txt").write_text("one\n", encoding="utf-8")
    _git(sibling, "add", "-A")
    _git(sibling, "commit", "-m", "one")
    sha_a = _git(sibling, "rev-parse", "HEAD").stdout.strip()
    (sibling / "payload.txt").write_text("two\n", encoding="utf-8")
    _git(sibling, "add", "-A")
    _git(sibling, "commit", "-m", "two")
    sha_b = _git(sibling, "rev-parse", "HEAD").stdout.strip()
    assert len(sha_a) == 40 and len(sha_b) == 40
    return sha_a, sha_b


def _diverged_sibling(sibling: Path) -> tuple[str, str]:
    _init_repo(sibling)
    (sibling / "payload.txt").write_text("base\n", encoding="utf-8")
    _git(sibling, "add", "-A")
    _git(sibling, "commit", "-m", "base")
    _git(sibling, "checkout", "-b", "branch-one")
    (sibling / "payload.txt").write_text("one\n", encoding="utf-8")
    _git(sibling, "add", "-A")
    _git(sibling, "commit", "-m", "one")
    sha_one = _git(sibling, "rev-parse", "HEAD").stdout.strip()
    _git(sibling, "checkout", "master")
    _git(sibling, "checkout", "-b", "branch-two")
    (sibling / "payload.txt").write_text("two\n", encoding="utf-8")
    _git(sibling, "add", "-A")
    _git(sibling, "commit", "-m", "two")
    sha_two = _git(sibling, "rev-parse", "HEAD").stdout.strip()
    return sha_one, sha_two


def _sibling_dirs(sibling: Path) -> dict[str, Path]:
    return {LINKED_NAME: sibling}


def test_linear_history_resolves_to_descendant(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_old), upstream=_pin_text(sha_new)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is True, result.message
    assert result.resolved_files == (PIN_PATH,)
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert (repo / PIN_PATH).read_text(encoding="utf-8") == _pin_text(sha_new)
    staged = _git(repo, "ls-files", "--stage", "--", PIN_PATH).stdout.splitlines()
    assert len(staged) == 1 and staged[0].split()[2] == "0"


def test_linear_history_resolves_to_descendant_reversed(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_new), upstream=_pin_text(sha_old)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is True, result.message
    assert (repo / PIN_PATH).read_text(encoding="utf-8") == _pin_text(sha_new)
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_equal_shas_keep_shared_value(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, _sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write_pin(repo, _pin_text(sha_old))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    blob = _git(repo, "hash-object", "-w", PIN_PATH).stdout.strip()
    _git(repo, "checkout", "--", PIN_PATH)
    _git(repo, "update-index", "--force-remove", PIN_PATH)
    info = f"100644 {blob} 2\t{PIN_PATH}\n100644 {blob} 3\t{PIN_PATH}\n"
    probe = subprocess.run(
        ["git", "update-index", "--index-info"],
        input=info,
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr

    result = resolve_revision_pin_conflicts(
        repo,
        (PIN_PATH,),
        sibling_dirs=_sibling_dirs(sibling),
        pins=PINS,
    )

    assert result.ok is True, result.message
    assert (repo / PIN_PATH).read_text(encoding="utf-8") == _pin_text(sha_old)


def test_diverged_shas_fall_through_to_model_repair(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_one, sha_two = _diverged_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_one), upstream=_pin_text(sha_two)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is False
    assert "diverged" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PIN_PATH
    )


def test_non_sha_content_falls_through(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local="not-a-sha\n", upstream=_pin_text(sha_new)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is False
    assert "not a 40-hex SHA" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PIN_PATH
    )


def test_missing_sibling_checkout_falls_through(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_old), upstream=_pin_text(sha_new)
    )

    result = resolve_semantic_conflicts(
        repo,
        revision_pin_sibling_dirs={LINKED_NAME: tmp_path / "no-such-dir"},
        revision_pin_pins=PINS,
    )

    assert result.ok is False
    assert "missing sibling checkout" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        PIN_PATH
    )


def test_unknown_sha_reports_not_found(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, _sha_new = _linear_sibling(sibling)
    unknown = "d" * 40
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_old), upstream=_pin_text(unknown)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is False
    assert "not found" in result.message


def test_pin_conflict_plus_unclaimed_file_falls_through(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "upstream")
    _write_pin(repo, _pin_text(sha_new))
    (repo / "notes.txt").write_text("upstream notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "upstream")
    _git(repo, "checkout", "master")
    _write_pin(repo, _pin_text(sha_old))
    (repo / "notes.txt").write_text("local notes\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "local")
    rebase = _git(repo, "rebase", "upstream", check=False)
    assert rebase.returncode != 0
    conflicted = _git(repo, "diff", "--name-only", "--diff-filter=U").stdout
    assert PIN_PATH in conflicted
    assert "notes.txt" in conflicted

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )

    assert result.ok is False
    assert "notes.txt" in result.message


def test_rebase_continues_after_pin_only_resolution(tmp_path: Path) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_old), upstream=_pin_text(sha_new)
    )

    result = resolve_semantic_conflicts(
        repo, revision_pin_sibling_dirs=_sibling_dirs(sibling), revision_pin_pins=PINS
    )
    assert result.ok is True, result.message

    continued = _git(
        repo, "-c", "core.editor=true", "rebase", "--continue", check=False
    )
    assert continued.returncode == 0, continued.stderr
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert (repo / PIN_PATH).read_text(encoding="utf-8") == _pin_text(sha_new)
    git_dir = Path(_git(repo, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    assert not (git_dir / "rebase-merge").is_dir()
    assert not (git_dir / "rebase-apply").is_dir()


def test_pin_predicate_claims_only_configured_pin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "sase").mkdir(parents=True)
    (repo / "sase" / "sase.yml").write_text(
        "repos:\n"
        "  linked:\n"
        "    - name: sase-core\n"
        "      path: ../sase-core\n"
        "      description: core\n"
        "      revision_pin: sase-core-revision.txt\n",
        encoding="utf-8",
    )

    assert is_revision_pin_conflict_path(repo, PIN_PATH) is True
    assert is_revision_pin_conflict_path(repo, "notes.txt") is False
    assert is_revision_pin_conflict_path(repo, PIN_PATH, pins={}) is False


def test_env_sibling_lookup_resolves_without_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sha_old, sha_new = _linear_sibling(sibling)
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_rebase_conflict(
        repo, base=None, local=_pin_text(sha_old), upstream=_pin_text(sha_new)
    )
    (repo / "sase").mkdir(parents=True)
    (repo / "sase" / "sase.yml").write_text(
        "repos:\n"
        "  linked:\n"
        "    - name: sase-core\n"
        "      path: ../sase-core\n"
        "      description: core\n"
        "      revision_pin: sase-core-revision.txt\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"name": LINKED_NAME, "workspace_dir": str(sibling)}]),
    )
    monkeypatch.delenv("SASE_SIBLING_REPOS_JSON", raising=False)
    assert os.environ["SASE_LINKED_REPOS_JSON"]

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    assert (repo / PIN_PATH).read_text(encoding="utf-8") == _pin_text(sha_new)
