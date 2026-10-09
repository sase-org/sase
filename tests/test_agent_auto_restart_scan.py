"""Tests for the update-skew witness-scan phase (read-only replay)."""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.agent.auto_restart.history import (
    FailedCandidate,
    collect_failed_candidates,
    _parse_local_stamp,
)
from sase.agent.auto_restart.inputs import (
    assemble_bundle_input,
    assemble_done_row_input,
    find_runner_log,
    read_log_tail,
)
from sase.agent.auto_restart.managed_roots import (
    ManagedRoot,
    code_identity_digest,
)
from sase.agent.auto_restart.witnesses import (
    WitnessInputs,
    _collect_journal_updates,
    _collect_witness_file_proof,
    collect_witnesses,
    _extract_proof_target,
    _parse_refresh_log_line,
    _select_proof_root,
)

GIT_AVAILABLE = shutil.which("git") is not None


def _managed_roots(**overrides: Any) -> tuple[ManagedRoot, ...]:
    roots = {
        "sase": ManagedRoot(
            name="sase",
            role="host",
            source_root="/repo/sase",
            commit="9c5000f2db",
            version="0.17.1",
            install_type="editable",
        ),
        "sase-core-rs": ManagedRoot(
            name="sase-core-rs",
            role="core",
            source_root=None,
            commit=None,
            version="0.37.2",
            install_type="wheel",
        ),
    }
    roots.update(overrides)
    return tuple(roots.values())


def _facts(
    import_name: str = "sase.monitor.continuation_delivery",
    symbol: str = "auto_launch_prefix",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at": "2026-10-09T12:00:00-04:00",
        "lifecycle_phase": "waiting",
        "exception_chain": [
            {
                "type": "ImportError",
                "qualname": "ImportError",
                "module": "builtins",
                "message": (f"cannot import name '{symbol}' from '{import_name}'"),
            }
        ],
        "import_error": {
            "name": import_name,
            "path": None,
            "missing_symbol": symbol,
        },
        "attribute_error": None,
        "frames": [
            {
                "file": "/repo/sase/src/sase/axe/run_agent_runner.py",
                "function": "_run_agent",
                "line": 232,
            }
        ],
        "last_frame_file": "/repo/sase/src/sase/axe/run_agent_runner.py",
        "skew_suspect": True,
        "error_text": None,
    }


# --- managed_roots -------------------------------------------------------


def test_code_identity_digest_detects_drift() -> None:
    boot = {"roots": [{"name": "sase", "commit": "9c5000f2db"}]}
    current = {"roots": [{"name": "sase", "commit": "9fd8a081f4"}]}
    assert code_identity_digest(boot) != code_identity_digest(current)


def test_code_identity_digest_stable_without_drift() -> None:
    identity = {
        "roots": [
            {"name": "sase", "commit": "9fd8a081f4"},
            {"name": "sase-core-rs", "version": "0.37.2"},
        ]
    }
    assert code_identity_digest(identity) == code_identity_digest(identity)


def test_code_identity_digest_prefers_commit_over_version() -> None:
    identity = {"roots": [{"name": "sase", "commit": "9fd8a081f4", "version": "9.9.9"}]}
    assert code_identity_digest(identity) == "sase@9fd8a08"


def test_code_identity_digest_none_without_roots() -> None:
    assert code_identity_digest(None) is None
    assert code_identity_digest({}) is None
    assert code_identity_digest({"roots": []}) is None
    assert code_identity_digest({"roots": [{"name": ""}]}) is None


# --- refresh log line ----------------------------------------------------


def test_parse_refresh_log_line() -> None:
    tail = (
        "Waiting for agents: research.46.final\n"
        "Refreshing sase runner code after dependency wait: "
        "9c5000f2dbb126962ea0a84856d0a49115450dc7 "
        "-> 9fd8a081f45689655249b7bf6ed7b561de65b8bf\n"
        "Error running agent: boom\n"
    )
    line = _parse_refresh_log_line(tail)
    assert line is not None
    assert line.from_rev == "9c5000f2dbb126962ea0a84856d0a49115450dc7"
    assert line.to_rev == "9fd8a081f45689655249b7bf6ed7b561de65b8bf"


def test_parse_refresh_log_line_missing() -> None:
    assert _parse_refresh_log_line("nothing here\n") is None
    assert _parse_refresh_log_line("") is None


# --- proof target + root selection ---------------------------------------


def test_extract_proof_target_from_structured_facts() -> None:
    module, symbol = _extract_proof_target(_facts(), error_text="", traceback_text="")
    assert module == "sase.monitor.continuation_delivery"
    assert symbol == "auto_launch_prefix"


def test_extract_proof_target_from_attribute_error() -> None:
    facts = _facts()
    facts["import_error"] = None
    facts["attribute_error"] = {
        "module": "sase.monitor.continuation_delivery",
        "attribute": "auto_launch_prefix",
    }
    module, symbol = _extract_proof_target(facts, error_text="", traceback_text="")
    assert module == "sase.monitor.continuation_delivery"
    assert symbol == "auto_launch_prefix"


def test_extract_proof_target_from_error_text() -> None:
    module, symbol = _extract_proof_target(
        None,
        error_text=("ImportError: cannot import name 'gone' from 'sase.foo.bar'"),
        traceback_text="",
    )
    assert module == "sase.foo.bar"
    assert symbol == "gone"


def test_extract_proof_target_unknown() -> None:
    assert _extract_proof_target(None, error_text="boom", traceback_text="") == (
        None,
        None,
    )
    assert _extract_proof_target({}, error_text="", traceback_text="") == (
        None,
        None,
    )


def test_select_proof_root() -> None:
    roots = _managed_roots()
    host = _select_proof_root("sase.monitor.x", roots)
    assert host is not None and host.name == "sase"
    core = _select_proof_root("sase_core_rs", roots)
    assert core is not None and core.name == "sase-core-rs"
    assert _select_proof_root("requests.models", roots) is None
    assert _select_proof_root(None, roots) is None
    assert _select_proof_root("sase.x", ()) is None


# --- journal windows -----------------------------------------------------


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
    journal = tmp_path / "dev_update.jsonl"
    _write_journal(
        journal,
        [
            "2026-10-09T11:40:00-04:00",
            "2026-10-09T11:53:00-04:00",
            "2026-10-09T12:30:00-04:00",
        ],
    )
    dismissal = datetime.datetime(2026, 10, 9, 11, 58, 33).astimezone().timestamp()
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


# --- W3 file proof against temporary git repos ---------------------------


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
        managed_roots=_managed_roots(),
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=True,
    )
    assert _collect_witness_file_proof(inputs, None) is None


def test_witness_file_proof_disabled_flag(tmp_path: Path) -> None:
    inputs = WitnessInputs(
        facts=_facts(),
        boot_identity=None,
        booted_at=None,
        finished_at=None,
        artifacts_timestamp=None,
        done_mtime=None,
        error_text="",
        traceback_text="",
        log_tail="",
        managed_roots=_managed_roots(),
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


# --- inputs assembly -----------------------------------------------------


def _done_dict(**overrides: Any) -> dict[str, Any]:
    done: dict[str, Any] = {
        "outcome": "failed",
        "finished_at": datetime.datetime(
            2026, 10, 9, 12, 5, tzinfo=datetime.UTC
        ).timestamp(),
        "name": "research.46.image",
        "cl_name": "gh_sase-org__sase",
        "workspace_dir": "/tmp/ws",
        "error": "ImportError: cannot import name 'x'",
        "traceback": "Traceback (most recent call last): ...",
        "output_path": None,
    }
    done.update(overrides)
    return done


def _meta_dict(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": "research.46.image",
        "lifecycle_phase": "waiting",
        "booted_at": "2026-10-09T11:29:14-04:00",
        "code_identity": {
            "schema_version": 1,
            "roots": [{"name": "sase", "commit": "9c5000f2db"}],
        },
    }
    meta.update(overrides)
    return meta


def test_assemble_done_row_with_structured_facts(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(failure_facts=_facts()),
        meta=_meta_dict(),
        managed_roots=(),
        project="gh_sase-org__sase",
        died_at=1.0,
        log_tail="Refreshing sase runner code after dependency wait: a -> b\n",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.name == "research.46.image"
    assert assembled.facts is not None
    assert assembled.facts.lifecycle_phase == "waiting"
    assert assembled.facts.import_error is not None
    assert assembled.facts.import_error.missing_symbol == "auto_launch_prefix"
    assert assembled.context.lifecycle_phase == "waiting"
    assert assembled.context.workspace_dir == "/tmp/ws"
    assert assembled.context.error_text.startswith("ImportError")
    assert assembled.witnesses.boot_identity == "sase@9c5000f"
    assert assembled.lifecycle_phase == "waiting"


def test_assemble_done_row_legacy_without_facts(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(),
        meta={"name": "old.row"},
        managed_roots=(),
        project="gh_sase-org__sase",
        died_at=1.0,
        log_tail="",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.facts is None
    assert assembled.context.error_text.startswith("ImportError")
    assert assembled.context.traceback_text.startswith("Traceback")
    assert assembled.witnesses.boot_identity is None
    assert assembled.lifecycle_phase is None


def test_assemble_done_row_pending_markers(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    (artifacts_dir / "pending_question.json").write_text("{}", encoding="utf-8")
    (artifacts_dir / ".sase_gate_pending").write_text("", encoding="utf-8")
    assembled = assemble_done_row_input(
        artifacts_dir=artifacts_dir,
        done=_done_dict(),
        meta={},
        managed_roots=(),
        project="p",
        died_at=None,
        log_tail="",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.context.has_pending_question is True
    assert assembled.context.has_pending_handoff is True


def test_assemble_bundle_input(tmp_path: Path) -> None:
    bundle = {
        "agent_name": "0yz",
        "cl_name": "gh_bobs-org__bob-cli",
        "workspace_dir": "/tmp/bob",
        "artifacts_dir": "/nowhere/20261009115056",
        "error_message": "ImportError: cannot import name 'x'",
        "error_traceback": "Traceback ...",
        "output_path": None,
    }
    assembled = assemble_bundle_input(
        bundle=bundle,
        managed_roots=(),
        project="gh_bobs-org__bob-cli",
        died_at=1.0,
        log_tail="tail",
        journal_path=tmp_path / "absent.jsonl",
        enable_file_proof=False,
    )
    assert assembled.name == "0yz"
    assert assembled.facts is None
    assert assembled.context.workspace_dir == "/tmp/bob"
    assert assembled.witnesses.boot_identity is None


def test_read_log_tail_last_200_lines(tmp_path: Path) -> None:
    log = tmp_path / "run.txt"
    log.write_text("\n".join(f"line {n}" for n in range(500)), encoding="utf-8")
    tail = read_log_tail(log)
    lines = tail.splitlines()
    assert len(lines) == 200
    assert lines[0] == "line 300"
    assert lines[-1] == "line 499"
    assert read_log_tail(tmp_path / "absent.txt") == ""
    assert read_log_tail(None) == ""


def test_find_runner_log_prefers_output_path(tmp_path: Path) -> None:
    log = tmp_path / "custom.txt"
    log.write_text("hello", encoding="utf-8")
    assert find_runner_log(None, str(log), tmp_path) == log
    assert find_runner_log(None, str(tmp_path / "absent.txt"), tmp_path) is None


def test_find_runner_log_by_timestamp_suffix(tmp_path: Path) -> None:
    shard = tmp_path / "202610"
    shard.mkdir()
    log = shard / "gh_x__y_ace-run-261009_112914.txt"
    log.write_text("hello", encoding="utf-8")
    assert find_runner_log("20261009112914", None, tmp_path) == log
    assert find_runner_log("19990101000000", None, tmp_path) is None


# --- history enumeration -------------------------------------------------


def _write_done(
    artifacts_dir: Path, done: dict[str, Any], meta: dict[str, Any] | None = None
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    if meta is not None:
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )


def _history_tree(tmp_path: Path) -> tuple[Path, Path, Path, float]:
    now = datetime.datetime.now(datetime.UTC).timestamp()
    projects = tmp_path / "projects"
    recent_dir = projects / "proj" / "artifacts" / "ace-run" / "recent-row"
    _write_done(
        recent_dir,
        {
            "outcome": "failed",
            "finished_at": now - 3600,
            "name": "recent.agent",
            "cl_name": "proj",
            "error": "boom",
            "traceback": "",
        },
        {"name": "recent.agent"},
    )
    old_dir = projects / "proj" / "artifacts" / "ace-run" / "old-row"
    _write_done(
        old_dir,
        {
            "outcome": "failed",
            "finished_at": now - 30 * 86400,
            "name": "old.agent",
            "cl_name": "proj",
            "error": "old boom",
            "traceback": "",
        },
    )
    done_dir = projects / "proj" / "artifacts" / "ace-run" / "done-row"
    _write_done(done_dir, {"outcome": "completed", "name": "ok.agent"})
    bundles = tmp_path / "dismissed_bundles"
    bundles.mkdir(parents=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    (bundles / f"{stamp}.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "wiped.agent",
                "cl_name": "proj",
                "artifacts_dir": "/wiped/20200101000000",
                "error_message": "wiped boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}dup.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "recent.agent",
                "cl_name": "proj",
                "artifacts_dir": str(recent_dir),
                "error_message": "duplicate boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}mon.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "check.agent--mon",
                "agent_session_role": "monitor",
                "error_message": "exited with code 1",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    (bundles / f"{stamp}ok.json").write_text(
        json.dumps({"status": "DONE", "agent_name": "ok.agent"}),
        encoding="utf-8",
    )
    return projects, bundles, tmp_path / "workflows", now


def test_collect_failed_candidates_filters_and_dedups(tmp_path: Path) -> None:
    projects, bundles, workflows, _now = _history_tree(tmp_path)
    candidates = collect_failed_candidates(
        projects_root=projects,
        bundles_root=bundles,
        workflows_root=workflows,
        since_seconds=7 * 86400,
    )
    by_name = {candidate.name: candidate for candidate in candidates}
    assert "recent.agent" in by_name
    assert by_name["recent.agent"].source == "done"
    assert "wiped.agent" in by_name
    assert by_name["wiped.agent"].source == "bundle"
    assert "old.agent" not in by_name
    assert "ok.agent" not in by_name
    assert "check.agent--mon" not in by_name


def test_collect_failed_candidates_keeps_unknown_time(tmp_path: Path) -> None:
    projects, bundles, workflows, _now = _history_tree(tmp_path)
    (bundles / "mystery.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "agent_name": "mystery.agent",
                "error_message": "mystery boom",
                "error_traceback": "",
            }
        ),
        encoding="utf-8",
    )
    candidates = collect_failed_candidates(
        projects_root=projects,
        bundles_root=bundles,
        workflows_root=workflows,
        since_seconds=7 * 86400,
    )
    assert "mystery.agent" in {candidate.name for candidate in candidates}


def test_parse_local_stamp_variants() -> None:
    assert _parse_local_stamp("20261009112914") is not None
    assert _parse_local_stamp("261009_112914") is not None
    assert _parse_local_stamp(1_700_000_000.0) is None
    assert _parse_local_stamp("") is None
    assert _parse_local_stamp("not-a-stamp") is None
    fourteen = _parse_local_stamp("20261009112914")
    twelve = _parse_local_stamp("261009_112914")
    assert fourteen is not None and twelve is not None
    assert abs(fourteen - twelve) < 1.0


# --- wire round-trips ----------------------------------------------------


def test_failure_facts_wire_round_trip() -> None:
    from sase.core.agent_auto_restart_wire import (
        agent_failure_facts_from_dict,
        agent_failure_facts_to_dict,
    )

    facts = agent_failure_facts_from_dict(_facts())
    assert facts is not None
    assert facts.import_error is not None
    assert facts.import_error.missing_symbol == "auto_launch_prefix"
    assert len(facts.exception_chain) == 1
    assert len(facts.frames) == 1
    assert agent_failure_facts_from_dict(None) is None
    assert agent_failure_facts_from_dict({}) is None
    assert agent_failure_facts_from_dict("nope") is None
    assert agent_failure_facts_to_dict(facts)["skew_suspect"] is True


def test_recovery_verdict_wire_to_dict() -> None:
    from sase.core.agent_auto_restart_wire import (
        RecoveryVerdictWire,
        recovery_verdict_to_dict,
    )

    verdict = RecoveryVerdictWire(
        tier="tier1_torn_python",
        family="cannot_import_name",
        signature="ImportError: cannot import name",
        origin_module="sase.monitor.continuation_delivery",
        missing_symbol="auto_launch_prefix",
        phase_class="pre_provider",
        mode="defer",
        reason="probe_pending",
        reason_text="waiting for the probe",
        witnesses_fired=("W1", "W2"),
        episode_id="sase@9fd8a08",
    )
    payload = recovery_verdict_to_dict(verdict)
    assert payload["mode"] == "defer"
    assert payload["witnesses_fired"] == ["W1", "W2"]
    assert payload["schema_version"] == 1


# --- CLI -----------------------------------------------------------------


def _scan_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "auto_restart_subcommand": "scan",
        "since": "7d",
        "limit": None,
        "json": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_parse_since_and_limit() -> None:
    from sase.agents.cli_auto_restart import _parse_limit, _parse_since_seconds

    assert _parse_since_seconds("7d") == 7 * 86400
    assert _parse_since_seconds("2w") == 2 * 604800
    assert _parse_since_seconds("90") == 90
    assert _parse_since_seconds("45m") == 2700
    with pytest.raises(ValueError):
        _parse_since_seconds("yesterday")
    with pytest.raises(ValueError):
        _parse_since_seconds("0d")
    assert _parse_limit(None) == 50
    assert _parse_limit("10") == 10
    with pytest.raises(ValueError):
        _parse_limit("0")
    with pytest.raises(ValueError):
        _parse_limit("many")


def test_handle_scan_rejects_bad_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents.cli_auto_restart import handle_agents_auto_restart

    args = _scan_args(since="yesterday")
    assert handle_agents_auto_restart(args) == 2
    args = _scan_args(limit="0")
    assert handle_agents_auto_restart(args) == 2
    args = argparse.Namespace(auto_restart_subcommand=None)
    assert handle_agents_auto_restart(args) == 2


def test_handle_scan_empty_corpus(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade

    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", lambda: 1)
    monkeypatch.setattr(cli, "collect_managed_roots", lambda: ())
    monkeypatch.setattr(cli, "collect_failed_candidates", lambda **_: [])
    assert cli.handle_agents_auto_restart(_scan_args()) == 0
    out = capsys.readouterr().out
    assert "Scanned 0 failures" in out
    assert "ledger was not written" in out


def test_handle_scan_json_emits_verdict_wires(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade
    from sase.core.agent_auto_restart_wire import RecoveryVerdictWire

    artifacts_dir = tmp_path / "20261009112914"
    artifacts_dir.mkdir()
    candidate = FailedCandidate(
        source="done",
        name="legacy.agent",
        project="proj",
        died_at=None,
        artifacts_dir=artifacts_dir,
        done={
            "outcome": "failed",
            "name": "legacy.agent",
            "error": "ImportError: cannot import name 'x'",
            "traceback": "",
        },
        meta={},
        bundle=None,
        log_path=None,
    )
    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", lambda: 1)
    monkeypatch.setattr(
        facade,
        "classify_agent_failure",
        lambda context, witnesses, facts=None: RecoveryVerdictWire(
            tier="tier1_torn_python",
            family="cannot_import_name",
            signature="ImportError: cannot import name",
            phase_class="unknown",
            mode="defer",
            reason="probe_pending",
            reason_text="waiting for the probe",
            witnesses_fired=("W2",),
        ),
    )
    monkeypatch.setattr(cli, "collect_managed_roots", lambda: ())
    monkeypatch.setattr(cli, "collect_failed_candidates", lambda **_: [candidate])
    assert cli.handle_agents_auto_restart(_scan_args(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    result = payload["results"][0]
    assert result["name"] == "legacy.agent"
    assert result["verdict"]["mode"] == "defer"
    assert result["verdict"]["witnesses_fired"] == ["W2"]
    assert result["context"]["error_text"].startswith("ImportError")


def test_handle_scan_missing_binding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.agents.cli_auto_restart as cli
    import sase.core.agent_auto_restart_facade as facade

    def _missing() -> int:
        raise AttributeError("no such binding")

    monkeypatch.setattr(facade, "auto_restart_wire_schema_version", _missing)
    assert cli.handle_agents_auto_restart(_scan_args()) == 1
    assert "unavailable" in capsys.readouterr().err
