"""Detail-panel and transcript-preview coverage for Artifacts Chats."""

from __future__ import annotations

from dataclasses import replace

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
