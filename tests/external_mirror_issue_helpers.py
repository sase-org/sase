"""Shared fixtures and helpers for external issue mirror tests."""

from __future__ import annotations

from pathlib import Path

import pluggy
import pytest

from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.external_mirror.issues import DEFAULT_BUDGET, run_issue_mirror_for_project
from sase.vcs_provider import VCSHookSpec, VCSPluginManager
from sase.vcs_provider._types import IssueWire

_WORKSPACE_DIR = "/repo"


def provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def issue(
    number: int,
    *,
    state: str = "open",
    title: str | None = None,
    body: str = "",
    labels: tuple[str, ...] = (),
    updated_at: str = "2026-08-10T18:00:00Z",
    provider_id: str | None = None,
) -> IssueWire:
    return IssueWire(
        number=number,
        title=title if title is not None else f"Issue {number}",
        state=state,  # type: ignore[arg-type]
        body=body,
        labels=labels,
        created_at=updated_at,
        updated_at=updated_at,
        url=f"https://example.test/issues/{number}",
        provider_id=provider_id or f"I_{number}",
    )


def install_provider(
    monkeypatch: pytest.MonkeyPatch,
    vcs_provider: object,
    *,
    listing_supported: bool = True,
) -> None:
    monkeypatch.setattr(
        "sase.external_mirror.issues.get_vcs_provider", lambda _cwd: vcs_provider
    )
    monkeypatch.setattr(
        "sase.external_mirror.issues.supports_issue_listing",
        lambda _cwd: listing_supported,
    )


def run_mirror(
    *,
    project_key: str = "sase",
    display_name: str = "sase",
    dry_run: bool = False,
    full: bool = False,
    budget=DEFAULT_BUDGET,
):
    return run_issue_mirror_for_project(
        project_key=project_key,
        display_name=display_name,
        workspace_dir=_WORKSPACE_DIR,
        dry_run=dry_run,
        full=full,
        budget=budget,
    )


def beads(beads_dir: Path) -> list:
    with open_bead_project_for_beads_dir(beads_dir) as project:
        return project.list_issues()


def create_mirrored_bead(
    beads_dir: Path,
    *,
    number: int = 42,
    status: Status = Status.OPEN,
) -> str:
    with open_bead_project_for_beads_dir(beads_dir) as project:
        bead = project.create(
            f"Mirrored {number}",
            IssueType.TASK,
            refs=[f"bug:sase#{number}"],
            external_ref=f"bug:sase#{number}",
            size=PhaseSize.SMALL,
        )
        if status is not Status.OPEN:
            bead = project.update(
                bead.id,
                status=status.value,
                assignee=(
                    "worker" if status in {Status.CLAIMED, Status.IN_PROGRESS} else ""
                ),
            )
        return bead.id


def show_bead(beads_dir: Path, bead_id: str):
    with open_bead_project_for_beads_dir(beads_dir) as project:
        return project.show(bead_id)


class RaisingProvider:
    def __init__(self, message: str) -> None:
        self._message = message

    def list_issues(self, cwd: str, state: str, limit: int) -> list[IssueWire]:
        del cwd, state, limit
        raise RuntimeError(self._message)
