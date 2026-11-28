"""In-store recovery activation and claim-publication tests.

Split from ``tests.test_bead.test_recovery_claims``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import threading
from typing import Any

import pytest

from sase.bead._sync_publication import PushOutcome
from sase.bead.recovery import (
    REASON_PUBLISH_UNCONFIRMED,
    publish_recovery_activation_in_store,
    publish_recovery_claim,
    _publish_recovery_claim_in_store,
)
from tests.test_bead._recovery_claims_helpers import (
    FakeRecoveryCore,
    claim_key,
    claim_request,
    recovery_fake_core,  # noqa: F401 (registers the fake_core fixture)
)


def test_missing_close_token_never_grants_a_permit(
    tmp_path: Path, fake_core: FakeRecoveryCore
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    fake_core.arm(str(beads_dir), {"project_id": "alpha"})
    result = _publish_recovery_claim_in_store(
        beads_dir,
        claim_request(close_token=""),
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
        claim_request(),
        refresh=lambda _path: None,
        commit=lambda _path, _message: True,
        push=lambda _path: PushOutcome(
            pushed=True, skipped_no_remote=False, error=None
        ),
        replay=lambda _path: None,
    )
    again = _publish_recovery_claim_in_store(
        beads_dir,
        claim_request(),
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
            claim_request(project_id=project, owner=owner, proc_id=proc_id),
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
    assert claim_key("alpha", "demo-1", "demo-1.1:evt-1") != claim_key(
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
        claim_request(),
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
                claim_request(owner=f"machine-{index}", proc_id=f"proc-{index}"),
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
    result = publish_recovery_claim("alpha", claim_request())
    assert seen == ["alpha"]
    assert result.launch_permit is True
