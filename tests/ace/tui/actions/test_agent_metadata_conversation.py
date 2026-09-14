"""Regression coverage for conversation content missing from the V pager."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.testing.wait import wait_for
from sase.ace.tui.actions.agents._metadata_pager_document import (
    build_agent_metadata_document,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.pager._layout import search_corpus
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument
from sase.pager.screen import PagerScreen
from tests.ace.agent_artifact_startup_fixtures import make_agent


@pytest.fixture(autouse=True)
def _metadata_without_external_io():
    with patch(
        "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
        return_value=DetailHeaderSummary(),
    ):
        yield


def _agent(tmp_path: Path, *, status: str = "DONE") -> Agent:
    agent = make_agent(status=status)
    agent.artifacts_dir = str(tmp_path)
    return agent


def _bodies(document: PagerDocument) -> dict[str, str]:
    return {section.title: section.plain_text for section in document.sections}


def test_real_files_populate_all_three_searchable_conversation_sections(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    sources = {
        "raw_xprompt.md": "#review Review src/sase/cli_pager.py",
        "run_prompt.md": "Expanded instructions for bead:sase-uk.7",
        "response.md": "## Result\n\nThe pager now includes **conversation** content.",
    }
    for name, body in sources.items():
        (tmp_path / name).write_text(body)
    agent.response_path = str(tmp_path / "response.md")
    document = build_agent_metadata_document(agent)

    bodies = _bodies(document)
    for title, name in zip(
        ("AGENT XPROMPT", "AGENT PROMPT", "AGENT REPLY"), sources, strict=True
    ):
        assert bodies[title] == sources[name]
        assert sources[name] in search_corpus(document)
    conversation = document.sections[-3:]
    assert all(
        s.raw_source and s.raw_source.language == "markdown" for s in conversation
    )
    targets = [span.text for _, span in document.iter_target_spans()]
    assert "src/sase/cli_pager.py" in targets
    assert "bead:sase-uk.7" in targets


@pytest.mark.parametrize("source", ["live", "response", "chat"])
@pytest.mark.parametrize("status", ["RUNNING", "DONE", "FAILED"])
def test_reply_fallbacks_are_visible_without_a_prompt(
    tmp_path: Path, source: str, status: str
) -> None:
    agent = _agent(tmp_path, status=status)
    reply = tmp_path / ("live_reply.md" if source == "live" else "reply.md")
    reply.write_text(f"Reply from {source}")
    if source == "response":
        agent.response_path = str(reply)
    if source == "chat":
        (tmp_path / "agent_meta.json").write_text(json.dumps({"chat_path": str(reply)}))

    bodies = _bodies(build_agent_metadata_document(agent))
    assert bodies["AGENT REPLY"] == f"Reply from {source}"
    assert "No expanded prompt" in bodies["AGENT PROMPT"]


def test_prompt_selection_uses_the_step_and_excludes_finalizer_prompts(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    agent.parent_workflow = "review"
    agent.step_name = "verify"
    for index, name in enumerate(
        (
            "run-verify_prompt.md",
            "run-other_prompt.md",
            "commit_finalizer_pass_1_prompt.md",
        )
    ):
        path = tmp_path / name
        path.write_text(name)
        os.utime(path, ns=(1_000_000_000 + index, 1_000_000_000 + index))

    assert (
        _bodies(build_agent_metadata_document(agent))["AGENT PROMPT"]
        == "run-verify_prompt.md"
    )


def test_malformed_prompt_does_not_hide_metadata_or_reply(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    (tmp_path / "run_prompt.md").write_bytes(b"\xff")
    (tmp_path / "live_reply.md").write_text("Still readable")
    bodies = _bodies(build_agent_metadata_document(agent))

    assert "TIMELINE" in bodies
    assert "Could not load prompts" in bodies["AGENT PROMPT"]
    assert bodies["AGENT REPLY"] == "Still readable"


def test_refresh_replaces_placeholders_and_keeps_section_identity(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, status="RUNNING")
    before = build_agent_metadata_document(agent)
    (tmp_path / "run_prompt.md").write_text("New prompt")
    reply = tmp_path / "live_reply.md"
    reply.write_text("First reply")
    first = build_agent_metadata_document(agent)
    with reply.open("a") as stream:
        stream.write("\nAppended reply")
    after = build_agent_metadata_document(agent)

    assert [s.identity for s in before.sections] == [s.identity for s in after.sections]
    assert _bodies(first)["AGENT REPLY"] == "First reply"
    assert _bodies(after)["AGENT REPLY"] == "First reply\nAppended reply"
    assert _bodies(after)["AGENT PROMPT"] == "New prompt"


def test_family_replies_are_attributed_and_keep_identity_when_members_are_added(
    tmp_path: Path,
) -> None:
    root = _agent(tmp_path)
    root.agent_name = "review--plan"
    root.agent_family = "review"
    root.agent_family_role = "root"
    root.refresh_raw_presented_agent_name()
    child = make_agent(cl_name="child", raw_suffix="20250101120500")
    child.agent_name = "review--impl"
    child.response_path = str(tmp_path / "child-response.md")
    Path(child.response_path).write_text("Implementation reply")
    (tmp_path / "live_reply.md").write_text("Planning reply")
    root.followup_agents = [child]
    before = build_agent_metadata_document(root)

    bodies = _bodies(before)
    assert bodies["AGENT REPLY · review--plan"] == "Planning reply"
    assert bodies["AGENT REPLY · review--impl"] == "Implementation reply"
    root.followup_agents.append(make_agent(cl_name="next", raw_suffix="20250101121000"))
    after = build_agent_metadata_document(root)
    assert [s.identity for s in before.sections] == [
        s.identity for s in after.sections[:-3]
    ]


def test_clan_conversations_keep_each_members_workspace(tmp_path: Path) -> None:
    clan = _agent(tmp_path)
    clan.is_clan_container = True
    clan.agent_clan = "review"
    members = []
    for index in range(2):
        workspace = tmp_path / f"workspace-{index}"
        workspace.mkdir()
        (workspace / "live_reply.md").write_text(f"Reply {index}: src/example.py")
        member = make_agent(cl_name=f"member-{index}")
        member.agent_name = f"review.member-{index}"
        member.agent_clan = "review"
        member.artifacts_dir = str(workspace)
        member.workspace_dir = str(workspace)
        member.refresh_raw_presented_agent_name()
        members.append(member)
    clan.runtime_children = members

    document = build_agent_metadata_document(clan)
    replies = [
        section
        for section in document.sections
        if section.title.startswith("AGENT REPLY")
    ]
    assert len(replies) == 2
    for index, section in enumerate(replies):
        assert section.plain_text == f"Reply {index}: src/example.py"
        assert section.link_anchors[0].directory == Path(members[index].workspace_dir)
        assert section.owner is not None
        assert section.owner.source_directory == members[index].workspace_dir


async def test_pager_refresh_and_search_use_fresh_conversation_off_thread(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path, status="RUNNING")
    reply = tmp_path / "live_reply.md"
    reply.write_text("\n".join(f"Reply line {index}" for index in range(50)))
    document = build_agent_metadata_document(agent)
    threads: list[int] = []

    def refresh() -> PagerDocument:
        threads.append(threading.get_ident())
        return build_agent_metadata_document(agent)

    app = SasePager(document, refresh_document_fn=refresh)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = app.screen
        assert isinstance(screen, PagerScreen)
        await pilot.press(*(["ctrl+n"] * (len(document.sections) - 1)))
        assert screen._current_section().title == "AGENT REPLY"
        identity = screen._current_section().identity
        with reply.open("a") as stream:
            stream.write("\nAppended content")
        await pilot.press("r")
        await wait_for(pilot, lambda: "Appended content" in screen.vim_search_corpus())
        assert threads and all(ident != threading.get_ident() for ident in threads)
        assert screen._current_section().identity == identity

        await pilot.press("slash", *"Appended", "enter")
        assert screen._search.query == "Appended"
        assert "Appended content" in screen._search.corpus
        assert screen._search.current_selection is not None
