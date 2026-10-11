"""Tests for the sidecar-visibility doctor check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
from sase.doctor.checks_sidecar_visibility import (
    _check_sidecar_visibility,
    sidecar_visibility_check_specs,
)
from sase.doctor.runner import DoctorContext, build_doctor_registry
from sase.sdd._sidecar_visibility import PrimaryRepoVisibility
from sase.sdd._store_types import SddSidecar, SddStoreRecord


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project="widget", sase_home=tmp_path / ".sase")


def _record(*roles: str) -> SddStoreRecord:
    return SddStoreRecord(
        schema_version=3,
        storage="sidecar_repos",
        provider="github",
        host="github.com",
        sidecars={
            role: SddSidecar(
                repo=f"acme/widget--{role}",
                remote_url=f"git@github.com:acme/widget--{role}.git",
            )
            for role in roles
        },
    )


def _stage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary: PrimaryRepoVisibility | None,
    record: SddStoreRecord | None,
    visibility_by_role: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_sidecar_visibility.resolve_current_project_record",
        lambda _context: SimpleNamespace(
            record=SimpleNamespace(workspace_dir="/tmp/widget"),
            project_name="widget",
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_sidecar_visibility.resolve_primary_repo_visibility",
        lambda _root: primary,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_sidecar_visibility.read_sdd_store_record",
        lambda _root: record,
    )
    if visibility_by_role is not None:
        set_remote_visibility_prober(
            lambda url: next(
                (
                    visibility
                    for role, visibility in visibility_by_role.items()
                    if f"widget--{role}" in url
                ),
                "unknown",
            )
        )


@pytest.fixture
def _no_prober():
    try:
        yield
    finally:
        set_remote_visibility_prober(None)


def test_skip_without_a_resolvable_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_prober: object
) -> None:
    _stage(monkeypatch, primary=None, record=_record("plans"))

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.id == "project.sidecar_visibility"
    assert check.status == "SKIP"


@pytest.mark.parametrize("visibility", ["public", "unknown"])
def test_skip_unless_the_primary_is_definitively_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _no_prober: object,
    visibility: str,
) -> None:
    _stage(
        monkeypatch,
        primary=PrimaryRepoVisibility(repo="acme/widget", visibility=visibility),  # type: ignore[arg-type]
        record=_record("plans"),
    )

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.status == "SKIP"


def test_missing_store_record_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_prober: object
) -> None:
    _stage(
        monkeypatch,
        primary=PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
        record=None,
    )

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.status == "SKIP"


def test_ok_when_every_recorded_sidecar_is_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_prober: object
) -> None:
    _stage(
        monkeypatch,
        primary=PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
        record=_record("plans", "beads"),
        visibility_by_role={"plans": "private", "beads": "private"},
    )

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.status == "OK"
    assert "are private" in check.summary


def test_ok_names_unverifiable_sidecars_without_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_prober: object
) -> None:
    _stage(
        monkeypatch,
        primary=PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
        record=_record("plans", "research"),
        visibility_by_role={"plans": "private", "research": "unknown"},
    )

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.status == "OK"
    assert "could not be verified" in check.summary


def test_warn_lists_public_sidecars_with_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_prober: object
) -> None:
    _stage(
        monkeypatch,
        primary=PrimaryRepoVisibility(repo="acme/widget", visibility="private"),
        record=_record("plans", "beads", "research"),
        visibility_by_role={
            "plans": "public",
            "beads": "private",
            "research": "public",
        },
    )

    check = _check_sidecar_visibility(_context(tmp_path))

    assert check.status == "WARN"
    assert "2 recorded sidecars" in check.summary
    assert "plans: acme/widget--plans is public" in check.details
    assert "research: acme/widget--research is public" in check.details
    assert (
        "gh repo edit acme/widget--plans --visibility private "
        "--accept-visibility-change-consequences" in check.details
    )
    assert (
        "gh repo edit acme/widget--research --visibility private "
        "--accept-visibility-change-consequences" in check.details
    )


def test_check_registered_alongside_attachment_store(tmp_path: Path) -> None:
    registry = build_doctor_registry(_context(tmp_path))

    ids = [spec.id for spec in registry.list_checks()]

    assert "project.sidecar_visibility" in ids
    assert ids.index("project.sidecar_visibility") == (
        ids.index("project.attachment_store") + 1
    )
    specs = {spec.id: spec for spec in registry.list_checks()}
    assert specs["project.sidecar_visibility"].group == "project"
    assert specs["project.sidecar_visibility"].title == "Sidecar visibility"
    assert sidecar_visibility_check_specs(_context(tmp_path))[0].id == (
        "project.sidecar_visibility"
    )
