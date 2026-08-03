"""Detail-panel and transcript-preview coverage for Artifacts Chats."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.widgets.artifacts import chats_detail
from sase.ace.tui.widgets.artifacts.chats_detail import (
    ChatDetailData,
    build_chat_detail,
    load_chat_detail,
)
from tests.ace.tui._artifacts_chats_helpers import chat_entry


def _detail(entry_path: str, *, truncated: bool = False) -> ChatDetailData:
    return ChatDetailData(
        absolute_path=entry_path,
        transcript_preview="# Chat\n\nPreview",
        transcript_truncated=truncated,
        model="gpt-5",
        provider="codex",
        agent_status="DONE",
        dismissed=False,
    )


def test_each_provenance_renders_distinct_explanation() -> None:
    expected = {
        "local": "Only on this machine",
        "shared": "also published to the agents sidecar",
        "remote": "Pulled in from bryan@zeus",
        "unknown": "Sync state unknown",
    }
    for provenance, sentence in expected.items():
        machine = "zeus" if provenance == "remote" else None
        entry = chat_entry(
            provenance,
            provenance=provenance,  # type: ignore[arg-type]
            machine=machine,
        )
        rendered = build_chat_detail(
            entry,
            _detail(entry.absolute_path),
            diagnostics=("sidecar checkout is unreadable",),
        ).plain
        assert sentence in rendered
        assert "PROVENANCE" in rendered
        assert "CHAT" in rendered
        assert "AGENT" in rendered
        assert "TRANSCRIPT" in rendered
        if provenance == "unknown":
            assert "local" not in rendered.casefold()


def test_local_publication_backlog_and_truncation_are_explained() -> None:
    entry = replace(
        chat_entry("pending"),
        publication_pending=True,
        publication_disposition="queued",
        publication_attempts=28,
        publication_last_error="network down",
    )
    rendered = build_chat_detail(
        entry,
        _detail(entry.absolute_path, truncated=True),
    ).plain

    assert "Queued to publish" in rendered
    assert "28 attempts" in rendered
    assert "last error: network down" in rendered
    assert "press enter for the full chat" in rendered


def test_quarantined_publication_is_never_described_as_queued() -> None:
    entry = replace(
        chat_entry("quarantined"),
        publication_pending=False,
        publication_quarantined=True,
        publication_disposition="quarantined",
        publication_attempts=3,
        publication_last_error="remote rejected update",
    )

    rendered = build_chat_detail(
        entry,
        _detail(entry.absolute_path),
    ).plain

    assert "Publication quarantined" in rendered
    assert "3 attempts" in rendered
    assert "last error: remote rejected update" in rendered
    assert "sase agent sync --retry-quarantined" in rendered
    assert "Queued to publish" not in rendered


def test_retired_publication_names_the_drop_command_instead_of_retry() -> None:
    entry = replace(
        chat_entry("retired"),
        publication_pending=False,
        publication_quarantined=False,
        publication_disposition="retired",
        publication_attempts=2,
        publication_last_error="hood 'lt' has no publishable runs",
    )

    rendered = build_chat_detail(entry, _detail(entry.absolute_path)).plain

    assert "Publication retired as unpublishable" in rendered
    assert "2 attempts" in rendered
    assert "last error: hood 'lt' has no publishable runs" in rendered
    assert "sase agent sync --drop-retired" in rendered
    assert "sase agent sync --retry-quarantined" not in rendered
    assert "Queued to publish" not in rendered


def test_shared_publication_states_keep_committed_provenance_visible() -> None:
    cases = (
        (
            replace(
                chat_entry("shared-queued", provenance="shared"),
                publication_pending=True,
                publication_disposition="queued",
                publication_attempts=2,
            ),
            "publication completion remains queued",
        ),
        (
            replace(
                chat_entry("shared-quarantined", provenance="shared"),
                publication_quarantined=True,
                publication_disposition="quarantined",
                publication_attempts=3,
            ),
            "publication retry is quarantined",
        ),
        (
            replace(
                chat_entry("shared-mixed", provenance="shared"),
                publication_pending=True,
                publication_disposition="mixed",
                publication_attempts=5,
            ),
            "retryable, quarantined, and retired requests coexist",
        ),
    )

    for entry, state_copy in cases:
        rendered = build_chat_detail(entry, _detail(entry.absolute_path)).plain
        assert "also published to the agents sidecar" in rendered
        assert "Published chat:" in rendered
        assert state_copy in rendered
        assert "attempts" in rendered

    assert (
        "Queued to publish"
        not in build_chat_detail(
            cases[1][0],
            _detail(cases[1][0].absolute_path),
        ).plain
    )


def test_local_mixed_publication_explains_both_retry_modes() -> None:
    entry = replace(
        chat_entry("local-mixed"),
        publication_pending=True,
        publication_quarantined=False,
        publication_disposition="mixed",
        publication_attempts=8,
        publication_last_error="latest failure",
    )

    rendered = build_chat_detail(entry, _detail(entry.absolute_path)).plain

    assert "Only on this machine" in rendered
    assert "retryable, quarantined, and retired requests coexist" in rendered
    assert "Active requests will retry automatically" in rendered
    assert "sase agent sync --retry-quarantined" in rendered
    assert "8 attempts" in rendered
    assert "last error: latest failure" in rendered
    assert "Queued to publish" not in rendered


def test_detail_loader_bounds_transcript_to_200_lines(tmp_path) -> None:
    transcript = tmp_path / "chat.md"
    transcript.write_text(
        "".join(f"line {index}\n" for index in range(205)),
        encoding="utf-8",
    )
    entry = replace(
        chat_entry("bounded"),
        absolute_path=str(transcript),
        agent_artifact_dir=None,
    )

    detail = load_chat_detail(entry)

    assert detail.transcript_truncated is True
    assert len(detail.transcript_preview.splitlines()) == 200
    assert "line 199" in detail.transcript_preview
    assert "line 200" not in detail.transcript_preview


def test_detail_shows_logical_reference_before_resolved_path() -> None:
    entry = chat_entry("reference")
    detail = replace(
        _detail(entry.absolute_path),
        reference="chat:202607/reference.md",
    )

    rendered = build_chat_detail(entry, detail).plain

    assert "Reference: chat:202607/reference.md" in rendered
    assert f"Path: {entry.absolute_path}" in rendered
    assert rendered.index("Reference:") < rendered.index("Path:")


def test_chat_reference_rejects_imports_outside_the_chats_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chats_root = tmp_path / "chats"
    transcript = chats_root / "202607" / "agent.md"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("# Chat")
    monkeypatch.setattr(chats_detail, "sase_subdir", lambda _name: chats_root)

    assert chats_detail.chat_reference(str(transcript)) == "chat:202607/agent.md"
    assert chats_detail.chat_reference(str(tmp_path / "imported.md")) is None
