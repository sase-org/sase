"""Temporary-repository integration coverage for the publication gate.

These tests drive :class:`BareGitPlugin` commit dispatch against real
temporary git repositories: upstream privatizes a first-party name while the
local side adds an import of the old name in another file. The combined
rebase is textually clean, so only the after-rebase gate can catch it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.vcs_provider.plugins.bare_git import BareGitPlugin

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tools" / "check_rebase_imports"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _configure_user(cwd: Path) -> None:
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Test User")


def _isolate_hooks(cwd: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty-hooks"
    empty.mkdir(exist_ok=True)
    _git(cwd, "config", "core.hooksPath", str(empty))


def _write_hook_config(repo: Path, *, timeout: Any = 10) -> None:
    config_dir = repo / "sase"
    config_dir.mkdir(exist_ok=True)
    hook = f"{sys.executable} {CHECKER}"
    (config_dir / "sase.yml").write_text(
        "commit_hooks:\n"
        f'  after_rebase: "{hook}"\n'
        f"  after_rebase_timeout_seconds: {timeout}\n",
        encoding="utf-8",
    )


def _write_raw_hook_config(repo: Path, hook: str, *, timeout: Any = 10) -> None:
    config_dir = repo / "sase"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "sase.yml").write_text(
        "commit_hooks:\n"
        f'  after_rebase: "{hook}"\n'
        f"  after_rebase_timeout_seconds: {timeout}\n",
        encoding="utf-8",
    )


def _write_src(repo: Path, name: str, body: str) -> None:
    path = repo / "src" / "sase" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _clone_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    worker = tmp_path / "worker"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(origin))
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_user(seed)
    _isolate_hooks(seed, tmp_path)
    _write_src(seed, "__init__.py", "")
    _write_src(seed, "thing.py", "X = 1\n")
    _git(seed, "add", "src")
    _git(seed, "commit", "-m", "base")
    _git(seed, "push", "origin", "master")
    _git(tmp_path, "clone", str(origin), str(worker))
    _configure_user(worker)
    _isolate_hooks(worker, tmp_path)
    _write_hook_config(worker)
    return origin, seed, worker


def _peer(tmp_path: Path, origin: Path, name: str = "peer") -> Path:
    peer = tmp_path / name
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)
    _isolate_hooks(peer, tmp_path)
    return peer


def _artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    return artifacts


def _ledger(artifacts: Path) -> list[dict[str, Any]]:
    path = artifacts / "commit_results.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _run_counter(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import sase.workflows.commit.rebase_gate_runner as runner

    calls: dict[str, Any] = {"count": 0, "verdicts": []}
    original = runner.run_after_rebase_gate

    def recording(context: Any, repo_root: str) -> Any:
        calls["count"] += 1
        outcome = original(context, repo_root)
        calls["verdicts"].append(outcome.decision.get("verdict", ""))
        return outcome

    monkeypatch.setattr(runner, "run_after_rebase_gate", recording)
    return calls


def test_privatized_import_blocks_push_and_keeps_commit_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin, _seed, worker = _clone_pair(tmp_path)
    artifacts = _artifacts(monkeypatch, tmp_path)
    peer = _peer(tmp_path, origin)
    (peer / "src" / "sase" / "thing.py").write_text("_X = 1\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "privatize X")
    _git(peer, "push", "origin", "master")

    _write_src(worker, "user.py", "from sase.thing import X\n")
    payload: dict[str, Any] = {"message": "use X"}
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

    assert ok is False, err
    assert err is not None
    assert "Rebase gate finding" in err
    assert "user.py" in err and "X" in err
    assert "sase stitch create --resume" in err
    assert payload.get("_rebase_gate_blocked") is True
    assert isinstance(payload.get("_rebase_gate_pending"), dict)
    # Origin does not move and the local commit survives unpublished.
    assert (
        _git(worker, "rev-parse", "origin/master").stdout.strip()
        != _git(worker, "rev-parse", "HEAD").stdout.strip()
    )
    assert (
        _git(peer, "rev-parse", "HEAD").stdout.strip()
        == _git(worker, "rev-parse", "origin/master").stdout.strip()
    )
    head = _git(worker, "rev-parse", "HEAD").stdout.strip()
    assert "use X" in _git(worker, "log", "--format=%s", "-n1").stdout
    markers = _ledger(artifacts)
    assert len(markers) == 1
    assert markers[0]["commit_sha"] == head
    assert markers[0]["pushed"] is False


def test_incoming_importer_path_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (peer / "src" / "sase" / "user.py").write_text(
        "from sase.thing import X\n", encoding="utf-8"
    )
    _git(peer, "add", "src/sase/user.py")
    _git(peer, "commit", "-m", "upstream adds importer")
    _git(peer, "push", "origin", "master")

    (worker / "src" / "sase" / "thing.py").write_text("_X = 1\n", encoding="utf-8")
    payload: dict[str, Any] = {"message": "privatize X locally"}
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

    assert ok is False, err
    assert err is not None and "Rebase gate finding" in err
    assert "user.py" in err
    assert payload.get("_rebase_gate_blocked") is True


def test_retry_rebase_tree_is_checked_before_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    # Worker commits the importer on the old base without publishing yet.
    _write_src(worker, "user.py", "from sase.thing import X\n")
    _git(worker, "add", "src/sase/user.py")
    _git(worker, "commit", "-m", "add importer")
    # Upstream privatizes before the first push attempt.
    (peer / "src" / "sase" / "thing.py").write_text("_X = 1\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "privatize X")
    _git(peer, "push", "origin", "master")

    from sase.vcs_provider.plugins.bare_git import BareGitPlugin as Plugin

    payload: dict[str, Any] = {"message": "add importer"}
    ok, err = Plugin()._push_current_branch_with_rebase_retry(str(worker), payload)

    assert ok is False, err
    assert err is not None and "Rebase gate finding" in err
    assert payload.get("_rebase_gate_blocked") is True
    assert isinstance(payload.get("_rebase_gate_pending"), dict)


def test_resume_blocks_unchanged_and_publishes_after_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (peer / "src" / "sase" / "thing.py").write_text("_X = 1\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "privatize X")
    _git(peer, "push", "origin", "master")

    _write_src(worker, "user.py", "from sase.thing import X\n")
    payload: dict[str, Any] = {"message": "use X"}
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))
    assert ok is False, err

    # Resume with the unchanged broken tree blocks again.
    ok, err = BareGitPlugin().vcs_finalize_commit(payload, str(worker))
    assert ok is False, err
    assert err is not None and "Rebase gate finding" in err
    assert "Unstaged edits alone" in err

    # Repair through the normal amend flow, resume, and publish once.
    (worker / "src" / "sase" / "user.py").write_text(
        "from sase.thing import _X\n", encoding="utf-8"
    )
    _git(worker, "add", "src/sase/user.py")
    _git(worker, "commit", "--amend", "--no-edit", "--quiet")
    ok, err = BareGitPlugin().vcs_finalize_commit(payload, str(worker))
    assert ok is True, err
    assert payload.get("_rebase_gate_pending") is None
    assert payload.get("_rebase_gate_blocked") is None
    _git(worker, "fetch", "origin", "master")
    assert _git(worker, "status", "--short", "--branch").stdout.strip() == (
        "## master...origin/master"
    )


def test_manual_textual_conflict_resume_runs_pending_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (worker / "src" / "sase" / "thing.py").write_text(
        "X = 1\nY = 2\n", encoding="utf-8"
    )
    (peer / "src" / "sase" / "thing.py").write_text("X = 1\nZ = 3\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "peer thing")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker thing", "files": ["src/sase/thing.py"]}, str(worker)
    )
    assert ok is False, err
    assert (
        _git(worker, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        == "src/sase/thing.py"
    )

    # Manual resolution through the normal rebase flow, then resume publishes.
    (worker / "src" / "sase" / "thing.py").write_text(
        "X = 1\nY = 2\nZ = 3\n", encoding="utf-8"
    )
    _git(worker, "add", "src/sase/thing.py")
    _git(worker, "-c", "core.editor=true", "rebase", "--continue")
    resume_payload: dict[str, Any] = {"message": "worker thing"}
    ok, err = BareGitPlugin().vcs_finalize_commit(resume_payload, str(worker))
    assert ok is True, err


def test_clean_divergent_rebase_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    calls = _run_counter(monkeypatch)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (peer / "src" / "sase" / "thing.py").write_text("X = 1\nW = 0\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "peer tweak")
    _git(peer, "push", "origin", "master")

    _write_src(worker, "user.py", "from sase.thing import X\nprint(X)\n")
    payload: dict[str, Any] = {"message": "use X cleanly"}
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

    assert ok is True, err
    assert calls["count"] == 1
    assert calls["verdicts"] == ["pass"]
    assert payload.get("_rebase_gate_pending") is None


def test_unchanged_base_skips_hook_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    calls = _run_counter(monkeypatch)

    _write_src(worker, "user.py", "from sase.thing import X\n")
    payload: dict[str, Any] = {"message": "use X"}
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

    assert ok is True, err
    assert calls["count"] == 0


def test_disabled_hook_skips_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    (worker / "sase" / "sase.yml").unlink()
    calls = _run_counter(monkeypatch)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (peer / "src" / "sase" / "thing.py").write_text("X = 1\nW = 0\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "peer tweak")
    _git(peer, "push", "origin", "master")

    _write_src(worker, "user.py", "from sase.thing import X\n")
    ok, err = BareGitPlugin().vcs_create_commit({"message": "use X"}, str(worker))

    assert ok is True, err
    assert calls["count"] == 0


def test_no_origin_skips_hook_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "solo"
    _git(tmp_path, "init", "--initial-branch=master", str(repo))
    _configure_user(repo)
    _write_hook_config(repo)
    _write_src(repo, "__init__.py", "")
    _write_src(repo, "thing.py", "X = 1\n")
    _git(repo, "add", "src")
    _git(repo, "commit", "-m", "base")
    _artifacts(monkeypatch, tmp_path)
    calls = _run_counter(monkeypatch)

    _write_src(repo, "user.py", "from sase.thing import X\n")
    ok, err = BareGitPlugin().vcs_create_commit({"message": "solo"}, str(repo))

    assert ok is True, err
    assert calls["count"] == 0


def test_detached_head_skips_hook_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    _artifacts(monkeypatch, tmp_path)
    calls = _run_counter(monkeypatch)

    _write_src(worker, "user.py", "from sase.thing import X\n")
    _git(worker, "add", "src/sase/user.py")
    _git(worker, "commit", "-m", "base plus user")
    _git(worker, "checkout", "--detach", "HEAD")

    _write_src(worker, "extra.py", "from sase.thing import X\n")
    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "detached", "files": ["src/sase/extra.py"]}, str(worker)
    )

    assert ok is True, err
    assert calls["count"] == 0


def test_broken_hook_warns_and_permits_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = (
        "sleep 30",
        "nonexistent-sase-gate-command-xyz",
        "exit 1",
        "echo 'not json'",
    )
    for index, hook in enumerate(hooks):
        case = tmp_path / f"case-{index}"
        case.mkdir()
        origin = case / "origin.git"
        seed = case / "seed"
        worker = case / "worker"
        _git(case, "init", "--bare", "--initial-branch=master", str(origin))
        _git(case, "clone", str(origin), str(seed))
        _configure_user(seed)
        _write_src(seed, "__init__.py", "")
        _write_src(seed, "thing.py", "X = 1\n")
        _git(seed, "add", "src")
        _git(seed, "commit", "-m", "base")
        _git(seed, "push", "origin", "master")
        _git(case, "clone", str(origin), str(worker))
        _configure_user(worker)
        timeout = 2 if hook == "sleep 30" else 10
        _write_raw_hook_config(worker, hook, timeout=timeout)
        peer = case / "peer"
        _git(case, "clone", str(origin), str(peer))
        _configure_user(peer)
        (peer / "src" / "sase" / "thing.py").write_text(
            "X = 1\nW = 0\n", encoding="utf-8"
        )
        _git(peer, "add", "src/sase/thing.py")
        _git(peer, "commit", "-m", "peer tweak")
        _git(peer, "push", "origin", "master")
        artifacts = case / "artifacts"
        artifacts.mkdir()
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")

        _write_src(worker, "user.py", "from sase.thing import X\n")
        payload: dict[str, Any] = {"message": f"hook {hook}"}
        ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

        assert ok is True, f"hook {hook!r}: {err}"
        assert payload.get("_rebase_gate_blocked") is None


def test_dirty_tree_fails_open_without_false_certification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, _seed, worker = _clone_pair(tmp_path)
    artifacts = _artifacts(monkeypatch, tmp_path)
    calls = _run_counter(monkeypatch)
    peer = _peer(tmp_path, tmp_path / "origin.git")
    (peer / "src" / "sase" / "thing.py").write_text("_X = 1\n", encoding="utf-8")
    _git(peer, "add", "src/sase/thing.py")
    _git(peer, "commit", "-m", "privatize X")
    _git(peer, "push", "origin", "master")

    # Stage only the importer; leave an unrelated dirty Python file unstaged
    # so the checker cannot certify the committed tree.
    _write_src(worker, "user.py", "from sase.thing import X\n")
    _write_src(worker, "scratch.py", "print('dirty')\n")
    _git(worker, "add", "src/sase/user.py")
    payload: dict[str, Any] = {
        "message": "use X",
        "files": ["src/sase/user.py"],
    }
    ok, err = BareGitPlugin().vcs_create_commit(payload, str(worker))

    # Fail open: the push proceeds, but the verdict is a warning, never a
    # clean certification of the broken combined tree.
    assert ok is True, err
    assert calls["verdicts"] == ["warn"]
    assert payload.get("_rebase_gate_blocked") is None
    assert _ledger(artifacts) == []
