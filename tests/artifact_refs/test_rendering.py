from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase import artifact_refs
from sase.artifact_refs import (
    ArtifactRefContext,
    ArtifactRefDocumentExpansion,
    ArtifactRefDocumentRoot,
    process_artifact_references,
)

from .helpers import context as make_context


def test_reference_for_each_entry_target_shape(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    chat = context.chats_root / "202607" / "agent.md"
    proposal = context.document_roots[1].root / "202607" / "proposal.md"
    archive = SimpleNamespace(
        plan=SimpleNamespace(relpath="202607/design.md", kind="designs")
    )
    issue = SimpleNamespace(id="sase-av", design="plan:202607/epic.md")
    phase = SimpleNamespace(id="sase-av.2", design="plan:202607/epic.md")

    assert (
        artifact_refs.reference_for_entry_target(
            "commits",
            ("commit", "sase", "a" * 40),
            context=context,
        )
        == f"commit:sase@{'a' * 40}"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(chat)),
            context=context,
        )
        == "chat:202607/agent.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "bugs",
            ("bug", "gh_sase-org__sase", "42"),
            context=context,
        )
        == "bug:sase#42"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "archive", str(archive.plan.relpath)),
            context=context,
            row=SimpleNamespace(archive=archive, archive_role="designs"),
        )
        == "designs:202607/design.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "epic", "sase-av"),
            context=context,
            row=SimpleNamespace(issue=issue),
        )
        == "bead:sase-av"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "phase", "sase-av.2"),
            context=context,
            row=SimpleNamespace(issue=phase),
        )
        == "bead:sase-av.2"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "proposal", "notification"),
            context=context,
            row=SimpleNamespace(proposal=SimpleNamespace(plan_path=str(proposal))),
        )
        == "plan:202607/proposal.md"
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "files",
            ("file", "default:0123456789abcdef01234567"),
            context=None,
        )
        == "file:default:0123456789abcdef01234567"
    )


def test_reference_rendering_declines_unrepresentable_rows(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    assert (
        artifact_refs.reference_for_entry_target(
            "chats",
            ("chat", str(tmp_path / "imported.md")),
            context=context,
        )
        is None
    )
    assert (
        artifact_refs.reference_for_entry_target(
            "plans",
            ("plan", "sase", "phase", "sase-av.2"),
            context=context,
            row=SimpleNamespace(issue=SimpleNamespace(id="")),
        )
        is None
    )


def test_plan_design_and_agent_reference_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity(username="alice", machine_name="athena"),
        sibling_machines=("athena", "zeus"),
        known_owner_roots=("bob.zeus", "athena", "zeus", "alice.athena"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )

    row = SimpleNamespace(issue=SimpleNamespace(design="plan:202607/epic.md"))
    assert artifact_refs.design_reference_for_plan_row(row) == "plan:202607/epic.md"
    assert artifact_refs.reference_for_agent_name("9w") == "agent:alice.athena.9w"
    assert (
        artifact_refs.reference_for_agent_name("alice.athena.9w--code")
        == "agent:alice.athena.9w--code"
    )
    assert (
        artifact_refs.reference_for_agent_name("bob.zeus.reader")
        == "agent:bob.zeus.reader"
    )


def _pointer_context(tmp_path: Path) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("research", tmp_path / "research"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
        document_expansions=(
            ArtifactRefDocumentExpansion(
                kind="research",
                role="research",
                expansion_format=(
                    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
                ),
                is_pointer=True,
            ),
        ),
    )


def test_pointer_document_ref_expands_through_declared_format_with_no_clone(
    tmp_path: Path,
) -> None:
    context = _pointer_context(tmp_path)

    expanded = process_artifact_references("@research:202608/x/x.md", context=context)

    assert expanded == "the 202608/x/x.md file in the research sidecar repo"
    assert not (tmp_path / "research").exists()


@pytest.mark.parametrize(
    ("reference", "expected"),
    (
        (
            "@research:202608/x/x.md#L10-L20",
            "the 202608/x/x.md file in the research sidecar repo (lines 10-20)",
        ),
        (
            "@research:202608/x/x.md#L10-L10",
            "the 202608/x/x.md file in the research sidecar repo (line 10)",
        ),
        (
            "@research:202608/x/x.md#page=2",
            "the 202608/x/x.md file in the research sidecar repo (page 2)",
        ),
        (
            "@research:202608/x/x.md#t=30",
            "the 202608/x/x.md file in the research sidecar repo (time 30s)",
        ),
        (
            "@plan:202608/foobar.md#L10-L20",
            "the 202608/foobar.md file in the plans sidecar repo (lines 10-20)",
        ),
    ),
)
def test_pointer_document_ref_fragment_is_appended_after_pointer_text(
    tmp_path: Path,
    reference: str,
    expected: str,
) -> None:
    if reference.startswith("@research:"):
        context = _pointer_context(tmp_path)
    else:
        context = ArtifactRefContext(
            document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
            chats_root=tmp_path / "chats",
            artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
            repositories=(),
            projects=(),
        )

    assert process_artifact_references(reference, context=context) == expected


def test_plan_ref_expands_to_plans_sidecar_pointer_without_cloning(
    tmp_path: Path,
) -> None:
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
    )
    assert not (tmp_path / "plans").exists()

    expanded = process_artifact_references("@plan:202608/foobar.md", context=context)

    assert expanded == "the 202608/foobar.md file in the plans sidecar repo"
    assert not (tmp_path / "plans").exists()


def test_missing_plan_path_is_non_fatal_when_sidecar_root_is_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
    )

    expanded = process_artifact_references("@plan:202608/missing.md", context=context)

    assert expanded == "the 202608/missing.md file in the plans sidecar repo"
    assert capsys.readouterr().err == ""


def test_unconfigured_document_kind_uses_sidecar_pointer_format(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)

    expanded = process_artifact_references("@designs:202607/design.md", context=context)

    assert expanded == "the 202607/design.md file in the designs sidecar repo"


def test_quoted_and_unicode_document_refs_expand_through_the_contract(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path)

    quoted = process_artifact_references('@plan:"foo bar.md"', context=context)
    unicode_prompt = process_artifact_references(
        "é @plan:plan.md done", context=context
    )

    assert quoted == "the foo bar.md file in the plans sidecar repo"
    assert unicode_prompt == "é the plan.md file in the plans sidecar repo done"


def test_explicit_at_prefixed_checkout_path_format_remains_compatible(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "202607" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
        document_expansions=(
            ArtifactRefDocumentExpansion(
                kind="plan",
                role="plans",
                expansion_format="@{checkout_path}",
                is_pointer=False,
            ),
        ),
    )

    assert (
        process_artifact_references("@plan:202607/plan.md", context=context)
        == f"@{plan}"
    )


def test_explicit_path_bound_provider_expands_to_prose_path(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans" / "202607" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plan", tmp_path / "plans"),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
        document_expansions=(
            ArtifactRefDocumentExpansion(
                kind="plan",
                role="plans",
                expansion_format="the {checkout_path} file",
                is_pointer=False,
            ),
        ),
    )

    expanded = process_artifact_references("@plan:202607/plan.md", context=context)

    assert expanded == f"the {plan} file"
    assert f"@{plan}" not in expanded
