"""Operational workspace lease coverage (sase-mq.2)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.procs.request import ProcSubmitRequest
from sase.procs.settlement import _settle_workspace_claim
from sase.running_field import WorkspaceClaimError
from sase.workspace_provider.lease import (
    OPERATIONAL_LEASE_POLICY_KIND,
    OperationalLease,
    _OperationalLeaseError as OperationalLeaseError,
    _authorize_operational_lease_workspace as authorize_operational_lease_workspace,
    _bind_operational_lease as bind_operational_lease,
    _transfer_operational_lease as transfer_operational_lease,
    acquire_operational_lease,
    is_operational_lease_policy,
    operational_workspace_lease,
    release_operational_lease,
    submit_via_lease,
)
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM


def _adjacent_config() -> dict[str, object]:
    return {"workspace": {"root": "adjacent", "project_key": "demo"}}


def _write_project_file(path: Path, *, primary: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"WORKSPACE_DIR: {primary}",
                "",
                "NAME: demo",
                "DESCRIPTION:",
                "  operational lease fixture",
                "STATUS: Ready",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _context(
    checkout: Path, primary: Path, workspace_num: int = 10
) -> OperationContext:
    return OperationContext(
        project="demo",
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        project_file=None,
        claim_pid=os.getpid(),
        claim_workflow="chop:demo",
    )


def _lease(
    tmp_path: Path,
    *,
    workspace_num: int = 10,
    workflow: str = "chop:demo",
    holder: str = "holder",
) -> OperationalLease:
    primary = tmp_path / "proj"
    checkout = tmp_path / f"proj_{workspace_num}"
    checkout.mkdir(parents=True, exist_ok=True)
    project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
    return OperationalLease(
        project="demo",
        workflow=workflow,
        holder=holder,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        project_file=project_file,
        claim_pid=111,
        cl_name=holder,
        context=_context(checkout, primary, workspace_num),
    )


def _patch_acquire_steps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace_num: int = 10,
    checkout: Path,
    primary: Path,
    claim: Any = None,
    materialize: Any = None,
    prepare: Any = None,
    context: Any = None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {"released": []}
    monkeypatch.setattr(
        "sase.workspace_provider.lease.claim_next_axe_workspace",
        claim or (lambda *_args, **_kwargs: workspace_num),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.lease._materialize_leased_checkout",
        materialize or (lambda *_args, **_kwargs: checkout),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.lease._prepare_from_primary_remote",
        prepare or (lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.lease.leased_operational_context",
        context
        or (lambda *_args, **_kwargs: _context(checkout, primary, workspace_num)),
    )

    def _release(
        project_file: str,
        num: int,
        workflow: str,
        cl_name: str | None = None,
    ) -> None:
        calls["released"].append((str(project_file), num, workflow, cl_name))

    monkeypatch.setattr("sase.workspace_provider.lease.release_workspace", _release)
    return calls


class TestAuthorizeOperationalLeaseWorkspace:
    def test_legacy_primary_is_not_leasable(self) -> None:
        with pytest.raises(_OperationalLeaseError, match="legacy #1") as exc_info:
            _authorize_operational_lease_workspace(1)
        assert "left untouched" in str(exc_info.value)
        assert exc_info.value.resumable is True

    def test_reserved_and_out_of_range_are_not_leasable(self) -> None:
        with pytest.raises(_OperationalLeaseError, match="reserved workspace"):
            _authorize_operational_lease_workspace(5)
        with pytest.raises(_OperationalLeaseError, match="unified claim pool"):
            _authorize_operational_lease_workspace(1000)

    def test_unified_pool_number_is_accepted(self) -> None:
        assert _authorize_operational_lease_workspace(10) == 10
        assert _authorize_operational_lease_workspace(42) == 42


class TestAcquireAndContextManager:
    def test_acquire_exposes_checkout_and_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        _patch_acquire_steps(monkeypatch, checkout=checkout, primary=primary)

        lease = acquire_operational_lease(
            "demo",
            workflow="chop:demo",
            holder="axe",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )

        assert lease.workspace_num == 10
        assert lease.checkout_dir == checkout
        assert lease.checkout_dir != primary.resolve()
        assert lease.operation_context.access_kind is AccessKind.LEASED_OPERATIONAL
        assert lease.operation_context.is_primary is False
        policy = lease.settlement_policy()
        assert policy["kind"] == OPERATIONAL_LEASE_POLICY_KIND
        assert policy["workspace_num"] == 10
        assert policy["workflow"] == "chop:demo"
        assert is_operational_lease_policy(policy)

    def test_context_manager_releases_on_success_and_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        calls = _patch_acquire_steps(monkeypatch, checkout=checkout, primary=primary)

        with operational_workspace_lease(
            "demo",
            workflow="chop:demo",
            holder="axe",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        ) as lease:
            assert lease.workspace_num == 10
        assert len(calls["released"]) == 1

        calls["released"].clear()
        with pytest.raises(RuntimeError, match="boom"):
            with operational_workspace_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
                config=_adjacent_config(),
                env={},
            ):
                raise RuntimeError("boom")
        assert len(calls["released"]) == 1

    def test_allocation_failure_does_not_touch_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        marker = primary / "user.txt"
        marker.write_text("keep", encoding="utf-8")
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)

        def _claim(*_args: object, **_kwargs: object) -> int:
            raise WorkspaceClaimError("all workspaces are claimed")

        monkeypatch.setattr(
            "sase.workspace_provider.lease.claim_next_axe_workspace",
            _claim,
        )

        with pytest.raises(_OperationalLeaseError, match="allocation") as exc_info:
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        assert "left untouched" in str(exc_info.value)
        assert marker.read_text(encoding="utf-8") == "keep"
        assert "primary" not in str(exc_info.value).lower() or "left untouched" in str(
            exc_info.value
        )

    def test_materialization_failure_releases_claim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)

        def _materialize(*_args: object, **_kwargs: object) -> Path:
            raise _OperationalLeaseError("materialization", "clone failed")

        calls = _patch_acquire_steps(
            monkeypatch,
            checkout=checkout,
            primary=primary,
            materialize=_materialize,
        )

        with pytest.raises(_OperationalLeaseError, match="materialization"):
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        assert calls["released"] == [
            (str(project_file.resolve()), 10, "chop:demo", "axe")
        ]

    def test_prepare_failure_releases_claim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)

        def _prepare(_checkout: Path) -> None:
            raise _OperationalLeaseError("preparation", "git fetch failed")

        calls = _patch_acquire_steps(
            monkeypatch,
            checkout=checkout,
            primary=primary,
            prepare=_prepare,
        )

        with pytest.raises(_OperationalLeaseError, match="preparation"):
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        assert calls["released"][0][1] == 10

    def test_claimed_primary_number_is_not_released_as_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        released: list[int] = []

        monkeypatch.setattr(
            "sase.workspace_provider.lease.claim_next_axe_workspace",
            lambda *_args, **_kwargs: PRIMARY_WORKSPACE_NUM,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease.release_workspace",
            lambda *_args, **kwargs: released.append(kwargs.get("workspace_num", -1)),
        )

        with pytest.raises(_OperationalLeaseError, match="primary workspace"):
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        assert released == []


class TestDurableSubmission:
    def test_bind_sets_cwd_policy_and_workspace_num(self, tmp_path: Path) -> None:
        lease = _lease(tmp_path)
        request = ProcSubmitRequest(
            argv=["true"],
            label="demo",
            cwd=tmp_path / "elsewhere",
            origin="test",
            project="demo",
        )
        bound = _bind_operational_lease(request, lease)
        assert Path(bound.cwd) == lease.checkout_dir
        assert bound.workspace_num == 10
        assert bound.workspace_claim is not None
        assert bound.workspace_claim["kind"] == OPERATIONAL_LEASE_POLICY_KIND

    def test_submit_transfers_after_ack_and_keeps_claim_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lease = _lease(tmp_path)
        captured: dict[str, Any] = {}

        def _submit(request: ProcSubmitRequest, after_ack: Any = None) -> Any:
            captured["request"] = request
            proc = SimpleNamespace(proc_id="proc-1", pid=4242)
            if after_ack is not None:
                after_ack(proc)
            return proc

        transferred = MagicMock()
        released = MagicMock()
        monkeypatch.setattr(
            "sase.procs.service.submit_proc_request",
            _submit,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease._transfer_operational_lease",
            transferred,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease.release_operational_lease",
            released,
        )

        request = ProcSubmitRequest(
            argv=["true"],
            label="demo",
            cwd=tmp_path,
            origin="test",
            project="demo",
        )
        proc = submit_via_lease(request, lease)

        assert proc.pid == 4242
        assert Path(captured["request"].cwd) == lease.checkout_dir
        transferred.assert_called_once()
        released.assert_not_called()

    def test_submit_releases_on_pre_transfer_spawn_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lease = _lease(tmp_path)

        def _submit(_request: ProcSubmitRequest, after_ack: Any = None) -> Any:
            del after_ack
            raise RuntimeError("could not start proc supervisor")

        released = MagicMock()
        monkeypatch.setattr(
            "sase.procs.service.submit_proc_request",
            _submit,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease.release_operational_lease",
            released,
        )

        request = ProcSubmitRequest(
            argv=["true"],
            label="demo",
            cwd=tmp_path,
            origin="test",
            project="demo",
        )
        with pytest.raises(RuntimeError, match="supervisor"):
            submit_via_lease(request, lease)
        released.assert_called_once_with(lease)

    def test_transfer_failure_names_the_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lease = _lease(tmp_path)
        monkeypatch.setattr(
            "sase.workspace_provider.lease.transfer_workspace_claim",
            lambda *_args, **_kwargs: SimpleNamespace(
                success=False, error="workspace #10 with pid 111 was not found"
            ),
        )
        with pytest.raises(_OperationalLeaseError, match="transfer") as exc_info:
            _transfer_operational_lease(
                lease, SimpleNamespace(proc_id="proc-1", pid=4242)
            )
        assert "left untouched" in str(exc_info.value)


class TestSettlement:
    def test_operational_lease_settles_even_for_monitor_like_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lease = _lease(tmp_path)
        released: list[int] = []

        def _release(
            project_file: str,
            workspace_num: int,
            workflow: str | None = None,
            cl_name: str | None = None,
        ) -> None:
            del project_file, workflow, cl_name
            released.append(workspace_num)

        monkeypatch.setattr(
            "sase.workspace_provider.lease.release_workspace",
            _release,
        )
        state = {
            "checkpoints": {"claim_settled": False},
            "proc_id": "proc-1",
            "followup": {"kind": "monitor"},
            "workspace_claim": lease.settlement_policy(),
        }
        _settle_workspace_claim(state)
        assert released == [10]

    def test_non_operational_monitor_policy_is_still_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        released = MagicMock()
        monkeypatch.setattr(
            "sase.procs.settlement.release_workspace",
            released,
        )
        state = {
            "checkpoints": {"claim_settled": False},
            "proc_id": "proc-1",
            "followup": {"kind": "monitor"},
            "workspace_claim": {
                "project_file": "/tmp/demo.sase",
                "workspace_num": 10,
                "workflow": "monitor",
                "cl_name": "demo",
            },
        }
        _settle_workspace_claim(state)
        released.assert_not_called()

    def test_release_operational_lease_ignores_non_lease_policy(self) -> None:
        release_operational_lease(
            {
                "project_file": "/tmp/demo.sase",
                "workspace_num": 10,
                "workflow": "monitor",
            }
        )


class TestPrepareFromRemote:
    def test_missing_git_dir_is_a_preparation_error(self, tmp_path: Path) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        checkout = tmp_path / "empty"
        checkout.mkdir()
        with pytest.raises(_OperationalLeaseError, match="preparation"):
            _prepare_from_primary_remote(checkout)

    def test_prepare_fast_forwards_to_origin_head(self, tmp_path: Path) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True)
        seed = tmp_path / "seed"
        seed.mkdir()
        _init_git(seed)
        (seed / "README").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-qm", "one"], cwd=seed, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote)], cwd=seed, check=True
        )
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True)

        checkout = tmp_path / "lease"
        subprocess.run(["git", "clone", str(remote), str(checkout)], check=True)
        (seed / "README").write_text("two\n", encoding="utf-8")
        subprocess.run(["git", "add", "README"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "-qm", "two"], cwd=seed, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True)

        _prepare_from_primary_remote(checkout)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        remote_head = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=remote,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert head == remote_head
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"


def _init_git(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
