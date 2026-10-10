"""Journal-window and file-proof witness tests for the scan phase.

Split from ``tests.test_agent_auto_restart_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.agent.auto_restart.managed_roots import ManagedRoot
from sase.agent.auto_restart.witnesses import (
    WitnessInputs,
    _collect_journal_updates,
    _collect_witness_file_proof,
    collect_witnesses,
)
from tests._agent_auto_restart_scan_helpers import scan_facts, scan_managed_roots

__all__ = [
    "addition_repo",
    "removal_repo",
    "test_collect_file_proof_addition_names_culprit",
    "test_collect_file_proof_removal_names_culprit",
    "test_collect_file_proof_unknown_module",
    "test_collect_journal_updates_bundle_window",
    "test_collect_journal_updates_missing_file",
    "test_collect_journal_updates_needs_launch_bound",
    "test_collect_journal_updates_uses_artifacts_timestamp",
    "test_collect_journal_updates_window",
    "test_collect_witnesses_w1_and_refresh_line",
    "test_witness_file_proof_disabled_flag",
    "test_witness_file_proof_gated_on_prefilter",
]

GIT_AVAILABLE = shutil.which("git") is not None


def _write_journal(path: Path, stamps: list[str]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write("not json\n")
        for stamp in stamps:
            stream.write(json.dumps({"timestamp": stamp}) + "\n")


def test_collect_journal_updates_window(tmp_path: Path) -> None:
    journal = tmp_path / "dev_update.jsonl"
    _write_journal(
        journal,
        [
            "2026-09-30T12:00:00-04:00",
            "2026-10-01T18:00:00-04:00",
            "2026-10-03T12:00:00-04:00",
        ],
    )
    updates = _collect_journal_updates(
        journal_path=journal,
        booted_at="2026-10-01T12:00:00-04:00",
        finished_at=datetime.datetime(
            2026, 10, 2, 12, 0, tzinfo=datetime.UTC
        ).timestamp(),
        artifacts_timestamp=None,
        done_mtime=None,
    )
    assert updates == ["2026-10-01T18:00:00-04:00"]


def test_collect_journal_updates_missing_file(tmp_path: Path) -> None:
    assert (
        _collect_journal_updates(
            journal_path=tmp_path / "absent.jsonl",
            booted_at="2026-10-01T12:00:00-04:00",
            finished_at=None,
            artifacts_timestamp="20261001120000",
            done_mtime=None,
        )
        == []
    )


def test_collect_journal_updates_needs_launch_bound(tmp_path: Path) -> None:
    journal = tmp_path / "dev_update.jsonl"
    _write_journal(journal, ["2026-10-01T18:00:00-04:00"])
    assert (
        _collect_journal_updates(
            journal_path=journal,
            booted_at=None,
            finished_at=None,
            artifacts_timestamp="not-a-stamp",
            done_mtime=None,
        )
        == []
    )


def test_collect_journal_updates_bundle_window(tmp_path: Path) -> None:
    """A bundle matches updates between launch and its dismissal bound."""
    from sase.core.time import get_timezone

    journal = tmp_path / "dev_update.jsonl"
    _write_journal(
        journal,
        [
            "2026-10-09T11:40:00-04:00",
            "2026-10-09T11:53:00-04:00",
            "2026-10-09T12:30:00-04:00",
        ],
    )
    dismissal = datetime.datetime(
        2026, 10, 9, 11, 58, 33, tzinfo=get_timezone()
    ).timestamp()
    updates = _collect_journal_updates(
        journal_path=journal,
        booted_at=None,
        finished_at=None,
        artifacts_timestamp="20261009115056",
        done_mtime=dismissal,
    )
    assert updates == ["2026-10-09T11:53:00-04:00"]


def test_collect_journal_updates_uses_artifacts_timestamp(tmp_path: Path) -> None:
    journal = tmp_path / "dev_update.jsonl"
    _write_journal(journal, ["2026-10-01T18:00:00-04:00"])
    updates = _collect_journal_updates(
        journal_path=journal,
        booted_at=None,
        finished_at=None,
        artifacts_timestamp="20261001120000",
        done_mtime=datetime.datetime(
            2026, 10, 2, 12, 0, tzinfo=datetime.UTC
        ).timestamp(),
    )
    assert updates == ["2026-10-01T18:00:00-04:00"]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture()
def removal_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo where TARGET_SYMBOL exists at boot and is removed at HEAD."""
    if not GIT_AVAILABLE:
        pytest.skip("git is not available")
    repo = tmp_path / "repo"
    module_file = repo / "src" / "pkg" / "mod.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("OTHER = 1\nTARGET_SYMBOL = 2\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "boot revision",
    )
    boot_rev = _git(repo, "rev-parse", "HEAD")
    module_file.write_text("OTHER = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "remove TARGET_SYMBOL",
    )
    head_rev = _git(repo, "rev-parse", "HEAD")
    assert boot_rev != head_rev
    return repo, boot_rev, head_rev


@pytest.fixture()
def addition_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo where TARGET_SYMBOL is absent at boot and added at HEAD."""
    if not GIT_AVAILABLE:
        pytest.skip("git is not available")
    repo = tmp_path / "repo"
    module_file = repo / "src" / "pkg" / "mod.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("OTHER = 1\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "boot revision",
    )
    boot_rev = _git(repo, "rev-parse", "HEAD")
    module_file.write_text("OTHER = 1\nTARGET_SYMBOL = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "add TARGET_SYMBOL",
    )
    return repo, boot_rev, _git(repo, "rev-parse", "HEAD")


def _proof_root(repo: Path) -> ManagedRoot:
    return ManagedRoot(
        name="sase",
        role="host",
        source_root=str(repo),
        commit=None,
        version="0.0.0",
        install_type="editable",
    )


def test_collect_file_proof_removal_names_culprit(
    removal_repo: tuple[Path, str, str],
) -> None:
    from sase.agent.auto_restart.witnesses import _collect_file_proof

    repo, boot_rev, _head_rev = removal_repo
    proof = _collect_file_proof(
        module="pkg.mod",
        symbol="TARGET_SYMBOL",
        root=_proof_root(repo),
        boot_rev=boot_rev,
    )
    assert proof is not None
    assert proof.boot_has is True
    assert proof.head_has is False
    assert proof.culprit_commit is not None and len(proof.culprit_commit) == 40
    assert proof.culprit_subject == "remove TARGET_SYMBOL"


def test_collect_file_proof_addition_names_culprit(
    addition_repo: tuple[Path, str, str],
) -> None:
    from sase.agent.auto_restart.witnesses import _collect_file_proof

    repo, boot_rev, _head_rev = addition_repo
    proof = _collect_file_proof(
        module="pkg.mod",
        symbol="TARGET_SYMBOL",
        root=_proof_root(repo),
        boot_rev=boot_rev,
    )
    assert proof is not None
    assert proof.boot_has is False
    assert proof.head_has is True
    assert proof.culprit_commit is not None
    assert proof.culprit_subject == "add TARGET_SYMBOL"


def test_collect_file_proof_unknown_module(
    removal_repo: tuple[Path, str, str],
) -> None:
    from sase.agent.auto_restart.witnesses import _collect_file_proof

    repo, boot_rev, _head_rev = removal_repo
    assert (
        _collect_file_proof(
            module="pkg.nope",
            symbol="TARGET_SYMBOL",
            root=_proof_root(repo),
            boot_rev=boot_rev,
        )
        is None
    )


def test_witness_file_proof_gated_on_prefilter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-skew failures skip git entirely (the epic-symbol consumer)."""
    import sase.agent.auto_restart.witnesses as witnesses_mod

    def _fail_git(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("git must not run for non-skew failures")

    monkeypatch.setattr(witnesses_mod, "_run_git", _fail_git)
    inputs = WitnessInputs(
        facts=None,
        boot_identity=None,
        booted_at=None,
        finished_at=None,
        artifacts_timestamp=None,
        done_mtime=None,
        error_text="ValueError: something ordinary broke",
        traceback_text="",
        log_tail="",
        managed_roots=scan_managed_roots(),
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=True,
    )
    assert _collect_witness_file_proof(inputs, None) is None


def test_witness_file_proof_disabled_flag(tmp_path: Path) -> None:
    inputs = WitnessInputs(
        facts=scan_facts(),
        boot_identity=None,
        booted_at=None,
        finished_at=None,
        artifacts_timestamp=None,
        done_mtime=None,
        error_text="",
        traceback_text="",
        log_tail="",
        managed_roots=scan_managed_roots(),
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert _collect_witness_file_proof(inputs, None) is None


def test_collect_witnesses_w1_and_refresh_line(tmp_path: Path) -> None:
    journal = tmp_path / "dev_update.jsonl"
    journal.write_text("", encoding="utf-8")
    boot_identity = {"roots": [{"name": "sase", "commit": "9c5000f2db"}]}
    witnesses = collect_witnesses(
        WitnessInputs(
            facts=None,
            boot_identity=boot_identity,
            booted_at=None,
            finished_at=None,
            artifacts_timestamp=None,
            done_mtime=None,
            error_text="boom",
            traceback_text="",
            log_tail=(
                "Refreshing sase runner code after dependency wait: "
                "9c5000f2db -> 9fd8a081f4\n"
            ),
            managed_roots=(),
            journal_path=journal,
            enable_file_proof=False,
        )
    )
    assert witnesses.boot_identity == "sase@9c5000f"
    assert witnesses.current_identity is not None
    assert witnesses.refresh_log_line is not None
    assert witnesses.refresh_log_line.from_rev == "9c5000f2db"
    assert witnesses.probe is None
    assert witnesses.file_proof is None
