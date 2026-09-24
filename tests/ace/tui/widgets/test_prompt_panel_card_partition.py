"""Card-partitioned Main documents (phase main-card-partition)."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path

from rich.console import Console, Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.lazy_syntax import CachedRenderable
from sase.ace.tui.util.renderable_digest import renderable_content_digest
from sase.ace.tui.widgets.decks.card_part import (
    CardPart,
    card_document,
    context_card,
    flatten_card_document,
    output_card,
    reply_card,
    summary_card,
)
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import find_identity_header
from sase.ace.tui.widgets.renderable_text import renderable_to_text


def _segments_text(renderable: object, width: int = 120) -> str:
    console = Console(record=True, width=width, color_system=None, file=StringIO())
    console.print(renderable, end="")
    return console.export_text(clear=True)


def _styled_segments(renderable: object, width: int = 120):
    console = Console(record=True, width=width, color_system=None, file=StringIO())
    console.print(renderable, end="")
    return list(console.render(renderable, console.options))


def test_card_segment_equivalence() -> None:
    a, b, c = Text("a\n"), Text("b\n"), Text("c\n")
    assert _segments_text(Group(a, b, c)) == _segments_text(
        Group(CardPart("context", "Context", a, b), CardPart("reply", "Reply", c))
    )


def test_card_document_drops_empty() -> None:
    doc = card_document(context_card(Text("x\n")), reply_card(), None)
    assert isinstance(doc, Group)
    assert len(doc.renderables) == 1
    assert isinstance(doc.renderables[0], CardPart)


def test_flatten_card_document() -> None:
    single = Text("only\n")
    assert flatten_card_document(card_document(context_card(single))) is single
    part = CardPart("reply", "Reply", Text("inner\n"))
    assert flatten_card_document(part).plain == "inner\n"
    loose = Text("loose\n")
    flat = flatten_card_document(Group(context_card(single), loose))
    assert isinstance(flat, Group)
    assert list(flat.renderables) == [single, loose]
    other = Text("plain\n")
    assert flatten_card_document(other) is other
    assert flatten_card_document(Group(single, loose)) is not single


def test_digest_includes_card_identity() -> None:
    body = Text("same\n")
    first = card_document(context_card(body))
    second = card_document(reply_card(body))
    assert renderable_content_digest(first) != renderable_content_digest(second)
    rebuilt = card_document(context_card(Text("same\n")))
    assert renderable_content_digest(first) == renderable_content_digest(rebuilt)


def test_find_carrier_descends_into_card() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_renderable import (
        AgentHeaderRenderable,
    )

    carrier = AgentHeaderRenderable(Text("body\n"), ())
    doc = card_document(context_card(carrier))
    assert find_identity_header(doc) is None
    assert find_identity_header(Group(Text("a\n"), Text("b\n"))) is None


def test_renderable_to_text_renders_cards() -> None:
    doc = card_document(context_card(Text("hello\n")), reply_card(Text("world\n")))
    text = renderable_to_text(doc)
    assert text is not None
    assert "hello" in text
    assert "world" in text


class _FakePanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo_cl",
        "project_file": "/tmp/test.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _cards_of(renderable: object) -> list[CardPart]:
    assert isinstance(renderable, Group)
    return [c for c in renderable.renderables if isinstance(c, CardPart)]


def _flat_plain(renderable: object) -> str:
    flat = flatten_card_document(renderable)
    text = renderable_to_text(flat)
    return text or ""


def test_regular_agent_partition_and_traceback_move(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "01_prompt.md").write_text("prompt body\n", encoding="utf-8")
    response = artifacts / "response.md"
    response.write_text("reply body\n", encoding="utf-8")
    tb = "Traceback (most recent call last):\nValueError: boom\n"
    agent = _make_agent(
        status="FAILED",
        artifacts_dir=str(artifacts),
        response_path=str(response),
        error_message="boom",
        error_traceback=tb,
    )
    panel = _FakePanel()
    panel.update_display(agent)
    cards = _cards_of(panel.captured[-1])
    assert [(c.card_id, c.title) for c in cards] == [
        ("context", "Context"),
        ("reply", "Reply"),
    ]
    reply_plain = renderable_to_text(Group(*cards[1].renderables)) or ""
    assert "TRACEBACK" in reply_plain
    assert reply_plain.index("TRACEBACK") < reply_plain.index("ValueError")
    flat = _flat_plain(panel.captured[-1])
    assert flat.index("prompt body") < flat.index("TRACEBACK")
    assert flat.index("TRACEBACK") < flat.index("AGENT CHAT")


def test_regular_no_prompt_traceback_only_reply() -> None:
    tb = "Traceback:\nboom\n"
    agent = _make_agent(status="FAILED", error_traceback=tb)
    panel = _FakePanel()
    panel.update_display(agent)
    cards = _cards_of(panel.captured[-1])
    assert [c.card_id for c in cards] == ["context", "reply"]
    agent_ok = _make_agent(status="RUNNING")
    panel_ok = _FakePanel()
    panel_ok.update_display(agent_ok)
    flat = flatten_card_document(panel_ok.captured[-1])
    assert isinstance(flat, Text)


def test_output_cards_use_reply_id() -> None:
    agent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        status="FAILED",
        step_type="bash",
        step_source="echo hi",
        step_output={"_raw": "hi"},
        error_traceback="boom\n",
    )
    agent._is_workflow_child = True  # type: ignore[attr-defined]
    panel = _FakePanel()
    panel._update_bash_python_display(  # type: ignore[attr-defined]
        agent, Text("header\n"), Syntax("boom\n", "pytb")
    )
    cards = _cards_of(panel.captured[-1])
    assert cards[1].card_id == "reply"
    assert cards[1].title == "Output"


def test_parallel_output_heading_moved() -> None:
    agent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        step_type="parallel",
        step_output={"_raw": "out"},
    )
    panel = _FakePanel()
    header = Text("header\n")
    panel._update_parallel_display(agent, header, None)  # type: ignore[attr-defined]
    cards = _cards_of(panel.captured[-1])
    assert cards[0].card_id == "context"
    assert "STEP OUTPUT" not in (getattr(header, "plain", "") or "")
    out_plain = renderable_to_text(Group(*cards[1].renderables)) or ""
    assert "STEP OUTPUT" in out_plain


def test_show_empty_stays_cardless() -> None:
    panel = _FakePanel()
    panel.show_empty()  # type: ignore[attr-defined]
    assert isinstance(panel.captured[-1], Text)
    assert flatten_card_document(panel.captured[-1]) is panel.captured[-1]


def test_attempt_not_found_is_context_card() -> None:
    agent = _make_agent(status="FAILED", attempt_history=[])
    panel = _FakePanel()
    panel.attempt_pinned_number = 9
    panel.update_display(agent)
    cards = _cards_of(panel.captured[-1])
    assert len(cards) == 1
    assert cards[0].card_id == "context"


def test_header_only_traceback_reply_card() -> None:
    agent = _make_agent(status="FAILED", error_traceback="tb\n")
    panel = _FakePanel()
    panel.update_header_only(agent)
    cards = _cards_of(panel.captured[-1])
    assert [c.card_id for c in cards] == ["context", "reply"]


def test_hint_numbering_continuous_across_cards(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x\n", encoding="utf-8")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text("see src/a.py\n", encoding="utf-8")
    (artifacts / "01_prompt.md").write_text("open src/a.py\n", encoding="utf-8")
    response = artifacts / "response.md"
    response.write_text("open src/a.py and src/b.py\n", encoding="utf-8")
    agent = _make_agent(
        status="DONE",
        artifacts_dir=str(artifacts),
        response_path=str(response),
        workspace_dir=str(workspace),
        error_traceback="open src/c.py\n",
    )
    panel = _FakePanel()
    render = panel.update_display_with_hints(agent)
    numbers = sorted(render.file_hints)
    assert numbers == list(range(1, len(numbers) + 1))
    flat = _flat_plain(panel.captured[-1])
    for n in numbers:
        assert f"[{n}]" in flat


def test_digest_stability_and_skip() -> None:
    agent = _make_agent(status="RUNNING")
    panel = _FakePanel()
    real_update = panel.update
    panel.update_display(agent)
    first = panel.captured[-1]
    d1 = renderable_content_digest(first)
    panel2 = _FakePanel()
    panel2.update_display(agent)
    assert renderable_content_digest(panel2.captured[-1]) == d1
    assert real_update is not None


def test_hint_cache_hit_republishes_card_document(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
        DetailHeaderSummary,
        cache_detail_header_summary,
    )

    artifacts = tmp_path / "art"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text("hi\n", encoding="utf-8")
    (artifacts / "01_prompt.md").write_text("body\n", encoding="utf-8")
    response = artifacts / "response.md"
    response.write_text("reply\n", encoding="utf-8")
    agent = _make_agent(
        status="DONE", artifacts_dir=str(artifacts), response_path=str(response)
    )
    panel = _FakePanel()
    cache_detail_header_summary(panel, agent, DetailHeaderSummary())
    panel.update_display_with_hints(agent)
    first = panel.captured[-1]
    panel.update_display_with_hints(agent)
    assert panel.captured[-1] is first
    assert isinstance(first, Group)
    assert any(isinstance(c, CardPart) for c in first.renderables)


def test_cached_per_card_wrapping() -> None:
    doc = card_document(context_card(Text("ctx\n")), reply_card(Text("rep\n")))
    panel = _FakePanel()
    out = panel._prepare_cached_hint_renderable(doc)  # type: ignore[attr-defined]
    assert isinstance(out, Group)
    parts = [c for c in out.renderables if isinstance(c, CardPart)]
    assert len(parts) == 2
    for part in parts:
        assert len(part.renderables) == 1
        assert isinstance(part.renderables[0], CachedRenderable)
