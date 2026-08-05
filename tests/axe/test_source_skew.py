"""Tests for the agent-runner source-skew guard."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sase.axe import source_skew
from sase.axe.source_skew import (
    DISABLE_IMPORT_PRELOAD_ENV,
    code_swap_explanation,
    preload_post_gate_modules,
    snapshot_source_revision,
)


@pytest.fixture(autouse=True)
def _reset_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test a fresh, unsnapshotted module state."""
    monkeypatch.setattr(source_skew, "_startup_revision", None)
    monkeypatch.setattr(source_skew, "_startup_revision_taken", False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "file.txt").write_text("one\n", encoding="utf-8")
    _git(path, "add", "file.txt")
    _git(path, "commit", "-q", "-m", "one")
    return path


def _commit_again(repo: Path) -> None:
    (repo / "file.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "two")


# --- preload -----------------------------------------------------------------


def test_preload_imports_the_deferred_post_gate_surface() -> None:
    preload_post_gate_modules()

    for name in (
        "sase.sdd.store",
        "sase.sdd.files",
        "sase.bead.conflict_resolver",
        "sase.bead.epic_launch",
        "sase.bead.epic_launch_handoff",
        "sase.agents_sync.prompt_archive",
        "sase.notifications.senders",
        "sase.vcs_provider.plugins._git_commit_dispatch",
    ):
        assert name in sys.modules, f"{name} was not preloaded"


def test_preload_survives_a_broken_module_in_the_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_walk = source_skew._walk_package

    def fake_walk(package_name: str) -> list[str]:
        return [*real_walk(package_name), "sase.axe._definitely_not_a_module"]

    monkeypatch.setattr(source_skew, "_walk_package", fake_walk)

    # A broken module must not propagate out of a best-effort preload.
    assert preload_post_gate_modules() > 0


def test_preload_kill_switch_skips_every_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DISABLE_IMPORT_PRELOAD_ENV, "1")
    calls: list[str] = []
    monkeypatch.setattr(
        source_skew,
        "_import_best_effort",
        lambda name: calls.append(name) or True,
    )

    assert preload_post_gate_modules() == 0
    assert calls == []


# --- revision snapshot -------------------------------------------------------


def test_snapshot_records_head_and_is_taken_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path / "checkout")
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: repo)

    head = _git(repo, "rev-parse", "HEAD")
    assert snapshot_source_revision() == head

    _commit_again(repo)
    # The boot-time value must survive a later swap.
    assert snapshot_source_revision() == head


def test_snapshot_is_none_outside_a_git_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: None)

    assert snapshot_source_revision() is None
    assert source_skew._source_revision_changed() is None


def test_source_revision_changed_reports_both_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path / "checkout")
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: repo)

    before = snapshot_source_revision()
    assert source_skew._source_revision_changed() is None

    _commit_again(repo)
    after = _git(repo, "rev-parse", "HEAD")
    assert source_skew._source_revision_changed() == (before, after)


def test_source_checkout_requires_a_git_directory(tmp_path: Path) -> None:
    fake_sase = tmp_path / "root" / "src" / "sase" / "__init__.py"
    fake_sase.parent.mkdir(parents=True)
    fake_sase.write_text("", encoding="utf-8")

    import sase

    original = sase.__file__
    try:
        sase.__file__ = str(fake_sase)
        assert source_skew._source_checkout() is None
        (tmp_path / "root" / ".git").mkdir()
        assert source_skew._source_checkout() == (tmp_path / "root").resolve()
    finally:
        sase.__file__ = original


# --- classification ----------------------------------------------------------


def _wrapped_import_error() -> Exception:
    try:
        try:
            raise ImportError("cannot import name 'issue_id_for_counter'")
        except ImportError as exc:
            raise RuntimeError("store is unusable") from exc
    except RuntimeError as wrapped:
        return wrapped


def test_code_swap_explanation_needs_both_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path / "checkout")
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: repo)
    boot_revision = snapshot_source_revision()
    assert boot_revision is not None

    wrapped = _wrapped_import_error()
    # Import cause, but no swap yet.
    assert code_swap_explanation(wrapped) is None

    _commit_again(repo)
    # Swap, but no import cause.
    assert code_swap_explanation(RuntimeError("store is mid-rebase")) is None

    explanation = code_swap_explanation(wrapped)
    assert explanation is not None
    assert boot_revision in explanation
    assert _git(repo, "rev-parse", "HEAD") in explanation
    assert str(repo) in explanation


def test_code_swap_explanation_ignores_swaps_outside_a_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: None)

    assert code_swap_explanation(_wrapped_import_error()) is None


def test_accepted_plan_store_detail_names_a_swap_only_when_one_happened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded epic failure detail must not blame the store for a swap."""
    from sase.axe.run_agent_exec_plan_accept import _store_failure_detail

    repo = _make_repo(tmp_path / "checkout")
    monkeypatch.setattr(source_skew, "_source_checkout", lambda: repo)
    snapshot_source_revision()

    plain = RuntimeError("plans store is mid-rebase")
    assert _store_failure_detail(plain) == "plans store is mid-rebase"

    _commit_again(repo)
    detail = _store_failure_detail(_wrapped_import_error())
    assert detail.startswith("mid-run sase code swap, not an unusable store:")
    assert "store is unusable" in detail
    # A non-import failure after the same swap is still reported verbatim.
    assert _store_failure_detail(plain) == "plans store is mid-rebase"
