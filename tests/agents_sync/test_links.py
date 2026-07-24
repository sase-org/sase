from __future__ import annotations

from pathlib import Path
import subprocess

from sase.agents_sync.links import resolve_agent_commit_tag
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.commit_footer_facade import LinkedCommitTagValue


def _git_result(
    _cwd: Path,
    args: list[str],
    *,
    network: bool = False,
    op: str = "",
) -> subprocess.CompletedProcess[str]:
    del network, op
    if args[:3] == ["symbolic-ref", "--quiet", "--short"]:
        return subprocess.CompletedProcess(args, 0, "main\n", "")
    raise AssertionError(args)


def test_family_member_commit_tag_links_to_stable_member_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "sidecar"
    (sidecar / ".git").mkdir(parents=True)
    target = ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        sidecar,
        "git@github.com:acme/project--agents.git",
    )
    monkeypatch.setattr(
        "sase.workflows.utils.get_project_from_workspace",
        lambda: "Project",
    )
    monkeypatch.setattr(
        "sase.agents_sync.links.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )

    value = resolve_agent_commit_tag(
        "foo.bar--code",
        identity=AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena")),
        cwd=primary,
        git_runner=_git_result,
    )

    assert value == LinkedCommitTagValue(
        "alice.athena.foo.bar--code",
        "https://github.com/acme/project--agents/blob/main/"
        "families/alice.athena.foo.bar.md#member-code",
    )


def test_commit_tag_falls_back_to_global_label_for_non_hosted_sidecar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    sidecar = tmp_path / "sidecar"
    (sidecar / ".git").mkdir(parents=True)
    target = ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        sidecar,
        str(tmp_path / "remote.git"),
    )
    monkeypatch.setattr(
        "sase.workflows.utils.get_project_from_workspace",
        lambda: "Project",
    )
    monkeypatch.setattr(
        "sase.agents_sync.links.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )

    assert (
        resolve_agent_commit_tag(
            "solo",
            identity=AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena")),
            cwd=primary,
            git_runner=_git_result,
        )
        == "alice.athena.solo"
    )
