"""Quarantine namespace safety across load, persistence, snapshot, and doctor."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import ArtifactLinkEventCorruptionError
from sase.sdd._artifact_link_event_quarantine import (
    load_artifact_link_quarantine_records,
    persist_artifact_link_quarantine_record,
)
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
)


def _canonical_json(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_canonical_json")(event))


def _finding():
    pair = (
        edge_event(
            "b" * 32,
            target="plan:202610/path-winner.md",
            description="winner",
        ),
        edge_event(
            "b" * 32,
            target="plan:202610/path-rejected.md",
            description="rejected",
        ),
    )
    snapshot = reduce_artifact_link_event_inputs(durable_events=pair, strict=True)
    return snapshot.quarantine_findings[0]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "SASE Tests")
    _git(root, "config", "user.email", "sase@example.test")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_fixture(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")


def _tree_state(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    state: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if path.is_symlink():
            state[relative.as_posix()] = ("symlink", os.readlink(path))
        elif path.is_file():
            state[relative.as_posix()] = ("file", path.read_bytes())
        elif path.is_dir():
            state[relative.as_posix()] = ("directory", None)
    return state


def test_load_rejects_live_staging_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    namespace = root / "link-events" / "quarantine" / "v1"
    namespace.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (namespace / ".staging").symlink_to(outside, target_is_directory=True)

    findings, errors = load_artifact_link_quarantine_records((root,))

    assert findings == ()
    assert any(".staging" in error and "symlink" in error for error in errors)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "shape",
    (
        "operation-file",
        "operation-broken-symlink",
        "namespace-symlink",
        "staging-broken-symlink",
    ),
)
def test_persist_rejects_unsafe_directories_before_open_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    from sase.sdd import _artifact_link_event_install as install_module

    root = tmp_path / "store"
    finding = _finding()
    relative = Path(
        str(
            require_rust_binding("artifact_link_quarantine_record_path")(
                finding.operation_id, finding.rejected_digest
            )
        )
    )
    version_root = root / "link-events" / "quarantine" / "v1"
    outside = tmp_path / "outside"
    outside.mkdir()
    version_root.mkdir(parents=True)
    operation_dir = root / relative.parent

    if shape == "operation-file":
        operation_dir.write_bytes(b"not a directory")
    elif shape == "operation-broken-symlink":
        operation_dir.symlink_to(
            tmp_path / "missing-operation", target_is_directory=True
        )
    elif shape == "namespace-symlink":
        (root / "link-events" / "quarantine" / "v1").rmdir()
        (root / "link-events" / "quarantine" / "v1").symlink_to(
            outside, target_is_directory=True
        )
    else:
        (version_root / ".staging").symlink_to(
            tmp_path / "missing-staging", target_is_directory=True
        )

    writes: list[Path] = []
    real_open = install_module.os.open

    def observe_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if flags & install_module.os.O_CREAT:
            writes.append(Path(path).resolve(strict=False))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(install_module.os, "open", observe_open)
    before_outside = _tree_state(outside)
    with pytest.raises(ArtifactLinkEventCorruptionError):
        persist_artifact_link_quarantine_record(
            root,
            finding,
            rejected_canonical_json=_canonical_json(finding.rejected_event),
        )

    assert writes == []
    assert _tree_state(outside) == before_outside
    assert not (root / relative).exists()


def test_symlinked_root_ancestor_reuses_with_real_staging_directory(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-store"
    real_root.mkdir()
    linked_root = tmp_path / "linked-store"
    linked_root.symlink_to(real_root, target_is_directory=True)
    staging = real_root / "link-events" / "quarantine" / "v1" / ".staging"
    staging.mkdir(parents=True)
    finding = _finding()
    rejected_json = _canonical_json(finding.rejected_event)

    relative = persist_artifact_link_quarantine_record(
        linked_root,
        finding,
        rejected_canonical_json=rejected_json,
    )
    original = (real_root / relative).read_bytes()
    reused = persist_artifact_link_quarantine_record(
        linked_root,
        finding,
        rejected_canonical_json=rejected_json,
    )

    assert reused == relative
    assert (real_root / relative).read_bytes() == original
    loaded, errors = load_artifact_link_quarantine_records((linked_root,))
    assert errors == ()
    assert len(loaded) == 1


@pytest.mark.parametrize("shape", ("operation-file", "staging-broken-symlink"))
def test_snapshot_and_doctor_report_quarantine_corruption_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    root = tmp_path / "plans"
    _init_repo(root)
    version_root = root / "link-events" / "quarantine" / "v1"
    version_root.mkdir(parents=True)
    if shape == "operation-file":
        (version_root / ("c" * 32)).write_bytes(b"not a directory")
    else:
        (version_root / ".staging").symlink_to(
            tmp_path / "missing-staging", target_is_directory=True
        )
    _commit_fixture(root)
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={"plan": root})
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    before_tree = _tree_state(root)
    before_status = _git(root, "status", "--porcelain")

    snapshot = store.artifact_link_event_snapshot(strict=False)
    assert any(
        item.kind == "invalid-quarantine" for item in snapshot.validation_findings
    )
    with pytest.raises(RuntimeError, match="invalid"):
        store.artifact_link_event_snapshot(strict=True)
    report = inspect_artifact_link_health()

    assert report.healthy is False
    assert report.event_validation_failures
    assert any("quarantine" in item for item in report.event_validation_failures)
    assert _tree_state(root) == before_tree
    assert _git(root, "status", "--porcelain") == before_status
