"""Host adapter coverage for recovery activation and claim publication."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import threading
from typing import Any

import pytest

from sase.bead._sync_publication import PushOutcome
from sase.bead.recovery import (
    REASON_EXISTING_CLAIM,
    REASON_NOT_LOCAL_WINNER,
    REASON_PUBLISH_UNCONFIRMED,
    publish_recovery_activation_in_store,
    publish_recovery_claim,
    _publish_recovery_claim_in_store,
)
from sase.core.recovery_facade import (
    RecoveryActivation,
    RecoveryActivationInspect,
    RecoveryArmResult,
    RecoveryClaim,
    RecoveryClaimCreateResult,
    RecoveryClaimInspect,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _configure_git(path: Path) -> None:
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _configure_git(path)
    _git(path, "commit", "--allow-empty", "-m", "init")


def _claim_key(project_id: str, epic_id: str, close_token: str) -> str:
    digest = sha256()
    digest.update(project_id.encode())
    digest.update(b"\x00")
    digest.update(epic_id.encode())
    digest.update(b"\x00")
    digest.update(close_token.encode())
    return digest.hexdigest()


class FakeRecoveryCore:
    """In-process create-if-absent store matching the Rust recovery layout."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def inspect_activation(
        self, beads_dir: str, project_id: str
    ) -> RecoveryActivationInspect:
        path = Path(beads_dir) / "recovery" / "activation.json"
        if not path.exists():
            return RecoveryActivationInspect(
                project_id=project_id, state="absent", recovery_enabled=False
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            activation = RecoveryActivation(
                project_id=payload["project_id"],
                armed_at=payload["armed_at"],
                generation=int(payload["generation"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return RecoveryActivationInspect(
                project_id=project_id,
                state="malformed",
                recovery_enabled=False,
                diagnostic=str(exc),
            )
        if activation.project_id != project_id:
            return RecoveryActivationInspect(
                project_id=project_id,
                state="malformed",
                recovery_enabled=False,
                diagnostic="project mismatch",
            )
        return RecoveryActivationInspect(
            project_id=project_id,
            state="armed",
            recovery_enabled=True,
            activation=activation,
        )

    def arm(self, beads_dir: str, request: dict[str, Any]) -> RecoveryArmResult:
        with self._lock:
            inspect = self.inspect_activation(beads_dir, str(request["project_id"]))
            if inspect.state == "malformed":
                return RecoveryArmResult(
                    state="malformed",
                    created=False,
                    recovery_enabled=False,
                    diagnostic=inspect.diagnostic,
                )
            if inspect.activation is not None:
                return RecoveryArmResult(
                    state="existing",
                    created=False,
                    recovery_enabled=True,
                    activation=inspect.activation,
                )
            activation = RecoveryActivation(
                project_id=str(request["project_id"]),
                armed_at=str(request.get("armed_at") or "2026-11-28T00:00:00Z"),
                generation=int(request.get("generation") or 1),
            )
            path = Path(beads_dir) / "recovery" / "activation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(activation), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return RecoveryArmResult(
                state="created",
                created=True,
                recovery_enabled=True,
                activation=activation,
            )

    def inspect_claim(
        self, beads_dir: str, request: dict[str, Any]
    ) -> RecoveryClaimInspect:
        key = _claim_key(
            str(request.get("project_id") or ""),
            str(request.get("epic_id") or ""),
            str(request.get("close_token") or ""),
        )
        path = Path(beads_dir) / "recovery" / "claims" / f"{key}.json"
        if not path.exists():
            return RecoveryClaimInspect(
                claim_key=key,
                project_id=str(request.get("project_id") or ""),
                epic_id=str(request.get("epic_id") or ""),
                close_token=str(request.get("close_token") or ""),
                state="absent",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            claim = RecoveryClaim(
                project_id=payload["project_id"],
                epic_id=payload["epic_id"],
                close_token=payload["close_token"],
                owner_machine=payload["owner_machine"],
                proc_id=payload["proc_id"],
                request_fingerprint=payload["request_fingerprint"],
                activation_generation=int(payload["activation_generation"]),
                created_at=payload["created_at"],
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return RecoveryClaimInspect(
                claim_key=key,
                project_id=str(request.get("project_id") or ""),
                epic_id=str(request.get("epic_id") or ""),
                close_token=str(request.get("close_token") or ""),
                state="malformed",
                diagnostic=str(exc),
            )
        return RecoveryClaimInspect(
            claim_key=key,
            project_id=claim.project_id,
            epic_id=claim.epic_id,
            close_token=claim.close_token,
            state="present",
            claim=claim,
        )

    def create(
        self, beads_dir: str, request: dict[str, Any]
    ) -> RecoveryClaimCreateResult:
        if not str(request.get("close_token") or "").strip():
            return RecoveryClaimCreateResult(
                claim_key="",
                state="refused",
                created=False,
                local_winner=False,
                diagnostic="recovery close_token must be a non-empty string",
            )
        with self._lock:
            activation = self.inspect_activation(beads_dir, str(request["project_id"]))
            if not activation.recovery_enabled or activation.activation is None:
                return RecoveryClaimCreateResult(
                    claim_key="",
                    state="refused",
                    created=False,
                    local_winner=False,
                    diagnostic="recovery activation is absent",
                )
            existing = self.inspect_claim(beads_dir, request)
            if existing.state == "malformed":
                return RecoveryClaimCreateResult(
                    claim_key=existing.claim_key,
                    state="malformed",
                    created=False,
                    local_winner=False,
                    diagnostic=existing.diagnostic,
                )
            if existing.claim is not None:
                winner = (
                    existing.claim.owner_machine == request["owner_machine"]
                    and existing.claim.proc_id == request["proc_id"]
                    and existing.claim.request_fingerprint
                    == request["request_fingerprint"]
                )
                return RecoveryClaimCreateResult(
                    claim_key=existing.claim_key,
                    state="existing",
                    created=False,
                    local_winner=winner,
                    claim=existing.claim,
                )
            claim = RecoveryClaim(
                project_id=str(request["project_id"]),
                epic_id=str(request["epic_id"]),
                close_token=str(request["close_token"]),
                owner_machine=str(request["owner_machine"]),
                proc_id=str(request["proc_id"]),
                request_fingerprint=str(request["request_fingerprint"]),
                activation_generation=activation.activation.generation,
                created_at=str(request.get("created_at") or "2026-11-28T12:00:00Z"),
            )
            key = _claim_key(claim.project_id, claim.epic_id, claim.close_token)
            path = Path(beads_dir) / "recovery" / "claims" / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(claim), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return RecoveryClaimCreateResult(
                claim_key=key,
                state="created",
                created=True,
                local_winner=True,
                claim=claim,
            )


@pytest.fixture
def fake_core(monkeypatch: pytest.MonkeyPatch) -> FakeRecoveryCore:
    core = FakeRecoveryCore()
    monkeypatch.setattr("sase.bead.recovery.arm_recovery_activation", core.arm)
    monkeypatch.setattr(
        "sase.bead.recovery.inspect_recovery_activation",
        core.inspect_activation,
    )
    monkeypatch.setattr("sase.bead.recovery.create_recovery_claim", core.create)
    monkeypatch.setattr("sase.bead.recovery.inspect_recovery_claim", core.inspect_claim)
    return core


def _claim_request(
    *,
    project_id: str = "alpha",
    epic_id: str = "demo-1",
    close_token: str = "demo-1.1:evt-1",
    owner: str = "athena",
    proc_id: str = "proc-a",
) -> dict[str, str]:
    return {
        "project_id": project_id,
        "epic_id": epic_id,
        "close_token": close_token,
        "owner_machine": owner,
        "proc_id": proc_id,
        "request_fingerprint": f"fp-{proc_id}",
    }


def test_missing_close_token_never_grants_a_permit(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    fake_core.arm(str(beads_dir), {"project_id": "alpha"})
    result = _publish_recovery_claim_in_store(
        beads_dir,
        _claim_request(close_token=""),
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    assert result.launch_permit is False
    assert result.reason == "claim_refused"


def test_repeated_reads_preserve_cutoff_and_winner(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    first = publish_recovery_activation_in_store(
        beads_dir,
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    second = publish_recovery_activation_in_store(
        beads_dir,
        {"project_id": "alpha", "armed_at": "2026-12-01T00:00:00Z"},
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    assert first.activation is not None
    assert second.activation is not None
    assert first.activation.armed_at == "2026-11-28T00:00:00Z"
    assert second.activation.armed_at == "2026-11-28T00:00:00Z"

    created = _publish_recovery_claim_in_store(
        beads_dir,
        _claim_request(),
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    again = _publish_recovery_claim_in_store(
        beads_dir,
        _claim_request(),
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    assert created.launch_permit is True
    assert again.launch_permit is True
    assert created.claim == again.claim


def test_malformed_activation_disables_publication(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    del fake_core
    beads_dir = tmp_path / "beads"
    path = beads_dir / "recovery" / "activation.json"
    path.parent.mkdir(parents=True)
    path.write_text("{nope", encoding="utf-8")
    result = publish_recovery_activation_in_store(
        beads_dir,
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    assert result.launch_permit is False
    assert result.reason == "activation_disabled"
    assert path.read_text(encoding="utf-8") == "{nope"


def test_two_projects_with_the_same_bead_suffix_stay_isolated(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    for beads_dir, project, owner, proc_id in (
        (alpha, "alpha", "athena", "proc-a"),
        (beta, "beta", "apollo", "proc-b"),
    ):
        publish_recovery_activation_in_store(
            beads_dir,
            {"project_id": project, "armed_at": "2026-11-28T00:00:00Z"},
            refresh=lambda _path: None,
            commit=lambda _path, _message: True,
            push=lambda _path: PushOutcome(
                pushed=True, skipped_no_remote=False, error=None
            ),
            replay=lambda _path: None,
        )
        result = _publish_recovery_claim_in_store(
            beads_dir,
            _claim_request(project_id=project, owner=owner, proc_id=proc_id),
            refresh=lambda _path: None,
            commit=lambda _path, _message: True,
            push=lambda _path: PushOutcome(
                pushed=True, skipped_no_remote=False, error=None
            ),
            replay=lambda _path: None,
        )
        assert result.launch_permit is True
        assert result.claim is not None
        assert result.claim.project_id == project
    assert _claim_key("alpha", "demo-1", "demo-1.1:evt-1") != _claim_key(
        "beta", "demo-1", "demo-1.1:evt-1"
    )


def test_unconfirmed_push_does_not_grant_a_permit(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    fake_core.arm(str(beads_dir), {"project_id": "alpha"})
    result = _publish_recovery_claim_in_store(
        beads_dir,
        _claim_request(),
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=False, skipped_no_remote=False, error="network down"
        ),
        replay=lambda _path: "still unpublished",
    )
    assert result.launch_permit is False
    assert result.reason in {
        REASON_PUBLISH_UNCONFIRMED,
        "publish_interrupted",
    }


def test_publication_module_does_not_submit_procs_or_agents() -> None:
    import sase.bead.recovery as recovery_module

    source = Path(recovery_module.__file__).read_text(encoding="utf-8")
    assert "launch_epic_bead_work" not in source
    assert "ProcSubmitRequest" not in source
    assert "submit_proc" not in source
    assert "sase.procs" not in source


def _fixture_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    first = tmp_path / "first"
    _init_repo(first)
    beads = first / "beads"
    beads.mkdir()
    (beads / "issues.jsonl").write_text("\n", encoding="utf-8")
    _git(first, "add", "beads")
    _git(first, "commit", "-m", "beads")
    _git(first, "remote", "add", "origin", str(remote))
    branch = _git(first, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    _git(first, "push", "-u", "origin", branch)
    second = tmp_path / "second"
    _git(tmp_path, "clone", str(remote), str(second))
    _configure_git(second)
    return first / "beads", second / "beads", remote


def _commit_recovery(beads_dir: Path, message: str) -> bool:
    repo = beads_dir.parent
    _git(repo, "add", "beads/recovery")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return False
    _git(repo, "commit", "-m", message)
    return True


def _push_recovery(beads_dir: Path) -> PushOutcome:
    repo = beads_dir.parent
    result = subprocess.run(
        ["git", "push"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return PushOutcome(pushed=True, skipped_no_remote=False, error=None)
    return PushOutcome(
        pushed=False,
        skipped_no_remote=False,
        error=(result.stderr or result.stdout).strip(),
    )


def _replay_recovery(beads_dir: Path) -> str | None:
    repo = beads_dir.parent
    fetched = subprocess.run(
        ["git", "fetch"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetched.returncode != 0:
        return fetched.stderr.strip()
    reset = subprocess.run(
        ["git", "reset", "--hard", "@{upstream}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if reset.returncode != 0:
        return reset.stderr.strip()
    return None


def test_competing_publisher_checkouts_keep_one_winner(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    first, second, _remote = _fixture_clones(tmp_path)
    fake_core.arm(
        str(first),
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
    )
    _commit_recovery(first, "arm")
    _push_recovery(first)
    _replay_recovery(second)

    winner = _publish_recovery_claim_in_store(
        first,
        _claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert winner.launch_permit is True
    assert winner.claim is not None
    assert winner.claim.owner_machine == "athena"

    loser = _publish_recovery_claim_in_store(
        second,
        _claim_request(owner="apollo", proc_id="proc-b"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert loser.launch_permit is False
    assert loser.reason in {REASON_EXISTING_CLAIM, REASON_NOT_LOCAL_WINNER}
    assert loser.claim is not None
    assert loser.claim.owner_machine == "athena"
    assert loser.claim.proc_id == "proc-a"


def test_interrupted_publication_adopts_the_published_winner(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    first, second, _remote = _fixture_clones(tmp_path)
    fake_core.arm(
        str(first),
        {"project_id": "alpha", "armed_at": "2026-11-28T00:00:00Z"},
    )
    _commit_recovery(first, "arm")
    _push_recovery(first)
    _replay_recovery(second)

    interrupted = _publish_recovery_claim_in_store(
        first,
        _claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=lambda _path: PushOutcome(
            pushed=False, skipped_no_remote=False, error="killed"
        ),
        replay=lambda _path: "unpublished",
    )
    assert interrupted.launch_permit is False

    published = _publish_recovery_claim_in_store(
        second,
        _claim_request(owner="apollo", proc_id="proc-b"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert published.launch_permit is True

    retried = _publish_recovery_claim_in_store(
        first,
        _claim_request(owner="athena", proc_id="proc-a"),
        refresh=lambda _path: None,
        commit=_commit_recovery,
        push=_push_recovery,
        replay=_replay_recovery,
    )
    assert retried.launch_permit is False
    assert retried.claim is not None
    assert retried.claim.owner_machine == "apollo"


def test_concurrent_local_publishers_keep_one_permit(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    fake_core.arm(str(beads_dir), {"project_id": "alpha"})
    results: list[Any] = []

    def publish(index: int) -> None:
        results.append(
            _publish_recovery_claim_in_store(
                beads_dir,
                _claim_request(owner=f"machine-{index}", proc_id=f"proc-{index}"),
                refresh=lambda _path: None,
                commit=lambda _path, _message: True,
                push=lambda _path: PushOutcome(
                    pushed=True, skipped_no_remote=False, error=None
                ),
                replay=lambda _path: None,
            )
        )

    threads = [threading.Thread(target=publish, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    permitted = [result for result in results if result.launch_permit]
    assert len(permitted) == 1
    winner = permitted[0].claim
    assert winner is not None
    for result in results:
        if result.claim is not None:
            assert result.claim.proc_id == winner.proc_id


def test_machine_adapter_uses_writable_store(
    tmp_path: Path,
    fake_core: FakeRecoveryCore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from sase.bead.background_store import WritableBeadStore
    from sase.workspace_provider.ownership import (
        AccessKind,
        MutationOrigin,
        OperationContext,
    )

    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    fake_core.arm(str(beads_dir), {"project_id": "alpha"})
    seen: list[str] = []

    @contextmanager
    def fake_store(project: str, **_kwargs: object) -> Iterator[WritableBeadStore]:
        seen.append(project)
        yield WritableBeadStore(
            project=project,
            beads_dir=beads_dir,
            context=OperationContext(
                project=project,
                access_kind=AccessKind.LEASED_OPERATIONAL,
                mutation_origin=MutationOrigin.MACHINE,
                workspace_num=10,
                checkout_dir=tmp_path,
                primary_checkout_dir=tmp_path / "primary",
                claim_pid=1,
                claim_workflow="epic_recovery_claim",
            ),
            reused_existing_claim=False,
        )

    monkeypatch.setattr(
        "sase.bead.background_store.writable_bead_store_for_machine",
        fake_store,
    )
    monkeypatch.setattr(
        "sase.bead.background_store.schedule_beads_sidecar_convergence",
        lambda _project: None,
    )
    monkeypatch.setattr(
        "sase.bead.recovery._publish_recovery_claim_in_store",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {
                "launch_permit": True,
                "published": True,
                "local_winner": True,
            },
        )(),
    )
    result = publish_recovery_claim("alpha", _claim_request())
    assert seen == ["alpha"]
    assert result.launch_permit is True
