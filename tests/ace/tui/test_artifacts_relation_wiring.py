"""Wiring: worker carriers hold a RelationIndex and panes expose it after apply."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.actions.patch._loading import (
    PatchLoadingMixin,
    _PreparedPatchLoad,
    _build_patch_relation_index,
)
from sase.ace.tui.relations import (
    build_beads_relation_index,
    build_documents_relation_index,
    build_files_relation_index,
    build_stitches_relation_index,
)
from sase.ace.tui.relations._support import relation_index_if_enabled
from sase.ace.tui.widgets.artifacts.beads_pane import (
    ArtifactsBeadsPane,
    _BeadsSnapshotResult,
)
from sase.ace.tui.widgets.artifacts.commits_collection import (
    CommitCollectionPayload,
    CommitsCollectionMixin,
)
from sase.ace.tui.widgets.artifacts.files_pane import (
    ArtifactsFilesPane,
    _FilesSnapshotResult,
)
from sase.ace.tui.widgets.artifacts.plans_pane import (
    ArtifactsDocumentsPane,
    _PlansSnapshotResult,
)
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.filter_query import CommitLogFilterValues
from sase.vcs_log.models import VcsLogResult
from tests.ace.tui._artifacts_beads_helpers import snapshot as beads_snapshot
from tests.ace.tui._artifacts_files_helpers import artifact_file
from tests.ace.tui._artifacts_files_helpers import snapshot as files_snapshot
from tests.ace.tui._artifacts_plans_helpers import _snapshot as plans_snapshot


def _patch(name: str = "root") -> Patch:
    return Patch(
        name=name,
        description="d",
        parent=None,
        status="Ready",
        file_path="/tmp/demo.sase",
        line_number=1,
    )


def test_patches_worker_carrier_and_pane_expose_index() -> None:
    patches = [_patch()]
    index = _build_patch_relation_index(patches)
    prepared = _PreparedPatchLoad(patches, None, {}, index)
    assert prepared.relation_index is not None
    assert prepared.relation_index.pane_id == "patches"
    holder = SimpleNamespace(
        _all_patches=patches,
        _patch_relation_index=None,
        _patch_relation_index_for_id=None,
    )
    PatchLoadingMixin._store_patch_relation_index(holder, patches, index)
    assert PatchLoadingMixin.relation_index(holder) is index


def test_beads_worker_carrier_and_pane_expose_index(tmp_path: Path) -> None:
    contract = compile_builtin_contract("beads", label="Bead", icon="x", accent="#0")
    pane = ArtifactsBeadsPane(contract=contract)
    snapshot = beads_snapshot(tmp_path)
    index = relation_index_if_enabled(
        contract,
        lambda compiled: build_beads_relation_index(snapshot, contract=compiled),
    )
    result = _BeadsSnapshotResult(
        snapshot=snapshot,
        filter_index=None,  # type: ignore[arg-type]
        query_index=None,  # type: ignore[arg-type]
        initial_query_result=None,
        relation_index=index,
    )
    assert result.relation_index is not None
    assert result.relation_index.pane_id == "beads"
    pane._relation_index = result.relation_index
    assert pane.relation_index() is result.relation_index


def test_files_worker_carrier_and_pane_expose_index() -> None:
    contract = compile_builtin_contract("files", label="File", icon="x", accent="#0")
    pane = ArtifactsFilesPane(contract=contract)
    snapshot = files_snapshot((artifact_file("one"),), project="alpha")
    index = relation_index_if_enabled(
        contract,
        lambda compiled: build_files_relation_index(snapshot, contract=compiled),
    )
    result = _FilesSnapshotResult(
        snapshot=snapshot,
        query_index=None,  # type: ignore[arg-type]
        initial_query_result=None,
        relation_index=index,
    )
    assert result.relation_index is not None
    assert result.relation_index.pane_id == "files"
    pane._relation_index = result.relation_index
    assert pane.relation_index() is result.relation_index


def test_documents_worker_carrier_and_pane_expose_index(tmp_path: Path) -> None:
    from sase.ace.tui._artifact_tab_contract import compile_provider_contract

    contract = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="x",
        accent="#0",
        spec=None,
        provider_spec_digest="w",
    ).contract
    pane = ArtifactsDocumentsPane(contract=contract)
    snapshot = plans_snapshot(tmp_path)
    index = relation_index_if_enabled(
        contract,
        lambda compiled: build_documents_relation_index(snapshot, contract=compiled),
    )
    result = _PlansSnapshotResult(
        snapshot=snapshot,
        filter_index=None,  # type: ignore[arg-type]
        query_index=None,  # type: ignore[arg-type]
        initial_query_result=None,
        relation_index=index,
    )
    assert result.relation_index is not None
    assert result.relation_index.pane_id == "ref:plan"
    pane._relation_index = result.relation_index
    assert pane.relation_index() is result.relation_index


def test_stitches_worker_carrier_and_pane_expose_index() -> None:
    contract = compile_builtin_contract("stitches", label="S", icon="x", accent="#0")
    commit = AggregatedCommitWire(
        "sase",
        VcsCommitWire(
            full_id="aaa",
            short_id="aaa",
            author_name="Ada",
            author_email="ada@example.com",
            timestamp=1,
            subject="feat",
            body="",
        ),
    )
    result = VcsLogResult(repos=(), commits=(commit,), warnings=())
    index = relation_index_if_enabled(
        contract,
        lambda compiled: build_stitches_relation_index(
            result.commits,
            contract=compiled,
            project_keys_by_repo={"sase": "sase"},
        ),
    )
    payload = CommitCollectionPayload(result, None, None, index)  # type: ignore[arg-type]
    assert payload.relation_index is not None
    assert payload.relation_index.pane_id == "stitches"
    pane = SimpleNamespace(
        result=result,
        filters=CommitLogFilterValues(),
        _relation_indexes_by_result={id(result): index},
        _preview_base=None,
        _authoritative_snapshot=lambda values: None,
    )
    assert CommitsCollectionMixin.relation_index(pane) is index
    assert relation_index_if_enabled(None, lambda compiled: index) is None
