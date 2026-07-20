"""Tests for local update-status revalidation."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import subprocess
from pathlib import Path

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.updates import (
    OutdatedComponent,
    ProviderUpdateCandidate,
    UpdateStatus,
    revalidate_provider_candidates,
    revalidate_update_status,
)
from sase.version._git import GitUpstreamStatus
from tests._update_status_helpers import agent_cli_status, git_status


def test_revalidate_update_status_drops_components_updated_locally() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )

    def _version(dist_name: str) -> str:
        if dist_name == "sase":
            return "1.1.0"
        if dist_name == "sase-github":
            return "0.5.0"
        raise importlib_metadata.PackageNotFoundError(dist_name)

    result = revalidate_update_status(status, version_fn=_version)

    assert [component.display_name for component in result.components] == ["github"]


def test_revalidate_provider_candidates_zero_candidates_does_no_work() -> None:
    def _status_fn(_names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        raise AssertionError("zero candidates must not inspect provider metadata")

    assert revalidate_provider_candidates((), status_fn=_status_fn) == ()


def test_revalidate_provider_candidates_is_named_drop_only_and_conservative() -> None:
    candidates = (
        ProviderUpdateCandidate("claude", "Claude", "1.0.0", "2.0.0"),
        ProviderUpdateCandidate("codex", "Codex", "1.0.0", "2.0.0"),
        ProviderUpdateCandidate("qwen", "Qwen", "1.0.0", "2.0.0"),
    )
    calls: list[tuple[str, ...]] = []

    def _status_fn(names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        calls.append(names)
        return (
            agent_cli_status(
                "claude",
                installed_version=None,
                version_error="timed out",
            ),
            agent_cli_status("codex", installed_version="2.0.0"),
            agent_cli_status("new-provider"),
        )

    result = revalidate_provider_candidates(candidates, status_fn=_status_fn)

    assert calls == [("claude", "codex", "qwen")]
    assert result == (candidates[0],)


def test_revalidate_provider_candidates_refreshes_manual_projection() -> None:
    candidate = ProviderUpdateCandidate("codex", "Codex", "1.0.0", "2.0.0")

    result = revalidate_provider_candidates(
        (candidate,),
        status_fn=lambda _names: (
            agent_cli_status(
                "codex",
                installed_version="1.1.0",
                install_method=InstallMethod.HOMEBREW,
            ),
        ),
    )

    assert result == (
        ProviderUpdateCandidate(
            "codex",
            "Codex",
            "1.1.0",
            "2.0.0",
            manual_only=True,
        ),
    )


@pytest.mark.parametrize(
    ("current_git_status", "expected_names"),
    [
        (git_status(ahead=0, behind=2), ["sase", "github"]),
        (git_status(ahead=0, behind=0), ["github"]),
        (git_status(ahead=2, behind=0), ["github"]),
        (git_status(ahead=1, behind=2), ["github"]),
        (git_status(ahead=0, behind=2, dirty=True), ["github"]),
    ],
)
def test_revalidate_update_status_uses_git_for_editable_components(
    current_git_status: GitUpstreamStatus,
    expected_names: list[str],
) -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0+local",
                latest_version="1.0.0+abc123",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
                install_type="wheel",
            ),
        ),
    )

    def _version(dist_name: str) -> str:
        if dist_name == "sase":
            raise AssertionError("editable revalidation must not compare versions")
        if dist_name == "sase-github":
            return "0.5.0"
        raise importlib_metadata.PackageNotFoundError(dist_name)

    result = revalidate_update_status(
        status,
        version_fn=_version,
        git_classifier_fn=lambda _path: current_git_status,
    )

    assert [component.display_name for component in result.components] == expected_names


def test_revalidate_update_status_keeps_editable_component_on_git_error() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0+local",
                latest_version="1.0.0+abc123",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
        ),
    )

    def _raise(_path: Path) -> GitUpstreamStatus:
        raise subprocess.TimeoutExpired(["git"], timeout=1.0)

    result = revalidate_update_status(
        status,
        version_fn=lambda _dist: "1.0.0",
        git_classifier_fn=_raise,
    )

    assert result == status


def test_revalidate_update_status_keeps_component_on_transient_metadata_error() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )

    result = revalidate_update_status(
        status,
        version_fn=lambda _dist: (_ for _ in ()).throw(OSError("metadata busy")),
    )

    assert result == status
