from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.sdd._repository_recovery_markers import (
    FAILED_INTEGRATION_MARKER,
    record_failed_integration_marker,
)
from sase.sdd._store_integration import (
    _has_unpushed_bead_commits,
    _sidecar_clone_bead_store_dir,
)
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_link import _pull_sdd_clone
from sase.sdd._store_types import (
    SddIntegrationError,
    SddMaterializationError,
    SddSidecar,
    SddStoreRecord,
)
from sase.sdd._store_workspace import ensure_beads_sidecar_clone
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


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


def _seed_single_bead_remote(
    tmp_path: Path, beads_dirname: str, name: str
) -> tuple[Path, Path, Path, str]:
    remote = tmp_path / f"{name}.git"
    seed = tmp_path / f"{name}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    prefix = "" if beads_dirname == BEADS_DIRNAME_ROOT else f"{beads_dirname}/"
    (seed / ".gitignore").write_text(f"{prefix}beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname=beads_dirname) as project:
        bead_id = project.create("Contested", IssueType.PLAN).id
    commit_all(seed, "seed contested bead")
    git(["push", "-u", "origin", "main"], seed)
    workspace_clone = tmp_path / f"{name}-local"
    peer_clone = tmp_path / f"{name}-peer"
    clone(remote, workspace_clone)
    clone(remote, peer_clone)
    return remote, workspace_clone, peer_clone, bead_id


def _diverge_one_bead(
    workspace_clone: Path,
    peer_clone: Path,
    bead_id: str,
    beads_dirname: str,
) -> None:
    with BeadProject(workspace_clone, beads_dirname=beads_dirname) as project:
        project.update(bead_id, notes="from local")
    commit_all(workspace_clone, "local bead note")
    with BeadProject(peer_clone, beads_dirname=beads_dirname) as project:
        project.update(bead_id, design="from upstream")
    commit_all(peer_clone, "upstream bead design")
    git(["push"], peer_clone)


def _assert_bead_rebase_integrated(
    workspace_clone: Path,
    peer_clone: Path,
    bead_id: str,
    beads_dirname: str,
) -> None:
    upstream_head = git(["rev-parse", "HEAD"], peer_clone).stdout.strip()
    git(
        ["merge-base", "--is-ancestor", upstream_head, "HEAD"],
        workspace_clone,
    )
    log = git(["log", "--oneline"], workspace_clone).stdout
    assert "local bead note" in log
    prefix = "" if beads_dirname == BEADS_DIRNAME_ROOT else f"{beads_dirname}/"
    stream = (workspace_clone / f"{prefix}events/streams/{bead_id}.jsonl").read_text(
        encoding="utf-8"
    )
    assert "from local" in stream
    assert "from upstream" in stream
    assert not (workspace_clone / ".git" / "rebase-merge").exists()
    assert not (workspace_clone / ".git" / "rebase-apply").exists()


def test_split_beads_pull_resolves_semantic_conflicts(tmp_path: Path) -> None:
    remote, workspace_clone, peer_clone, target = _seed_single_bead_remote(
        tmp_path, BEADS_DIRNAME_ROOT, "split"
    )
    _diverge_one_bead(workspace_clone, peer_clone, target, BEADS_DIRNAME_ROOT)

    ensure_sidecar_sdd_clone(workspace_clone, str(remote), strict=True, fresh=True)

    _assert_bead_rebase_integrated(
        workspace_clone, peer_clone, target, BEADS_DIRNAME_ROOT
    )


def test_combined_beads_pull_resolves_semantic_conflicts(tmp_path: Path) -> None:
    remote, workspace_clone, peer_clone, target = _seed_single_bead_remote(
        tmp_path, "beads", "combined"
    )
    _diverge_one_bead(workspace_clone, peer_clone, target, "beads")

    ensure_sidecar_sdd_clone(workspace_clone, str(remote), strict=True, fresh=True)

    _assert_bead_rebase_integrated(workspace_clone, peer_clone, target, "beads")


def test_split_beads_unpushed_commits_bypass_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "beads.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "beads"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    with BeadProject.init(clone_dir, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        project.create("Cooldown bead", IssueType.PLAN)
    commit_all(clone_dir, "local bead event")

    assert _sidecar_clone_bead_store_dir(clone_dir) == clone_dir.resolve()

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


def test_non_bead_sidecar_conflict_still_aborts(tmp_path: Path) -> None:
    remote = tmp_path / "research.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "research"
    peer = tmp_path / "peer"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "notes.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    clone(remote, peer)

    (clone_dir / "notes.md").write_text("local\n", encoding="utf-8")
    commit_all(clone_dir, "local change")
    (peer / "notes.md").write_text("remote\n", encoding="utf-8")
    commit_all(peer, "remote change")
    git(["push"], peer)

    assert _sidecar_clone_bead_store_dir(clone_dir) is None
    assert _has_unpushed_bead_commits(clone_dir, None) is False

    with pytest.raises(SddIntegrationError, match="non-bead conflicts remain"):
        _pull_sdd_clone(clone_dir, strict=True, fresh=True)


def test_beads_sidecar_error_hint_omitted_for_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import nullcontext

    workspace = tmp_path / "ws"
    primary = tmp_path / "primary"
    workspace.mkdir()
    primary.mkdir()
    record = SddStoreRecord(
        schema_version=3,
        storage="sidecar_repos",
        sidecars={
            "plans": SddSidecar(
                repo="sase-org/sase--plans", remote_url="file:///plans"
            ),
            "beads": SddSidecar(
                repo="sase-org/sase--beads", remote_url="file:///beads"
            ),
        },
    )
    monkeypatch.setattr(
        "sase.sdd._store_workspace.materialization_lock",
        lambda _path: nullcontext(),
    )
    monkeypatch.setattr(
        "sase.sdd._store_workspace.read_sdd_store_record",
        lambda _path: record,
    )
    monkeypatch.setattr(
        "sase._linked_repo_paths.sidecar_repo_clone_dir",
        lambda host, dirname: str(tmp_path / f"{dirname}-clone"),
    )

    def raise_integration(_clone_dir: Path, _remote_url: str, **_kwargs) -> None:
        raise SddIntegrationError(
            "git rebase failed: non-bead conflicts remain: notes.md"
        )

    monkeypatch.setattr(
        "sase.sdd._store_link.ensure_sidecar_sdd_clone",
        raise_integration,
    )
    with pytest.raises(SddMaterializationError) as excinfo:
        ensure_beads_sidecar_clone(
            workspace,
            1,
            primary_workspace_resolver=lambda _ws, _num: str(primary),
        )
    assert "Git credentials" not in str(excinfo.value)

    def raise_clone_failure(_clone_dir: Path, _remote_url: str, **_kwargs) -> None:
        raise SddMaterializationError(
            "could not create SDD sidecar clone at /tmp/missing"
        )

    monkeypatch.setattr(
        "sase.sdd._store_link.ensure_sidecar_sdd_clone",
        raise_clone_failure,
    )
    with pytest.raises(SddMaterializationError) as excinfo:
        ensure_beads_sidecar_clone(
            workspace,
            1,
            primary_workspace_resolver=lambda _ws, _num: str(primary),
        )
    assert "Git credentials" in str(excinfo.value)
