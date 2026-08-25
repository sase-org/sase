from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._repository_recovery_markers import (
    FAILED_INTEGRATION_MARKER,
    record_failed_integration_marker,
)
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_link import _pull_sdd_clone
from sase.sdd._store_types import SddMaterializationError
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def test_moved_sidecar_clone_with_matching_remote_is_accepted(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    old_clone = tmp_path / "repo--plans"
    moved_clone = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, old_clone)
    old_clone.rename(moved_clone)
    (moved_clone / "local-untracked.md").write_text("keep\n", encoding="utf-8")

    ensure_sidecar_sdd_clone(moved_clone, str(remote), strict=True)

    assert not old_clone.exists()
    assert (moved_clone / "local-untracked.md").read_text(encoding="utf-8") == "keep\n"
    assert git(["remote", "get-url", "origin"], moved_clone).stdout.strip() == str(
        remote
    )


@pytest.mark.parametrize(
    ("mode", "force_fresh", "marker_fresh", "expected_integrations"),
    [
        ("background", False, True, 0),
        ("off", False, True, 0),
        ("blocking", False, True, 1),
        ("background", True, True, 1),
        ("background", False, False, 1),
    ],
)
def test_pull_sdd_clone_ttl_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    force_fresh: bool,
    marker_fresh: bool,
    expected_integrations: int,
) -> None:
    integrations: list[Path] = []

    def integrate(repo_root: Path, **_kwargs):
        from sase.sdd._repository_transaction import (
            SddIntegrationOutcome,
            SddIntegrationStatus,
        )

        integrations.append(repo_root)
        return SddIntegrationOutcome(SddIntegrationStatus.SUCCESS)

    monkeypatch.setattr("sase.sdd._integration_marker.bead_refresh_mode", lambda: mode)
    monkeypatch.setattr(
        "sase.sdd._integration_marker.integration_is_fresh",
        lambda _repo: marker_fresh,
    )
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_machine_managed_sdd_repository",
        integrate,
    )

    assert _pull_sdd_clone(tmp_path, fresh=force_fresh) is True
    assert len(integrations) == expected_integrations


def test_pull_failure_warning_and_axe_report_are_durably_rate_limited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    from sase.sdd import _repository_recovery, _repository_transaction
    from sase.sdd._repository_transaction import (
        SddIntegrationOutcome,
        SddIntegrationStatus,
    )

    outcome = SddIntegrationOutcome(
        SddIntegrationStatus.RECOVERY_FAILED,
        error="injected durable recovery failure",
    )
    monkeypatch.setattr(
        _repository_transaction,
        "integrate_machine_managed_sdd_repository",
        lambda *_args, **_kwargs: outcome,
    )
    now = [100.0]
    real_admit = _repository_recovery.admit_recovery_notice

    def controlled_admit(repo_root: Path, signature: str, **kwargs) -> bool:
        return real_admit(
            repo_root,
            signature,
            clock=lambda: now[0],
            **kwargs,
        )

    monkeypatch.setattr(
        _repository_recovery,
        "admit_recovery_notice",
        controlled_admit,
    )
    errors: list[dict] = []
    monkeypatch.setattr("sase.axe.state.append_error", errors.append)

    assert _pull_sdd_clone(clone_dir, clock=lambda: now[0]) is False
    assert _pull_sdd_clone(clone_dir, clock=lambda: now[0]) is False

    warnings = [
        record
        for record in caplog.records
        if "Failed to pull workspace SDD clone" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert len(errors) == 1
    assert errors[0]["job"] == "workspace_sdd_clone_recovery"
    assert errors[0]["clone_path"] == str(clone_dir.resolve())
    assert errors[0]["failure_signature"]

    now[0] += 3601
    assert _pull_sdd_clone(clone_dir, clock=lambda: now[0]) is False
    warnings = [
        record
        for record in caplog.records
        if "Failed to pull workspace SDD clone" in record.getMessage()
    ]
    assert len(warnings) == 2
    assert len(errors) == 2


def test_failed_integration_cooldown_suppresses_repeated_rebases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, clone_dir, _right = _build_unrebasable_sidecar(tmp_path)
    from sase.sdd import _repository_transaction

    real_runner = _repository_transaction.default_git_runner
    rebase_attempts: list[str] = []

    def recording_runner(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rebase", "@{upstream}"]:
            rebase_attempts.append(op)
        return real_runner(repo_root, args, op=op, network=network)

    telemetry: list[dict] = []
    monkeypatch.setattr(_repository_transaction, "default_git_runner", recording_runner)
    monkeypatch.setattr("sase.logs.log_tui_git_operation", telemetry.append)

    now = [100.0]
    for _ in range(5):
        assert _pull_sdd_clone(clone_dir, clock=lambda: now[0]) is False

    assert rebase_attempts == ["sdd.clone.rebase"]
    cooldown_records = [
        record
        for record in telemetry
        if record.get("operation") == "sdd.clone.integration_cooldown"
    ]
    assert [record["suppressed_count"] for record in cooldown_records] == [1, 2, 3, 4]
    assert all(record["status"] == "suppressed" for record in cooldown_records)


def test_failed_integration_cooldown_does_not_park_unpushed_bead_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    bead_stream = clone_dir / "beads" / "events" / "streams" / "sase-1.jsonl"
    bead_stream.parent.mkdir(parents=True)
    bead_stream.write_text('{"event_id":"sase-1:1"}\n', encoding="utf-8")
    commit_all(clone_dir, "local bead event")

    from sase.sdd import _repository_transaction
    from sase.sdd._repository_transaction import (
        SddIntegrationOutcome,
        SddIntegrationStatus,
    )

    assert record_failed_integration_marker(
        clone_dir,
        SddIntegrationOutcome(
            SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
            upstream_present=True,
            error="injected failed integration",
        ),
        clock=lambda: 100.0,
    )
    integrations: list[Path] = []

    def integrate(repo_root: Path, **_kwargs):
        integrations.append(repo_root)
        return SddIntegrationOutcome(
            SddIntegrationStatus.SUCCESS,
            upstream_present=True,
        )

    monkeypatch.setattr(
        _repository_transaction,
        "integrate_machine_managed_sdd_repository",
        integrate,
    )

    assert _pull_sdd_clone(clone_dir, fresh=True, clock=lambda: 101.0) is True
    assert integrations == [clone_dir]
    assert not (clone_dir / ".git" / FAILED_INTEGRATION_MARKER).exists()


def test_successful_pull_clears_failed_integration_marker(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    from sase.sdd._integration_marker import git_state_path
    from sase.sdd._repository_transaction import (
        SddIntegrationOutcome,
        SddIntegrationStatus,
    )

    marker = git_state_path(clone_dir, FAILED_INTEGRATION_MARKER)
    assert record_failed_integration_marker(
        clone_dir,
        SddIntegrationOutcome(
            SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
            upstream_present=True,
            error="injected failed rebase",
        ),
        clock=lambda: 100.0,
    )
    assert marker.exists()

    assert _pull_sdd_clone(clone_dir, fresh=True, clock=lambda: 401.0) is True

    assert not marker.exists()


def test_sidecar_clone_fetches_once_within_ttl_and_refetches_on_demand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    refresh = {"mode": "background", "ttl_seconds": 120}
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"bead_refresh": refresh}},
    )

    from sase.sdd import _repository_transaction
    from sase.sdd._integration_marker import git_state_path

    fetches: list[str] = []
    real_runner = _repository_transaction.default_git_runner

    def recording_runner(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["fetch"]:
            fetches.append(op)
        return real_runner(repo_root, args, op=op, network=network)

    monkeypatch.setattr(_repository_transaction, "default_git_runner", recording_runner)
    marker = git_state_path(clone_dir, "sase-bead-sync.integration")
    assert not marker.exists()

    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)
    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)

    assert marker.exists()
    assert fetches == ["sdd.clone.fetch"]

    refresh["ttl_seconds"] = 0
    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)
    assert fetches == ["sdd.clone.fetch", "sdd.clone.fetch"]

    refresh["ttl_seconds"] = 120
    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True, fresh=True)
    assert fetches == ["sdd.clone.fetch"] * 3

    refresh["mode"] = "blocking"
    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)
    assert fetches == ["sdd.clone.fetch"] * 4


def test_retained_https_sidecar_clone_is_rewritten_without_losing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    clone_dir.mkdir(parents=True)
    git(["init", "-q"], clone_dir)
    git(
        [
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widget--plans.git",
        ],
        clone_dir,
    )
    local = clone_dir / "local-untracked.md"
    local.write_text("preserve me\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd._store_link._pull_sdd_clone",
        lambda _path, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.sdd._store_link._replace_workspace_sdd_clone",
        lambda *_args: pytest.fail("matching HTTPS clone was replaced"),
    )

    ensure_sidecar_sdd_clone(
        clone_dir,
        "git@github.com:acme/widget--plans.git",
        strict=True,
    )

    assert local.read_text(encoding="utf-8") == "preserve me\n"
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == (
        "git@github.com:acme/widget--plans.git"
    )


def test_sidecar_clone_uses_authoritative_remote_not_durable_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    durable_primary = tmp_path / "primary" / "sase" / "repos" / "plans"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    readme = seed / "README.md"
    readme.write_text("initial\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, durable_primary)

    (durable_primary / "README.md").write_text(
        "durable primary only\n", encoding="utf-8"
    )
    commit_all(durable_primary, "Unpushed durable-primary change")
    primary_only_head = git(["rev-parse", "HEAD"], durable_primary).stdout.strip()

    readme.write_text("authoritative remote\n", encoding="utf-8")
    commit_all(seed, "Advance authoritative remote incompatibly")
    git(["push"], seed)
    remote_head = git(["rev-parse", "HEAD"], seed).stdout.strip()
    clone_commands: list[list[str]] = []
    clone_terminal_prompts: list[str | None] = []
    from sase.sdd import _commit

    original_run_sdd_git = _commit.run_sdd_git

    def record_git(args: list[str], **kwargs):
        if args and args[0] == "clone":
            clone_commands.append(args)
            clone_terminal_prompts.append(kwargs["env"].get("GIT_TERMINAL_PROMPT"))
        return original_run_sdd_git(args, **kwargs)

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", record_git)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("durable primary seeded fresh sidecar"),
    )

    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)

    assert clone_commands == [["clone", str(remote), str(clone_dir)]]
    assert clone_terminal_prompts == ["0"]
    assert git(["rev-parse", "HEAD"], clone_dir).stdout.strip() == remote_head
    assert git(["rev-parse", "@{upstream}"], clone_dir).stdout.strip() == remote_head
    assert (clone_dir / "README.md").read_text(encoding="utf-8") == (
        "authoritative remote\n"
    )
    assert git(["status", "--porcelain"], clone_dir).stdout == ""
    assert (
        primary_only_head
        not in git(["rev-list", "--all"], clone_dir).stdout.splitlines()
    )
    assert not (clone_dir / ".git" / "rebase-merge").exists()
    assert not (clone_dir / ".git" / "rebase-apply").exists()
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(remote)


def test_sidecar_clone_failure_removes_partial_target_and_surfaces_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0

    def failed_clone(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        clone_dir.mkdir(parents=True)
        (clone_dir / "partial").write_text("incomplete", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="authentication failed for plans remote",
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", failed_clone)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("clone failure used a local fallback"),
    )

    with pytest.raises(
        SddMaterializationError, match="authentication failed for plans remote"
    ):
        ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert not clone_dir.exists()
    assert attempts == 1


def test_sidecar_clone_retries_transient_transport_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0
    sleeps: list[float] = []

    def flaky_clone(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        clone_dir.mkdir(parents=True)
        if attempts < 3:
            (clone_dir / "partial").write_text("incomplete", encoding="utf-8")
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=(
                    "Connection to ssh.example.test closed by remote host.\n"
                    "fetch-pack: unexpected disconnect while reading sideband packet\n"
                    "fatal: early EOF\n"
                    "fatal: fetch-pack: invalid index-pack output"
                ),
            )
        (clone_dir / ".git").mkdir()
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", flaky_clone)
    monkeypatch.setattr("sase.sdd._store_clone_ops.time.sleep", sleeps.append)

    ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert attempts == 3
    assert sleeps == [0.25, 1.0]
    assert not (clone_dir / "partial").exists()


def _build_unrebasable_sidecar(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    left = tmp_path / "plans"
    right = tmp_path / "right"
    init_bare_repo(remote)
    clone(remote, seed)
    target = seed / "plans" / "shared.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, left)
    clone(remote, right)

    (left / "plans" / "shared.md").write_text("local\n", encoding="utf-8")
    commit_all(left, "local change")
    (right / "plans" / "shared.md").write_text("remote\n", encoding="utf-8")
    commit_all(right, "remote change")
    git(["push"], right)
    return remote, left, right


@pytest.mark.parametrize("strict", [False, True])
def test_http_sidecar_remote_is_rejected_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    strict: bool,
) -> None:
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    git_calls: list[list[str]] = []

    def record_git(args: list[str], **_kwargs):
        git_calls.append(args)
        raise AssertionError("Git must not run for HTTP(S) sidecar remotes")

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", record_git)

    if strict:
        with pytest.raises(
            SddMaterializationError,
            match=r"refusing HTTP\(S\).*Git was not invoked",
        ):
            ensure_sidecar_sdd_clone(
                clone_dir,
                "https://example.test/acme/widget--plans.git",
                strict=True,
            )
    else:
        ensure_sidecar_sdd_clone(
            clone_dir,
            "http://example.test/acme/widget--plans.git",
        )
        assert "Git was not invoked" in caplog.text

    assert git_calls == []
    assert not clone_dir.exists()
