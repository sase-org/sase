from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase import artifact_refs

from .helpers import context as make_context


def test_reference_for_each_entry_target_shape(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    chat = context.chats_root / "202607" / "agent.md"
    proposal = context.document_roots[1].root / "202607" / "proposal.md"
    archive = SimpleNamespace(
        plan=SimpleNamespace(relpath="202607/design.md", kind="designs")
    )
    issue = SimpleNamespace(id="sase-av", design="plans:202607/epic.md")
    phase = SimpleNamespace(id="sase-av.2", design="plans:202607/epic.md")

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
        == "plans:202607/proposal.md"
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
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )

    row = SimpleNamespace(issue=SimpleNamespace(design="plans:202607/epic.md"))
    assert artifact_refs.design_reference_for_plan_row(row) == "plans:202607/epic.md"
    assert artifact_refs.reference_for_agent_name("9w") == "agent:alice.athena.9w"
    assert (
        artifact_refs.reference_for_agent_name("alice.athena.9w--code")
        == "agent:alice.athena.9w--code"
    )
    assert (
        artifact_refs.reference_for_agent_name("bob.zeus.reader")
        == "agent:bob.zeus.reader"
    )
