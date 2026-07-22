"""Generated-file coverage for sidecar initialization."""

from __future__ import annotations

import json
from pathlib import Path

from sase.sdd._init_files import (
    ensure_sdd_sidecar_initialized,
    expected_sdd_sidecar_files,
    plan_sdd_sidecar_init_actions,
)


def test_sidecar_generated_files_are_deterministic_and_drift_tracked(
    tmp_path: Path,
) -> None:
    for kind in ("plans", "research"):
        root = tmp_path / kind
        actions = plan_sdd_sidecar_init_actions(kind, root)
        assert {action.path.name for action in actions} == {
            "README.md",
            f"{kind}-directory-map.png",
        }

        written = ensure_sdd_sidecar_initialized(kind, root)
        assert len(written) == 2
        expected_readme = expected_sdd_sidecar_files(kind, root)[0]
        assert (root / "README.md").read_text() == expected_readme.content
        assert (
            (root / "assets" / f"{kind}-directory-map.png")
            .read_bytes()
            .startswith(b"\x89PNG\r\n\x1a\n")
        )
        assert plan_sdd_sidecar_init_actions(kind, root) == ()


def test_agents_sidecar_generated_files_are_privacy_forward_and_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"

    actions = plan_sdd_sidecar_init_actions("agents", root)

    assert {action.path.relative_to(root).as_posix() for action in actions} == {
        "README.md",
        "manifest.json",
        "agents/.gitkeep",
    }
    written = ensure_sdd_sidecar_initialized("agents", root)
    assert set(written) == {action.path for action in actions}
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "full agent chat transcripts" in readme
    assert "prompts and responses" in readme
    assert "agent metadata and commit associations" in readme
    assert "`private`" in readme
    assert "`disabled: true`" in readme
    assert "`sase agent sync`" in readme
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "agents": {},
    }
    assert (root / "agents" / ".gitkeep").read_text(encoding="utf-8") == ""
    assert plan_sdd_sidecar_init_actions("agents", root) == ()

    (root / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert plan_sdd_sidecar_init_actions("agents", root) == ()

    (root / "agents" / ".gitkeep").unlink()
    populated = root / "agents" / "athena.worker"
    populated.mkdir()
    (populated / "meta.json").write_text("{}\n", encoding="utf-8")
    assert plan_sdd_sidecar_init_actions("agents", root) == ()


def test_custom_sidecar_generates_deterministic_generic_readme(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    actions = plan_sdd_sidecar_init_actions(
        "artifacts",
        root,
        description="Durable generated build artifacts.",
    )

    assert [action.path.name for action in actions] == ["README.md"]
    written = ensure_sdd_sidecar_initialized(
        "artifacts",
        root,
        description="Durable generated build artifacts.",
    )
    assert written == (root / "README.md",)
    assert (root / "README.md").read_text(encoding="utf-8") == (
        "# SASE Artifacts\n\n"
        "Durable generated build artifacts.\n\n"
        "This repository is managed as a SASE sidecar and is cloned below "
        "`sase/repos/artifacts` in project workspaces.\n"
    )
