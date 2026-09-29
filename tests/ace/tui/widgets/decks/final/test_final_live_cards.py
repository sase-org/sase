"""In-card live-tail rendering over the real projection dataclasses."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets.decks.final.document import build_final_deck_document
from sase.ace.tui.widgets.decks.final.instance_card import (
    build_instance_card_renderables,
)
from sase.core.finalizer_run_view import (
    FinalizerNodeView,
    _RunViewNodeInstance,
    RunViewRun,
)
from tests.ace.tui.widgets.decks.final._final_live_shared import (
    NOW,
    make_active_op,
    make_run,
    make_run_instance,
)

__all__ = [
    "test_card_hides_tail_before_gate_opens",
    "test_card_hides_tail_for_settled_ops",
    "test_card_renders_gated_live_tail_for_active_op",
    "test_card_tail_caps_at_twelve_lines",
    "test_card_tail_never_bleeds_across_agents",
    "test_card_tails_follow_newest_run_only",
    "test_document_build_threads_live_tail",
]


def _text(renderables: tuple[object, ...]) -> str:
    parts: list[str] = []
    for renderable in renderables:
        if isinstance(renderable, Text):
            parts.append(renderable.plain)
        else:
            parts.append(str(renderable))
    return "\n".join(parts)


def _node(instance_id: str, runs: list[RunViewRun]) -> FinalizerNodeView:
    return FinalizerNodeView(
        schema_version=1,
        status="running",
        glyph="▶",
        instances=[
            _RunViewNodeInstance(
                instance_id=instance_id,
                selection_reason="default",
                status="running",
            )
        ],
        runs=runs,
    )


# Card rendering ----------------------------------------------------------


def test_card_renders_gated_live_tail_for_active_op() -> None:
    runs = [make_run("run-a", make_run_instance(make_active_op()))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "live · 30s" in body
    assert "line one" in body
    assert "line two" in body


def test_card_hides_tail_before_gate_opens() -> None:
    runs = [make_run("run-a", make_run_instance(make_active_op(started_at=NOW - 1.0)))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=5.0, live_now=NOW
        )
    )
    assert "line one" not in body
    assert "live" not in body


def test_card_hides_tail_for_settled_ops() -> None:
    runs = [
        make_run(
            "run-a",
            make_run_instance(make_active_op(returncode=0, live_tail=["stale"])),
        )
    ]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "stale" not in body


def test_card_tails_follow_newest_run_only() -> None:
    old_op = make_active_op(live_tail=["old tail"])
    new_op = make_active_op(live_tail=["new tail"])
    runs = [
        make_run("run-old", make_run_instance(old_op)),
        make_run("run-new", make_run_instance(new_op)),
    ]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "new tail" in body
    assert "old tail" not in body


def test_card_tail_never_bleeds_across_agents() -> None:
    runs_a = [
        make_run("run-a", make_run_instance(make_active_op(live_tail=["agent A tail"])))
    ]
    runs_b = [
        make_run("run-b", make_run_instance(make_active_op(live_tail=["agent B tail"])))
    ]
    body_a = _text(
        build_instance_card_renderables(
            _node("check", runs_a).instances[0],
            runs_a,
            live_delay_seconds=0,
            live_now=NOW,
        )
    )
    body_b = _text(
        build_instance_card_renderables(
            _node("check", runs_b).instances[0],
            runs_b,
            live_delay_seconds=0,
            live_now=NOW,
        )
    )
    assert "agent A tail" in body_a and "agent B tail" not in body_a
    assert "agent B tail" in body_b and "agent A tail" not in body_b


def test_card_tail_caps_at_twelve_lines() -> None:
    tail = [f"trace {index}" for index in range(20)]
    runs = [make_run("run-a", make_run_instance(make_active_op(live_tail=tail)))]
    node = _node("check", runs)
    body = _text(
        build_instance_card_renderables(
            node.instances[0], runs, live_delay_seconds=0, live_now=NOW
        )
    )
    assert "trace 0" not in body
    assert "trace 19" in body


def test_document_build_threads_live_tail() -> None:
    runs = [make_run("run-a", make_run_instance(make_active_op()))]
    node = _node("check", runs)
    document = build_final_deck_document(
        node, subject="agent-x", digest="d", live_tail_delay=0, live_now=NOW
    )
    assert "agent-x" in document.card_ids or document.cards
    flat = "\n".join(
        part.plain
        for card in document.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "line one" in flat
    calm = build_final_deck_document(node, subject="agent-x", digest="d")
    calm_flat = "\n".join(
        part.plain
        for card in calm.cards
        for part in card.renderables
        if isinstance(part, Text)
    )
    assert "line one" not in calm_flat
