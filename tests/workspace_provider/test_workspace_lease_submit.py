"""Operational workspace lease submission and settlement (sase-mq.2)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.procs.request import ProcSubmitRequest
from sase.procs.settlement import _settle_workspace_claim
from sase.workspace_provider.lease import (
    OPERATIONAL_LEASE_POLICY_KIND,
    OperationalLease,
    _OperationalLeaseError as OperationalLeaseError,
    _bind_operational_lease as bind_operational_lease,
    _transfer_operational_lease as transfer_operational_lease,
    release_operational_lease,
    submit_via_lease,
)
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)


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
        bound = bind_operational_lease(request, lease)
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
            "sase.procs.submission.submit_proc_request",
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
            "sase.procs.submission.submit_proc_request",
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
        with pytest.raises(OperationalLeaseError, match="transfer") as exc_info:
            transfer_operational_lease(
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
