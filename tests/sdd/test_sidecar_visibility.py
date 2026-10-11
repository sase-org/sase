"""Resolver and policy coverage for private-primary sidecar visibility."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
from sase.sdd._sidecar_init import SidecarInitSpec
from sase.sdd._sidecar_visibility import (
    PrimaryRepoVisibility,
    apply_primary_visibility_policy,
    format_visibility_notes,
    resolve_primary_repo_visibility,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _spec(role: str, visibility: str = "public") -> SidecarInitSpec:
    return SidecarInitSpec(
        role=role,
        repo=f"acme/widget--{role}",
        visibility=visibility,
    )


def _default_specs() -> tuple[SidecarInitSpec, ...]:
    return (
        _spec("plans"),
        _spec("beads"),
        _spec("research"),
        _spec("agents"),
        _spec("attachments"),
        _spec("attachments-private", "private"),
    )


def test_resolver_returns_none_without_an_origin(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")

    assert resolve_primary_repo_visibility(tmp_path) is None


def test_resolver_returns_none_for_a_local_path_origin(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path / "elsewhere"))

    assert resolve_primary_repo_visibility(tmp_path) is None


@pytest.mark.parametrize("visibility", ["public", "private", "unknown"])
def test_resolver_reports_the_probed_visibility(
    tmp_path: Path, visibility: str
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "remote", "add", "origin", "git@github.com:acme/widget.git")
    set_remote_visibility_prober(lambda _url: visibility)
    try:
        resolved = resolve_primary_repo_visibility(tmp_path)
    finally:
        set_remote_visibility_prober(None)

    assert resolved == PrimaryRepoVisibility(repo="acme/widget", visibility=visibility)


@pytest.mark.parametrize(
    "primary", [None, PrimaryRepoVisibility("acme/widget", "public")]
)
def test_policy_leaves_public_and_unresolvable_primaries_alone(
    primary: PrimaryRepoVisibility | None,
) -> None:
    specs = _default_specs()

    policy = apply_primary_visibility_policy(specs, primary)

    assert policy.specs == specs
    assert policy.forced_roles == ()
    assert policy.dropped_roles == ()


@pytest.mark.parametrize("visibility", ["private", "unknown"])
def test_policy_forces_private_and_drops_attachments(visibility: str) -> None:
    primary = PrimaryRepoVisibility("acme/widget", visibility)  # type: ignore[arg-type]

    policy = apply_primary_visibility_policy(_default_specs(), primary)

    by_role = {spec.role: spec for spec in policy.specs}
    assert set(by_role) == {
        "plans",
        "beads",
        "research",
        "agents",
        "attachments-private",
    }
    assert all(spec.visibility == "private" for spec in policy.specs)
    assert by_role["attachments-private"].visibility == "private"
    assert policy.forced_roles == ("plans", "beads", "research", "agents")
    assert policy.dropped_roles == ("attachments",)


def test_policy_overrides_explicit_public_and_keeps_explicit_private() -> None:
    primary = PrimaryRepoVisibility(repo="acme/widget", visibility="private")
    specs = (
        _spec("plans", "public"),
        _spec("agents", "private"),
    )

    policy = apply_primary_visibility_policy(specs, primary)

    assert [spec.visibility for spec in policy.specs] == ["private", "private"]
    assert policy.forced_roles == ("plans",)
    assert policy.dropped_roles == ()


def test_policy_notes_name_the_private_primary() -> None:
    primary = PrimaryRepoVisibility(repo="acme/widget", visibility="private")
    policy = apply_primary_visibility_policy(_default_specs(), primary)

    notes = format_visibility_notes(policy, primary)

    assert notes == (
        "note: acme/widget is private, so SASE creates its sidecar repositories "
        "as private",
        "note: skipping the public attachments sidecar because acme/widget is "
        "not verified public",
    )


def test_policy_notes_cover_an_unverifiable_primary() -> None:
    primary = PrimaryRepoVisibility(repo="acme/widget", visibility="unknown")
    policy = apply_primary_visibility_policy(_default_specs(), primary)

    notes = format_visibility_notes(policy, primary)

    assert notes[0] == (
        "note: could not verify that acme/widget is public, so SASE creates its "
        "sidecar repositories as private"
    )
    assert notes[1].startswith("note: skipping the public attachments sidecar")


def test_policy_notes_are_empty_without_changes() -> None:
    primary = PrimaryRepoVisibility(repo="acme/widget", visibility="public")
    policy = apply_primary_visibility_policy(_default_specs(), primary)

    assert format_visibility_notes(policy, primary) == ()
