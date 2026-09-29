"""Path and preflight policy coverage for sidecar initialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd._sidecar_init import (
    SidecarInitSpec,
    preflight_sidecars,
    sidecar_clone_root,
)
from sase.workspace_provider import SddSidecarPreflight


def test_sidecar_clone_root_keeps_agents_machine_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda root: "gh_acme__widget" if root == str(project) else None,
    )

    assert sidecar_clone_root(project, "plans") == (
        project / "sase" / "repos" / "plans"
    )
    assert sidecar_clone_root(project, "agents") == (
        state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    )
    assert sidecar_clone_root(project, "attachments-private") == (
        state_root / "projects" / "gh_acme__widget" / "repos" / "attachments-private"
    )
    assert not state_root.exists()


def test_attachments_private_preflight_pins_reserved_role_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    captured: list[dict[str, object]] = []
    spec = SidecarInitSpec(
        role="attachments-private",
        repo="acme/widget--attachments-private",
        remote_url="https://github.com/acme/widget--attachments-private.git",
        visibility="private",
        description="Hidden sidecar that stores private bead attachment bytes.",
    )

    def preflight(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> SddSidecarPreflight:
        captured.append(options)
        return SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/widget--attachments-private",
            visibility="private",
        )

    monkeypatch.setattr("sase.workspace_provider.preflight_sdd_sidecar", preflight)

    result = preflight_sidecars(project, 1, (spec,))

    assert result["attachments-private"].visibility == "private"
    assert captured == [
        {
            "create": False,
            "provider_policy": "separate_repo",
            "sdd_sidecar_suffix": "attachments-private",
            "sdd_visibility": "private",
            "workspace_num": 1,
            "sdd_repo": "acme/widget--attachments-private",
            "sdd_remote_url": (
                "https://github.com/acme/widget--attachments-private.git"
            ),
            "sdd_description": (
                "Hidden sidecar that stores private bead attachment bytes."
            ),
        }
    ]


def test_attachments_private_preflight_rejects_public_provider_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    spec = SidecarInitSpec(role="attachments-private", visibility="private")
    monkeypatch.setattr(
        "sase.workspace_provider.preflight_sdd_sidecar",
        lambda *_args: SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/widget--attachments-private",
            visibility="public",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="config requires private",
    ):
        preflight_sidecars(project, 1, (spec,))


def test_custom_sidecar_preflight_passes_pin_visibility_and_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    captured: list[dict[str, object]] = []
    spec = SidecarInitSpec(
        role="artifacts",
        repo="acme/shared-artifacts",
        remote_url="https://github.com/acme/shared-artifacts.git",
        visibility="private",
        description="Durable build artifacts.",
    )

    def preflight(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> SddSidecarPreflight:
        captured.append(options)
        return SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/shared-artifacts",
            visibility="private",
        )

    monkeypatch.setattr("sase.workspace_provider.preflight_sdd_sidecar", preflight)

    result = preflight_sidecars(project, 1, (spec,))

    assert result["artifacts"].visibility == "private"
    assert captured == [
        {
            "create": False,
            "provider_policy": "separate_repo",
            "sdd_sidecar_suffix": "artifacts",
            "sdd_visibility": "private",
            "workspace_num": 1,
            "sdd_repo": "acme/shared-artifacts",
            "sdd_remote_url": "https://github.com/acme/shared-artifacts.git",
            "sdd_description": "Durable build artifacts.",
        }
    ]


def test_custom_sidecar_preflight_rejects_provider_visibility_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    spec = SidecarInitSpec(role="artifacts", visibility="private")
    monkeypatch.setattr(
        "sase.workspace_provider.preflight_sdd_sidecar",
        lambda *_args: SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/widget--artifacts",
            visibility="public",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="config requires private",
    ):
        preflight_sidecars(project, 1, (spec,))
