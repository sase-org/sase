"""Focused coverage for the generic provider Artifacts relation source."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui.relations import build_provider_relation_index
from sase.ace.tui.widgets.artifacts.plans_data_models import (
    PlansSnapshot,
    ProjectArchive,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.plan_search.model import Plan, PlanSearchMatch


def test_provider_filename_family_and_declared_property() -> None:
    archive = (
        _archive("alpha", "/tmp/bundle.md", "bundle.md"),
        _archive(
            "alpha",
            "/tmp/bundle__a.md",
            "bundle__a.md",
            {"related": "bundle.md"},
        ),
        _archive("alpha", "/tmp/bundle__b.md", "bundle__b.md"),
        _archive("alpha", "/tmp/other.md", "other.md", {"related": "missing.md"}),
    )
    snapshot = PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(),
        active=(),
        archive=archive,
        bead_plan_links={},
        linked_plan_documents={},
        source_key=("src",),
        errors={},
        provider_kind="notes",
        provider_label="Note",
    )
    contract = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#0",
        spec={
            "schema_version": 1,
            "provider": "notes",
            "ref": {
                "kind": "notes",
                "icon": "¶",
                "expansion_format": (
                    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
                ),
                "properties": {
                    "title": {"type": "string", "source": "markdown_frontmatter"},
                    "related": {"type": "string", "source": "markdown_frontmatter"},
                },
                "identity": {},
                "inventory": {"globs": ["**/*.md"]},
                "publication": {
                    "link": "vcs_permalink",
                    "referenced_by": "markdown_table",
                },
                "relations": [
                    {
                        "name": "related",
                        "kind": "link",
                        "label": "Related",
                        "source": "related",
                        "target_pane": None,
                        "inverse": None,
                        "directed": True,
                        "transitive": False,
                    }
                ],
            },
        },
        provider_spec_digest="t",
    ).contract
    index = build_provider_relation_index(snapshot, contract=contract)
    parent = ArtifactEntryTarget("ref:notes", ("alpha", "archive", "/tmp/bundle.md"))
    member_a = ArtifactEntryTarget(
        "ref:notes", ("alpha", "archive", "/tmp/bundle__a.md")
    )
    other = ArtifactEntryTarget("ref:notes", ("alpha", "archive", "/tmp/other.md"))
    bundle_targets = {
        edge.target for edge in index.edges_for_relation(parent, "bundle")
    }
    assert member_a in bundle_targets
    related = index.edges_for_relation(member_a, "related")[0]
    assert related.target == parent
    assert related.dangling is False
    dangling = index.edges_for_relation(other, "related")[0]
    assert dangling.dangling is True
    assert dangling.target == ArtifactEntryTarget("ref:notes", ("missing.md",))


def _archive(
    project: str,
    path: str,
    relpath: str,
    frontmatter: dict[str, str] | None = None,
) -> ProjectArchive:
    return ProjectArchive(
        project,
        PlanSearchMatch(
            plan=Plan(
                source="repo",
                kind="notes",
                path=path,
                relpath=relpath,
                name=relpath,
                title=relpath,
                status="",
                created_at="",
                prompt_link="",
                summary="",
                body="",
                frontmatter=frontmatter or {},
            ),
            matched_fields=[],
            score=1.0,
        ),
    )
