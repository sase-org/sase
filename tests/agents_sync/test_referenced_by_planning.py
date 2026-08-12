from __future__ import annotations

from pathlib import Path
from typing import cast

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.render import RenderedPromptArchive
from sase.agents_sync.referenced_by_planning import plan_referenced_by_requests
from sase.core.artifact_ref_uses import record_artifact_ref_use
from sase.core.prompt_artifact_staging import PromptArtifactRecord
from sase.sdd.store import SddStore


def _target(workspace: Path, agents: Path) -> ProjectTarget:
    return ProjectTarget(
        "proj",
        "Project",
        workspace,
        (workspace,),
        agents,
        "git@example.test:project/agents.git",
    )


def test_plan_referenced_by_requests_for_document_sidecar_refs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    artifacts_dir = tmp_path / "run"
    workspace.mkdir()
    plans.mkdir()
    agents.mkdir()
    document = plans / "202608" / "example.md"
    document.parent.mkdir()
    document.write_text("# Example\n", encoding="utf-8")
    raw_ref = "@plan:202608/example.md"
    for _ in range(2):
        record_artifact_ref_use(
            agent_name="alice.athena.worker",
            raw_ref=raw_ref,
            canonical_ref="plan:202608/example.md",
            ref_kind="plan",
            prompt_text=raw_ref,
            agent_artifacts_dir=artifacts_dir,
        )
    monkeypatch.setattr(
        "sase.agents_sync.referenced_by_planning.resolution_config",
        lambda *_args, **_kwargs: {},
    )
    store = SddStore("sidecar_repos", plans, plans)
    artifact_record = cast(
        PromptArtifactRecord,
        {
            "raw_ref": raw_ref,
            "source_path": str(document),
            "vcs_repo": None,
            "vcs_relpath": None,
        },
    )
    rendered = RenderedPromptArchive(
        document="Use [@plan:202608/example.md][1]\n\n[1]: https://target",
        linked_records=(artifact_record,),
        reference_labels=(
            {
                "raw_ref": raw_ref,
                "label": "1",
                "destination": "https://target",
            },
        ),
    )

    [request] = plan_referenced_by_requests(
        target=_target(workspace, agents),
        rendered=rendered,
        agent_artifacts_dir=artifacts_dir,
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        store=store,
        workspace_root=workspace,
        repository_roots={},
        agent_url="https://example.test/agents/worker",
    )

    assert request.project_key == "proj"
    assert request.sidecar_role == "plans"
    assert request.provider == "plan"
    assert request.artifact_id == "plan:202608/example.md"
    assert request.repo_relpath == "202608/example.md"
    assert request.canonical_ref == "plan:202608/example.md"
    assert request.destination == "https://target"
    assert request.uses == 2
