"""Background bead writers stay off the canonical primary clone (sase-mq.5)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import subprocess
import threading

import pytest

from sase.bead.background_store import (
    WritableBeadStore,
    schedule_beads_sidecar_convergence,
    writable_bead_store_for_machine,
)
from sase.bead.claims import claim_bead_for_waiting_agent
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)

from .claims_test_helpers import writable_store_for_beads
from .sync_test_helpers import init_git_repo


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _snapshot(repo: Path) -> tuple[str, str, str]:
    head = _git(repo, "rev-parse", "HEAD").strip()
    status = _git(repo, "status", "--porcelain=v1")
    refs = _git(repo, "show-ref")
    return head, status, refs


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_git_repo(path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _context(
    checkout: Path,
    primary: Path,
    *,
    workspace_num: int = 10,
    project: str = "demo",
) -> OperationContext:
    return OperationContext(
        project=project,
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        claim_pid=1,
        claim_workflow="bead_claim",
    )


def _lease(tmp_path: Path, checkout: Path, primary: Path) -> OperationalLease:
    project_file = tmp_path / "demo.sase"
    project_file.write_text("NAME: demo\nWORKSPACE_DIR: {primary}\n", encoding="utf-8")
    return OperationalLease(
        project="demo",
        workflow="chop:bead_claim_checks",
        holder="holder",
        workspace_num=10,
        checkout_dir=checkout,
        project_file=project_file,
        claim_pid=1,
        cl_name="holder",
        context=_context(checkout, primary),
    )


def _seed_phase(root: Path) -> tuple[Path, str]:
    with BeadProject.init(root) as project:
        epic = project.create("Epic", IssueType.PLAN)
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
        beads_dir = project.beads_dir
    return beads_dir, phase.id


class TestSeparateSidecarReuse:
    def test_reuses_workspace_local_sidecar_without_leasing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "primary"
        checkout = tmp_path / "ws_10"
        beads = checkout / "sase" / "repos" / "beads"
        _init_repo(checkout)
        _init_repo(beads)
        leases: list[str] = []

        monkeypatch.setattr(
            "sase.workspace_provider.marker.find_marker_from_cwd",
            lambda _cwd: (
                checkout,
                type("Marker", (), {"workspace_num": 10})(),
            ),
        )
        monkeypatch.setattr(
            "sase.bead.background_store.leased_operational_context",
            lambda *_args, **_kwargs: _context(checkout, primary),
        )
        monkeypatch.setattr(
            "sase.bead.background_store._materialize_writable_beads",
            lambda _context: beads,
        )

        @contextmanager
        def fake_lease(*_args: object, **_kwargs: object):
            leases.append("acquired")
            yield _lease(tmp_path, checkout, primary)

        monkeypatch.setattr(
            "sase.workspace_provider.lease.operational_workspace_lease",
            fake_lease,
        )

        with writable_bead_store_for_machine(
            "demo",
            workflow="bead_claim",
            holder="wait-claim:worker",
            prefer_existing_claim=True,
        ) as store:
            assert store.reused_existing_claim is True
            assert store.beads_dir == beads
        assert leases == []

    @pytest.mark.parametrize(
        "layout",
        ["in_tree", "local", "separate_repo"],
    )
    def test_same_git_checkout_acquires_a_short_lease(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        layout: str,
    ) -> None:
        primary = tmp_path / "primary"
        checkout = tmp_path / "ws_10"
        _init_repo(checkout)
        if layout == "in_tree":
            beads = checkout / "sdd" / "beads"
        elif layout == "local":
            beads = checkout / ".sase" / "sdd" / "beads"
        else:
            beads = checkout / ".sase" / "sdd" / "beads"
        beads.mkdir(parents=True)
        (beads / "issues.jsonl").write_text("", encoding="utf-8")
        leases: list[str] = []

        monkeypatch.setattr(
            "sase.workspace_provider.marker.find_marker_from_cwd",
            lambda _cwd: (
                checkout,
                type("Marker", (), {"workspace_num": 10})(),
            ),
        )
        monkeypatch.setattr(
            "sase.bead.background_store.leased_operational_context",
            lambda *_args, **_kwargs: _context(checkout, primary),
        )
        monkeypatch.setattr(
            "sase.bead.background_store._materialize_writable_beads",
            lambda _context: beads,
        )

        @contextmanager
        def fake_lease(*_args: object, **_kwargs: object):
            leases.append("acquired")
            yield _lease(tmp_path, checkout, primary)

        monkeypatch.setattr(
            "sase.workspace_provider.lease.operational_workspace_lease",
            fake_lease,
        )

        with writable_bead_store_for_machine(
            "demo",
            workflow="bead_claim",
            holder="wait-claim:worker",
            prefer_existing_claim=True,
        ) as store:
            assert store.reused_existing_claim is False
            assert store.beads_dir == beads
        assert leases == ["acquired"]

    def test_sidecar_mode_reuses_when_beads_are_their_own_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "primary"
        checkout = tmp_path / "ws_11"
        beads = checkout / "sase" / "repos" / "beads"
        _init_repo(checkout)
        _init_repo(beads)
        monkeypatch.setattr(
            "sase.workspace_provider.marker.find_marker_from_cwd",
            lambda _cwd: (
                checkout,
                type("Marker", (), {"workspace_num": 11})(),
            ),
        )
        monkeypatch.setattr(
            "sase.bead.background_store.leased_operational_context",
            lambda *_args, **_kwargs: _context(checkout, primary, workspace_num=11),
        )
        monkeypatch.setattr(
            "sase.bead.background_store._materialize_writable_beads",
            lambda _context: beads,
        )
        acquired = False

        @contextmanager
        def fake_lease(*_args: object, **_kwargs: object):
            nonlocal acquired
            acquired = True
            yield _lease(tmp_path, checkout, primary)

        monkeypatch.setattr(
            "sase.workspace_provider.lease.operational_workspace_lease",
            fake_lease,
        )
        with writable_bead_store_for_machine(
            "demo",
            workflow="bead_claim",
            holder="wait-claim:worker",
            prefer_existing_claim=True,
        ) as store:
            assert isinstance(store, WritableBeadStore)
            assert store.reused_existing_claim is True
        assert acquired is False


class TestPrimaryRemainsUntouched:
    def test_claim_and_hint_leave_primary_and_sidecar_head_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "primary"
        primary_sidecar = tmp_path / "primary-beads"
        leased = tmp_path / "leased"
        _init_repo(primary)
        _init_repo(primary_sidecar)
        leased.mkdir(parents=True)
        init_git_repo(leased)
        beads_dir, bead_id = _seed_phase(leased)
        subprocess.run(["git", "add", "sdd"], cwd=leased, check=True)
        subprocess.run(
            ["git", "commit", "-m", "beads"],
            cwd=leased,
            check=True,
            capture_output=True,
        )
        before_primary = _snapshot(primary)
        before_sidecar = _snapshot(primary_sidecar)
        hints: list[tuple[str, str]] = []

        @contextmanager
        def fake_store(project: str, **_kwargs: object):
            yield writable_store_for_beads(beads_dir, project=project)

        monkeypatch.setattr(
            "sase.bead.background_store.writable_bead_store_for_machine",
            fake_store,
        )
        monkeypatch.setattr(
            "sase._sidecar_sync_hints.mark_sidecar_sync_hint",
            lambda project, role: hints.append((project, role)),
        )
        monkeypatch.setattr(
            "sase.bead.sync.publish_bead_claim", lambda *_args, **_kwargs: None
        )

        assert claim_bead_for_waiting_agent(
            project_name="demo",
            bead_id=bead_id,
            agent_name="worker",
        )
        with BeadProject(leased) as project:
            issue = project.show(bead_id)
            assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

        assert _snapshot(primary) == before_primary
        assert _snapshot(primary_sidecar) == before_sidecar
        assert hints == [("demo", "beads")]

    def test_auto_sync_is_not_invoked_from_the_mutation_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        leased = tmp_path / "leased"
        leased.mkdir(parents=True)
        init_git_repo(leased)
        beads_dir, bead_id = _seed_phase(leased)
        subprocess.run(["git", "add", "sdd"], cwd=leased, check=True)
        subprocess.run(
            ["git", "commit", "-m", "beads"],
            cwd=leased,
            check=True,
            capture_output=True,
        )
        sync_calls: list[str] = []

        @contextmanager
        def fake_store(project: str, **_kwargs: object):
            yield writable_store_for_beads(beads_dir, project=project)

        monkeypatch.setattr(
            "sase.bead.background_store.writable_bead_store_for_machine",
            fake_store,
        )
        monkeypatch.setattr(
            "sase.bead.sync.publish_bead_claim", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr(
            "sase._sidecar_auto_sync.sync_primary_sidecar_role",
            lambda *_args, **_kwargs: sync_calls.append("sync"),
        )
        monkeypatch.setattr(
            "sase.bead.sync.refresh_bead_store",
            lambda path: sync_calls.append(f"refresh:{path}"),
        )

        assert claim_bead_for_waiting_agent(
            project_name="demo",
            bead_id=bead_id,
            agent_name="worker",
        )
        assert sync_calls == []


class TestConcurrentWriters:
    def test_claim_and_mirror_writers_do_not_share_or_touch_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "primary"
        _init_repo(primary)
        before = _snapshot(primary)
        claim_root = tmp_path / "claim-lease"
        mirror_root = tmp_path / "mirror-lease"
        claim_root.mkdir()
        mirror_root.mkdir()
        init_git_repo(claim_root)
        init_git_repo(mirror_root)
        claim_beads, bead_id = _seed_phase(claim_root)
        mirror_beads, _mirror_id = _seed_phase(mirror_root)
        for root in (claim_root, mirror_root):
            subprocess.run(["git", "add", "sdd"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-m", "beads"],
                cwd=root,
                check=True,
                capture_output=True,
            )

        stores = {
            "claim": writable_store_for_beads(claim_beads, project="demo"),
            "mirror": writable_store_for_beads(mirror_beads, project="demo"),
        }
        assigned: dict[int, str] = {}

        @contextmanager
        def fake_store(_project: str, **kwargs: object):
            holder = str(kwargs.get("holder", ""))
            key = "mirror" if "external_issue_mirror" in holder else "claim"
            assigned[threading.get_ident()] = key
            yield stores[key]

        monkeypatch.setattr(
            "sase.bead.background_store.writable_bead_store_for_machine",
            fake_store,
        )
        monkeypatch.setattr(
            "sase.bead.sync.publish_bead_claim", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr(
            "sase.bead.background_store.schedule_beads_sidecar_convergence",
            lambda _project: None,
        )

        errors: list[BaseException] = []

        def claim() -> None:
            try:
                claim_bead_for_waiting_agent(
                    project_name="demo",
                    bead_id=bead_id,
                    agent_name="worker",
                )
            except BaseException as exc:  # noqa: BLE001 - collect sibling failure.
                errors.append(exc)

        def mirror_write() -> None:
            try:
                from sase.external_mirror._issue_apply import apply_issue_mirror
                from sase.external_mirror._issue_models import MirrorBudget

                apply_issue_mirror(
                    beads_dir=mirror_beads,
                    project_key="demo",
                    create_candidates=[],
                    transition_candidates=[],
                    budget=MirrorBudget(),
                    mutation_origin="machine",
                    operation_context=stores["mirror"].context,
                )
            except BaseException as exc:  # noqa: BLE001 - collect sibling failure.
                errors.append(exc)

        claim_thread = threading.Thread(target=claim)
        mirror_thread = threading.Thread(target=mirror_write)
        claim_thread.start()
        mirror_thread.start()
        claim_thread.join(timeout=5)
        mirror_thread.join(timeout=5)
        assert errors == []
        assert _snapshot(primary) == before
        with BeadProject(claim_root) as project:
            issue = project.show(bead_id)
            assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")


def test_schedule_beads_sidecar_convergence_records_a_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase._sidecar_sync_hints.sase_subdir", lambda name: tmp_path / name
    )
    schedule_beads_sidecar_convergence("demo")
    from sase._sidecar_sync_hints import pending_sidecar_sync_roles

    assert pending_sidecar_sync_roles("demo") == ("beads",)


def test_chops_always_lease_even_inside_a_claimed_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    checkout = tmp_path / "ws_10"
    beads = checkout / "sase" / "repos" / "beads"
    _init_repo(checkout)
    _init_repo(beads)
    leases: list[str] = []
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (checkout, type("Marker", (), {"workspace_num": 10})()),
    )
    monkeypatch.setattr(
        "sase.bead.background_store.leased_operational_context",
        lambda *_args, **_kwargs: _context(checkout, primary),
    )
    monkeypatch.setattr(
        "sase.bead.background_store._materialize_writable_beads",
        lambda _context: beads,
    )

    @contextmanager
    def fake_lease(*_args: object, **_kwargs: object):
        leases.append("acquired")
        yield _lease(tmp_path, checkout, primary)

    monkeypatch.setattr(
        "sase.workspace_provider.lease.operational_workspace_lease",
        fake_lease,
    )

    with writable_bead_store_for_machine(
        "demo",
        workflow="chop:bead_claim_checks",
        holder="bead_claim_checks:demo",
        prefer_existing_claim=False,
    ) as store:
        assert store.reused_existing_claim is False
    assert leases == ["acquired"]
