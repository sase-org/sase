"""CardBlock data model, walkers and block anchors (phase card-block-model)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console, Group
from rich.style import Style
from rich.text import Text

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.util.lazy_syntax import CachedRenderable
from sase.ace.tui.util.renderable_digest import renderable_content_digest
from sase.ace.tui.widgets.decks.card_block import (
    BlockMeta,
    BlockSpreadOnly,
    CardBlock,
    card_block_id,
    is_card_container,
    partition_card_children,
)
from sase.ace.tui.widgets.decks.card_part import (
    CardPart,
    card_document,
    flatten_card_document,
    reply_card,
    split_card_parts,
)
from sase.ace.tui.widgets.decks.render_mode import (
    _lower_bound_node,
    _lower_bound_rows,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
    render_phase_divider,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
    _plain_renderable_content,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import _find_carrier
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    DECK_BLOCK_META_KEY,
    PromptPanelSectionRole,
    _segment_section_identity,
)


def _meta(**overrides: object) -> BlockMeta:
    fields: dict[str, object] = {
        "number": "0",
        "label": "--plan",
        "glyph": "",
        "accent": "#AF87FF",
        "status_bucket": "Done",
        "kind": "agent",
    }
    fields.update(overrides)
    return BlockMeta(**fields)  # type: ignore[arg-type]


def _block(
    block_id: str = "RUNNING|demo|--plan",
    *texts: str,
    meta: BlockMeta | None = None,
) -> CardBlock:
    return CardBlock(
        block_id,
        "AGENT (plan)",
        *[Text(t) for t in texts],
        meta=meta or _meta(),
    )


def test_card_block_id_from_identity() -> None:
    value = AgentType.RUNNING.value
    assert (
        card_block_id((AgentType.RUNNING, "demo", "--plan")) == f"{value}|demo|--plan"
    )
    assert card_block_id((AgentType.RUNNING, "demo", None)) == f"{value}|demo|"


def test_is_card_container() -> None:
    assert is_card_container(CardPart("reply", "Reply", Text("x\n")))
    assert is_card_container(_block("id"))
    assert is_card_container(BlockSpreadOnly(Text("x\n")))
    assert not is_card_container(Text("x\n"))
    assert not is_card_container(Group(Text("x\n")))


def test_card_block_repr_hides_child_ids() -> None:
    assert "0x" not in repr(_block("bid", "hello\n"))


def test_partition_valid() -> None:
    pre = Text("pre\n")
    first, second = _block("a", "x\n"), _block("b", "y\n")
    preamble, blocks, error = partition_card_children((pre, first, second))
    assert error is None
    assert preamble == (pre,)
    assert tuple(b.block_id for b in blocks) == ("a", "b")
    assert partition_card_children(())[1] == ()


def test_partition_non_block_after_block_falls_back(caplog) -> None:
    card = CardPart("reply", "Reply", _block("a", "x\n"), Text("trailing\n"))
    assert card.blocks == ()
    assert card.preamble == card.renderables
    assert "invalid block structure" in caplog.text


def test_partition_duplicate_and_empty_ids_fall_back() -> None:
    assert CardPart("reply", "Reply", _block("a"), _block("a")).blocks == ()
    assert CardPart("reply", "Reply", _block("", "x\n")).blocks == ()


def test_block_accessors() -> None:
    card = CardPart("reply", "Reply", _block("a", "x\n"))
    assert card.block_ids == ("a",)
    assert card.newest_block_id == "a"
    assert not card.has_block_navigation
    assert CardPart("reply", "Reply", Text("x\n")).newest_block_id is None
    two = CardPart("reply", "Reply", _block("a", "x\n"), _block("b", "y\n"))
    assert two.has_block_navigation
    assert two.block("b") is two.blocks[1]
    assert two.block("missing") is None


def test_block_page_rules() -> None:
    preamble = Text("traceback\n")
    heading = BlockSpreadOnly(Text("AGENT REPLY · 1\n"))
    card = CardPart(
        "reply", "Reply", preamble, heading, _block("a", "old\n"), _block("b", "new\n")
    )
    newest = card.block_page("b")
    assert len(newest) == 2
    assert newest[0] is preamble
    assert _plain_renderable_content(Group(*newest)) == "traceback\n\nnew\n"
    older = card.block_page("a")
    assert len(older) == 1
    assert _plain_renderable_content(Group(*older)) == "old\n"
    assert card.block_page("missing") == ()


def test_digest_changes_on_meta_and_status() -> None:
    first = CardPart("reply", "Reply", _block("a", "same\n", meta=_meta()))
    renamed = CardPart("reply", "Reply", _block("b", "same\n", meta=_meta()))
    assert renderable_content_digest(first) != renderable_content_digest(renamed)
    running = CardPart(
        "reply", "Reply", _block("a", "same\n", meta=_meta(status_bucket="Running"))
    )
    done = CardPart(
        "reply", "Reply", _block("a", "same\n", meta=_meta(status_bucket="Done"))
    )
    assert renderable_content_digest(running) != renderable_content_digest(done)


def test_digest_sees_content_changes_past_2k() -> None:
    head = "x" * 3000 + "\n"
    first = CardPart("reply", "Reply", _block("a", head + "old tail\n"))
    second = CardPart("reply", "Reply", _block("a", head + "new tail\n"))
    assert renderable_content_digest(first) != renderable_content_digest(second)


def test_lower_bound_descends_into_blocks() -> None:
    card = CardPart("reply", "Reply", _block("a", "x\n" * 5000))
    assert _lower_bound_node(card) >= 5000
    assert _lower_bound_rows([card], stop_after=10) > 10


def test_flatten_equivalence_with_blocks() -> None:
    body_a, body_b = Text("alpha\n"), Text("beta\n")
    card = CardPart(
        "reply",
        "Reply",
        Text("pre\n"),
        BlockSpreadOnly(Text("head\n")),
        CardBlock("a", "A", body_a, meta=_meta()),
        CardBlock("b", "B", body_b, meta=_meta()),
    )
    flat = flatten_card_document(card)
    assert isinstance(flat, Group)
    assert [getattr(child, "plain", None) for child in flat.renderables] == [
        "pre\n",
        "head\n",
        "alpha\n",
        "beta\n",
    ]


def test_plain_content_and_carrier_descend_into_blocks() -> None:
    card = CardPart("reply", "Reply", _block("a", "deep\n"))
    assert "deep" in _plain_renderable_content(card_document(card))
    assert "deep" in _plain_renderable_content(card)
    assert _find_carrier(card) is None


def test_split_keeps_blocks_intact() -> None:
    card = CardPart("reply", "Reply", _block("a", "x\n"), _block("b", "y\n"))
    (kept,) = split_card_parts(Group(card))
    assert kept is card
    assert kept.block_ids == ("a", "b")


class _FakePanel(AgentHintsDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def test_hinted_card_keeps_blocks_with_salted_caches() -> None:
    card = CardPart(
        "reply",
        "Reply",
        BlockSpreadOnly(Text("AGENT REPLY · 2\n")),
        _block("a", "old text\n"),
        _block("b", "new text\n"),
    )
    panel = _FakePanel()
    out = panel._prepare_cached_hint_renderable(Group(card))  # type: ignore[arg-type]
    assert isinstance(out, Group)
    (hinted,) = [c for c in out.renderables if isinstance(c, CardPart)]
    assert hinted.block_ids == ("a", "b")
    assert isinstance(hinted.preamble[0], BlockSpreadOnly)
    salts = set()
    for block in hinted.blocks:
        assert len(block.renderables) == 1
        (cached,) = block.renderables
        assert isinstance(cached, CachedRenderable)
        assert cached.code in ("old text\n", "new text\n")
        assert cached.plain == cached.code
        salts.add(cached.content_digest)
    assert len(salts) == 2


def test_identical_block_text_different_ids_diverge() -> None:
    def hinted(block_id: str) -> CardPart:
        panel = _FakePanel()
        out = panel._prepare_cached_hint_renderable(
            Group(CardPart("reply", "Reply", _block(block_id, "same\n")))
        )
        (card,) = [c for c in out.renderables if isinstance(c, CardPart)]  # type: ignore[union-attr]
        return card

    first, second = hinted("id-one"), hinted("id-two")
    first_digest = first.blocks[0].renderables[0].content_digest  # type: ignore[union-attr]
    second_digest = second.blocks[0].renderables[0].content_digest  # type: ignore[union-attr]
    assert first_digest != second_digest
    assert renderable_content_digest(first) != renderable_content_digest(second)


def _rendered_identities(renderable: object) -> set:
    console = Console(record=True, width=120, color_system=None, file=StringIO())
    console.print(renderable, end="")
    return {
        _segment_section_identity(segment)
        for segment in console.render(renderable, console.options)
    }


def test_block_anchor_published_at_divider_row() -> None:
    divider = render_phase_divider(
        "AGENT (code)", None, accent="#AF87FF", block_id="RUNNING|demo|--code"
    )
    assert any(
        isinstance(span.style, Style)
        and span.style.meta
        and span.style.meta.get(DECK_BLOCK_META_KEY) == "RUNNING|demo|--code"
        for span in divider.spans
    )
    identities = _rendered_identities(divider)
    assert (
        "block:RUNNING|demo|--code",
        PromptPanelSectionRole.BLOCK,
    ) in identities


def test_same_text_different_ids_publish_different_anchors() -> None:
    def card(block_id: str) -> CardPart:
        return CardPart(
            "reply",
            "Reply",
            CardBlock(
                block_id,
                "AGENT (code)",
                render_phase_divider("AGENT (code)", None, block_id=block_id),
                Text("same\n"),
                meta=_meta(),
            ),
        )

    first_ids = _rendered_identities(card("id-one"))
    second_ids = _rendered_identities(card("id-two"))
    assert ("block:id-one", PromptPanelSectionRole.BLOCK) in first_ids
    assert ("block:id-two", PromptPanelSectionRole.BLOCK) in second_ids


def test_divider_without_block_id_has_no_block_anchor() -> None:
    divider = render_phase_divider("AGENT (code)", None)
    identities = _rendered_identities(divider)
    assert not any(
        identity is not None and identity[1] is PromptPanelSectionRole.BLOCK
        for identity in identities
    )
