"""Pure-function tests for the ``@<kind>::`` sync domain policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefDocumentExpansion
from sase.artifact_ref_sync import (
    ArtifactRefSyncPlan,
    plan_artifact_ref_sync,
    run_artifact_ref_sync,
)
from sase.sdd._store_types import SddStore


def _context(
    *,
    kind: str = "research",
    role: str = "research",
    is_pointer: bool = True,
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(),
        chats_root=Path("/chats"),
        artifact_index_path=Path("/index.json"),
        repositories=(),
        projects=(),
        document_expansions=(
            ArtifactRefDocumentExpansion(
                kind=kind,
                role=role,
                expansion_format=(
                    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
                    if is_pointer
                    else "the {checkout_path} file"
                ),
                is_pointer=is_pointer,
            ),
        ),
    )


def _store(**overrides: object) -> SddStore:
    base: dict[str, object] = {
        "storage": "sidecar_repos",
        "sdd_dir": Path("/sdd"),
        "repo_root": Path("/sdd"),
    }
    base.update(overrides)
    return SddStore(**base)  # type: ignore[arg-type]


def test_plan_mode_is_clone_when_root_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "research"
    store = _store(
        sidecar_dirs={"research": missing},
        sidecar_remote_urls={"research": "git@github.com:sase-org/sase--research.git"},
    )
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(), "research", workspace_dir=tmp_path, workspace_num=1
    )

    assert plan.mode == "clone"
    assert plan.role == "research"
    assert plan.label == "sase--research"
    assert plan.checkout == missing


def test_plan_mode_is_pull_when_root_present_and_remote_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    present = tmp_path / "research"
    present.mkdir()
    store = _store(
        sidecar_dirs={"research": present},
        sidecar_remote_urls={"research": "git@github.com:sase-org/sase--research.git"},
    )
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(), "research", workspace_dir=tmp_path, workspace_num=1
    )

    assert plan.mode == "pull"
    assert plan.role == "research"
    assert plan.label == "sase--research"
    assert plan.checkout == present


def test_plan_mode_is_rescan_when_no_remote_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    present = tmp_path / "plan"
    present.mkdir()
    store = _store(sidecar_dirs={"plan": present}, sidecar_remote_urls={})
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(kind="plan", role="plan"),
        "plan",
        workspace_dir=tmp_path,
        workspace_num=1,
    )

    assert plan.mode == "rescan"
    assert plan.label == "plan"


def test_plan_maps_bead_kind_to_beads_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    store = _store(
        beads_dir=beads_dir,
        beads_remote_url="git@github.com:sase-org/sase--beads.git",
    )
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(), "bead", workspace_dir=tmp_path, workspace_num=1
    )

    assert plan.role == "beads"
    assert plan.mode == "pull"
    assert plan.label == "sase--beads"


def test_plan_rescan_only_kind_has_no_role(tmp_path: Path) -> None:
    context = ArtifactRefContext(
        document_roots=(),
        chats_root=Path("/c"),
        artifact_index_path=Path("/i"),
        repositories=(),
        projects=(),
    )

    plan = plan_artifact_ref_sync(
        context, "file", workspace_dir=tmp_path, workspace_num=1
    )

    assert plan.role is None
    assert plan.mode == "rescan"
    assert plan.label == "file"
    assert plan.checkout is None


def test_plan_label_falls_back_to_role_when_no_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    present = tmp_path / "plan"
    present.mkdir()
    store = _store(sidecar_dirs={"plan": present}, sidecar_remote_urls={})
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(kind="plan", role="plan"),
        "plan",
        workspace_dir=tmp_path,
        workspace_num=1,
    )

    assert plan.label == "plan"


def test_plan_degrades_to_rescan_when_kind_root_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenStore(SddStore):
        def kind_root(self, kind: str) -> Path:
            raise ValueError("boom")

    store = _BrokenStore(
        storage="sidecar_repos", sdd_dir=Path("/sdd"), repo_root=Path("/sdd")
    )
    monkeypatch.setattr(
        "sase.artifact_ref_sync.resolve_sdd_store", lambda *a, **k: store
    )

    plan = plan_artifact_ref_sync(
        _context(), "research", workspace_dir=tmp_path, workspace_num=1
    )

    assert plan.mode == "rescan"
    assert plan.role == "research"
    assert plan.checkout is None


def test_run_artifact_ref_sync_rescan_ok_without_calling_ensure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "sase.artifact_ref_sync.ensure_sdd_kind_clone",
        lambda *a, **k: calls.append((a, k)),
    )
    plan = ArtifactRefSyncPlan(
        kind="file", mode="rescan", role=None, label="file", checkout=None
    )

    outcome = run_artifact_ref_sync(plan, workspace_dir=tmp_path, workspace_num=1)

    assert outcome.ok is True
    assert calls == []


def test_run_artifact_ref_sync_calls_ensure_with_fresh_and_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    def fake(
        workspace_dir: Path,
        workspace_num: int,
        role: str,
        *,
        strict: bool = False,
        fresh: bool = False,
    ) -> Path:
        calls.append((workspace_dir, workspace_num, role, strict, fresh))
        return tmp_path

    monkeypatch.setattr("sase.artifact_ref_sync.ensure_sdd_kind_clone", fake)
    plan = ArtifactRefSyncPlan(
        kind="research",
        mode="pull",
        role="research",
        label="sase--research",
        checkout=tmp_path,
    )

    outcome = run_artifact_ref_sync(plan, workspace_dir=tmp_path, workspace_num=1)

    assert outcome.ok is True
    assert calls == [(tmp_path, 1, "research", True, True)]


def test_run_artifact_ref_sync_exception_becomes_short_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError(
            "could not reach origin: connection refused after a very long "
            "timeout that should be truncated for the completion panel row"
        )

    monkeypatch.setattr("sase.artifact_ref_sync.ensure_sdd_kind_clone", fake)
    plan = ArtifactRefSyncPlan(
        kind="research",
        mode="clone",
        role="research",
        label="sase--research",
        checkout=tmp_path,
    )

    outcome = run_artifact_ref_sync(plan, workspace_dir=tmp_path, workspace_num=1)

    assert outcome.ok is False
    assert outcome.detail
    assert len(outcome.detail) <= 60
    assert "could not reach origin" in outcome.detail


def test_run_artifact_ref_sync_short_exception_is_kept_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("network unreachable")

    monkeypatch.setattr("sase.artifact_ref_sync.ensure_sdd_kind_clone", fake)
    plan = ArtifactRefSyncPlan(
        kind="research",
        mode="clone",
        role="research",
        label="sase--research",
        checkout=tmp_path,
    )

    outcome = run_artifact_ref_sync(plan, workspace_dir=tmp_path, workspace_num=1)

    assert outcome.ok is False
    assert outcome.detail == "network unreachable"
