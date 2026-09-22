"""Operational workspace lease acquisition (sase-mq.2)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.running_field import WorkspaceClaimError, get_claimed_workspaces
from sase.workspace_provider.lease import (
    OPERATIONAL_LEASE_POLICY_KIND,
    _OperationalLeaseError as OperationalLeaseError,
    _authorize_operational_lease_workspace as authorize_operational_lease_workspace,
    acquire_operational_lease,
    is_operational_lease_policy,
    operational_workspace_lease,
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
        with pytest.raises(OperationalLeaseError, match="legacy #1") as exc_info:
            authorize_operational_lease_workspace(1)
        assert "left untouched" in str(exc_info.value)
        assert exc_info.value.resumable is True

    def test_reserved_and_out_of_range_are_not_leasable(self) -> None:
        with pytest.raises(OperationalLeaseError, match="reserved workspace"):
            authorize_operational_lease_workspace(5)
        with pytest.raises(OperationalLeaseError, match="unified claim pool"):
            authorize_operational_lease_workspace(1000)

    def test_unified_pool_number_is_accepted(self) -> None:
        assert authorize_operational_lease_workspace(10) == 10
        assert authorize_operational_lease_workspace(42) == 42


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
        assert policy["workflow"] == "lease(chop:demo)"
        assert is_operational_lease_policy(policy)

    def test_acquire_claims_the_reserved_lease_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        claimed: dict[str, Any] = {}

        def _claim(_project_file: str, workflow: str, _pid: int, **kwargs: Any) -> int:
            claimed["workflow"] = workflow
            claimed["cl_name"] = kwargs.get("cl_name")
            return 10

        _patch_acquire_steps(
            monkeypatch, checkout=checkout, primary=primary, claim=_claim
        )

        lease = acquire_operational_lease(
            "demo",
            workflow="chop:demo",
            holder="bead_claim_checks:demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        )

        # The RUNNING field records the reserved label, and every downstream
        # consumer of the lease reports that same on-disk label.
        assert claimed["workflow"] == "lease(chop:demo)"
        assert lease.workflow == "lease(chop:demo)"
        assert lease.settlement_policy()["workflow"] == "lease(chop:demo)"
        # The holder stays the caller's identity and still backs cl_name.
        assert lease.holder == "bead_claim_checks:demo"
        assert claimed["cl_name"] == "bead_claim_checks:demo"
        assert lease.cl_name == "bead_claim_checks:demo"

    def test_lease_round_trips_through_the_running_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real claim/release: the label lands on disk and is cleaned up."""
        primary = tmp_path / "proj"
        primary.mkdir()
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            "sase.workspace_provider.lease._materialize_leased_checkout",
            lambda *_args, **_kwargs: checkout,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease._prepare_from_primary_remote",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.lease.leased_operational_context",
            lambda *_args, **_kwargs: _context(checkout, primary),
        )

        with operational_workspace_lease(
            "demo",
            workflow="chop:bead_claim_checks",
            holder="bead_claim_checks:demo",
            project_file=project_file,
            config=_adjacent_config(),
            env={},
        ) as lease:
            claims = get_claimed_workspaces(str(project_file))
            assert [(c.workflow, c.cl_name) for c in claims] == [
                ("lease(chop:bead_claim_checks)", "bead_claim_checks:demo")
            ]
            assert claims[0].workspace_num == lease.workspace_num

        assert get_claimed_workspaces(str(project_file)) == []

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

        with pytest.raises(OperationalLeaseError, match="allocation") as exc_info:
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
            raise OperationalLeaseError("materialization", "clone failed")

        calls = _patch_acquire_steps(
            monkeypatch,
            checkout=checkout,
            primary=primary,
            materialize=_materialize,
        )

        with pytest.raises(OperationalLeaseError, match="materialization"):
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        # Released under the label that was claimed, not the caller's argument.
        assert calls["released"] == [
            (str(project_file.resolve()), 10, "lease(chop:demo)", "axe")
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
            raise OperationalLeaseError("preparation", "git fetch failed")

        calls = _patch_acquire_steps(
            monkeypatch,
            checkout=checkout,
            primary=primary,
            prepare=_prepare,
        )

        with pytest.raises(OperationalLeaseError, match="preparation"):
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

        with pytest.raises(OperationalLeaseError, match="primary workspace"):
            acquire_operational_lease(
                "demo",
                workflow="chop:demo",
                holder="axe",
                project_file=project_file,
            )
        assert released == []
