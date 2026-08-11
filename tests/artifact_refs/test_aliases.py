"""Legacy parse-alias behavior: commit:/plans:/chat:/bug: (S3.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_ref_kinds import (
    completion_artifact_ref_kinds,
    parsable_artifact_ref_kinds,
)
from sase.artifact_ref_models import ArtifactRefContext
from sase.artifact_refs import process_artifact_references

from .helpers import context as make_context
from .preprocessing_helpers import (
    context as make_preprocessing_context,
    disable_consumption_ledger_writes,  # noqa: F401 (registers autouse fixture)
)


def test_plans_resolves_and_warns_once_while_plan_is_silent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = make_preprocessing_context(tmp_path)
    plan = tmp_path / "plans" / "x.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# X\n")

    deprecated = process_artifact_references(
        "@plans:x.md and @plans:x.md again", context=context
    )
    assert deprecated == f"@{plan} and @{plan} again"
    warnings = [
        line for line in capsys.readouterr().err.splitlines() if "@plans:" in line
    ]
    assert len(warnings) == 1
    assert "deprecated" in warnings[0]
    assert "@plan:<path>" in warnings[0]

    canonical = process_artifact_references("@plan:x.md", context=context)
    assert canonical == f"@{plan}"
    assert capsys.readouterr().err == ""


def test_chat_and_bug_resolve_and_warn_with_replacement_named(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase import artifact_ref_prompt

    monkeypatch.setattr(
        artifact_ref_prompt,
        "_resolved_bug_url",
        lambda project, number: f"https://bugs.test/{project}/{number}",
    )
    context = make_preprocessing_context(tmp_path)
    chat = tmp_path / "chats" / "agent.md"
    chat.parent.mkdir(parents=True)
    chat.write_text("# Chat\n")

    chat_result = process_artifact_references("@chat:agent.md", context=context)
    assert chat_result == f"@{chat}"
    chat_warnings = capsys.readouterr().err
    assert "@chat:" in chat_warnings
    assert "@agent:<name>" in chat_warnings

    bug_result = process_artifact_references(
        "@bug:gh_sase-org__sase#42", context=context
    )
    assert bug_result == "#42 https://bugs.test/sase/42"
    bug_warnings = capsys.readouterr().err
    assert "@bug:" in bug_warnings
    assert "@bead:<id>" in bug_warnings


def test_commit_never_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tests.artifact_providers.helpers import init_git_repo

    full_sha = init_git_repo(tmp_path / "workspace")
    context = make_context(tmp_path)

    process_artifact_references(f"@commit:sase@{full_sha[:12]}", context=context)

    assert capsys.readouterr().err == ""


def test_completion_kinds_exclude_aliases_and_historical_kinds() -> None:
    completion = set(completion_artifact_ref_kinds())
    parsable = set(parsable_artifact_ref_kinds())

    assert {"stitch", "patch", "bead", "agent", "file"} <= completion
    assert not {"commit", "plans", "chat", "bug"} & completion
    assert {
        "stitch",
        "patch",
        "bead",
        "agent",
        "file",
        "commit",
        "plans",
        "chat",
        "bug",
    } <= parsable


def test_known_kinds_no_longer_silently_drops_builtin_or_alias_kinds() -> None:
    """Regression: phase 3's plans->plan rename used to drop @stitch/@patch/@plans."""

    context = ArtifactRefContext(
        document_roots=(),
        chats_root=Path("/tmp/chats"),
        artifact_index_path=Path("/tmp/idx.jsonl"),
        repositories=(),
        projects=(),
    )
    known = set(context.known_kinds)
    for kind in ("stitch", "patch", "commit", "plans", "chat", "bug", "bead", "agent"):
        assert kind in known, f"{kind} silently dropped from known_kinds"
