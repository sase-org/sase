"""``sase artifact create --bead`` attaches the reference it just minted."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.artifact_cli.create import handle_create
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead.work import SASE_BEAD_ID_ENV


def _args(path: Path, *, bead: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        path=str(path),
        label="Report",
        kind=None,
        move=False,
        bead=bead,
    )


@pytest.fixture
def agent_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    """Return a source file and the id of a bead in a real store under cwd."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with BeadProject.init(workspace) as project:
        bead = project.create("Cited work", IssueType.PLAN)
    beads_dir = project.beads_dir

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.delenv(SASE_BEAD_ID_ENV, raising=False)
    monkeypatch.chdir(workspace)

    # This fixture is a bare bead store, not a registered SASE project, so
    # the full checkout-anchor resolution `resolve_artifact_link_store` uses
    # in a real agent workspace has nothing to find. Point it at this test's
    # own store directly instead of registering a whole project.
    import sase.sdd.artifact_link_store as artifact_link_store_module
    from sase.sdd.artifact_link_store import ArtifactLinkStore

    monkeypatch.setattr(
        artifact_link_store_module,
        "resolve_artifact_link_store",
        lambda: ArtifactLinkStore(
            project_key="test-project", sidecar_roots={}, beads_dir=beads_dir
        ),
    )
    return source, bead.id


def _stored_links(workspace: Path, bead_id: str) -> list[str]:
    with BeadProject(workspace) as project:
        issue = project.show(bead_id)
        # The bead is the target of the ``related`` row this call writes
        # (the artifact is the source), so it is stored inbound.
        return [
            link.target_ref
            for link in issue.links
            if link.relation == "related" and link.direction == "in"
        ]


def test_an_explicit_bead_id_receives_the_minted_reference(
    agent_workspace: tuple[Path, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, bead_id = agent_workspace

    assert handle_create(_args(source, bead=bead_id)) == 0

    output = capsys.readouterr().out
    reference = next(
        line.removeprefix("ref: ")
        for line in output.splitlines()
        if line.startswith("ref: ")
    )
    assert f"bead: {bead_id}" in output
    assert _stored_links(Path.cwd(), bead_id) == [reference]


def test_a_bare_flag_attaches_to_the_agents_own_bead(
    agent_workspace: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, bead_id = agent_workspace
    monkeypatch.setenv(SASE_BEAD_ID_ENV, bead_id)

    assert handle_create(_args(source, bead="")) == 0

    output = capsys.readouterr().out
    assert f"bead: {bead_id}" in output
    stored = _stored_links(Path.cwd(), bead_id)
    assert len(stored) == 1
    assert stored[0].startswith("file:explicit:")


def test_a_bare_flag_without_a_bead_in_the_environment_fails_loudly(
    agent_workspace: tuple[Path, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, _bead_id = agent_workspace

    assert handle_create(_args(source, bead="")) == 1

    captured = capsys.readouterr()
    assert SASE_BEAD_ID_ENV in captured.err
    # The artifact must not be created when the attachment cannot happen.
    assert "ref: file:" not in captured.out


def test_an_unknown_bead_id_fails_before_the_artifact_is_created(
    agent_workspace: tuple[Path, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, _bead_id = agent_workspace

    assert handle_create(_args(source, bead="nope-99")) == 1

    captured = capsys.readouterr()
    assert "bead not found: nope-99" in captured.err
    assert "ref: file:" not in captured.out


def test_omitting_the_flag_leaves_every_bead_untouched(
    agent_workspace: tuple[Path, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, bead_id = agent_workspace

    assert handle_create(_args(source, bead=None)) == 0

    output = capsys.readouterr().out
    assert "ref: file:explicit:" in output
    assert "bead:" not in output
    assert _stored_links(Path.cwd(), bead_id) == []
