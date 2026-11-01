"""Freshness preflight coverage for local closed-bead whitelist rows."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sase.bead import epic_symbol_freshness as freshness


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _repo_with_justfile(path: Path, text: str) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "master", str(path)], check=True)
    _git(path, "config", "user.name", "sase-test")
    _git(path, "config", "user.email", "sase-test@example.com")
    (path / "Justfile").write_text(text, encoding="utf-8")
    _git(path, "add", "Justfile")
    _git(path, "commit", "-m", "fixture")
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def test_no_rows_return_before_status_resolution(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    _repo_with_justfile(repo, "symvision src\n")

    def unexpected_status_read(*_args, **_kwargs):
        pytest.fail("empty Justfile must not resolve bead status")

    monkeypatch.setattr(freshness, "_read_statuses", unexpected_status_read)

    assert freshness._assess_local_checkout(repo) == []


def test_batches_statuses_once_and_ignores_open_rekeyed_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    text = (
        "symvision src \\\n"
        '    --epic-symbol "sase-1.2.1(SymbolA)" \\\n'
        '    --epic-symbol "sase-1.2.1(SymbolB)" \\\n'
        '    --epic-symbol "sase-1.2.2(SymbolC)"\n'
    )
    head = _repo_with_justfile(repo, text)
    status_calls: list[tuple[Path, list[str]]] = []

    def statuses_for_ids(beads_dir: Path, bead_ids: list[str]) -> dict[str, str]:
        status_calls.append((beads_dir, bead_ids))
        return {"sase-1.2.1": "closed", "sase-1.2.2": "open"}

    monkeypatch.setattr(
        freshness,
        "resolve_operation_context_for_targets",
        lambda ids, **_kwargs: SimpleNamespace(
            beads_dir=tmp_path / "beads",
            resolved_ids=tuple(ids),
        ),
    )
    monkeypatch.setattr(
        freshness.bead_read_facade, "statuses_for_ids", statuses_for_ids
    )
    monkeypatch.setattr(
        freshness,
        "_fresh_upstream_rows",
        lambda *_args: ("a" * 40, [], True, None),
    )
    monkeypatch.setattr(freshness, "_is_ancestor", lambda *_args: True)

    result = freshness._assess_local_checkout(repo)

    assert len(status_calls) == 1
    assert status_calls[0][1] == ["sase-1.2.1", "sase-1.2.2"]
    assert [item["symbol"] for item in result] == ["SymbolA", "SymbolB"]
    assert all(item["classification"] == "stale_checkout" for item in result)
    assert all(item["local_head"] == head for item in result)


def test_failed_fetch_remains_uncertain_for_a_known_closed_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    _repo_with_justfile(
        repo,
        'symvision src \\\n    --epic-symbol "sase-9(Symbol)"\n',
    )
    monkeypatch.setattr(
        freshness,
        "resolve_operation_context_for_targets",
        lambda ids, **_kwargs: SimpleNamespace(
            beads_dir=tmp_path / "beads",
            resolved_ids=tuple(ids),
        ),
    )
    monkeypatch.setattr(
        freshness.bead_read_facade,
        "statuses_for_ids",
        lambda _beads_dir, _ids: {"sase-9": "closed"},
    )
    monkeypatch.setattr(
        freshness,
        "_fresh_upstream_rows",
        lambda *_args: (None, None, False, "remote unavailable"),
    )

    assert freshness._run_preflight(repo) == 1
    error = capsys.readouterr().err
    assert "uncertain" in error
    assert "Upstream cleanliness is unproven" in error
    assert "stale_checkout" not in error
    assert "unknown" in error
    assert "remote unavailable" in error
