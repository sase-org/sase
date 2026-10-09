"""Plan modal rendering: rail layout, tinted first frame, keypress cost, and polling."""

from __future__ import annotations

from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_compact_verdict_stays_inside_rail_with_stylesheet",
    "test_draft_edit_avoids_revalidate_relex",
    "test_first_frame_tint_keeps_syntax",
    "test_generic_gate_rail_stays_42_with_stylesheet",
    "test_settled_polling_reads_only_open_modal",
]


async def test_compact_verdict_stays_inside_rail_with_stylesheet(tmp_path) -> None:
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import VerticalScroll as _VS

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "rail_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    for choice in ("tale", "epic"):
        for with_decisions in (True, False):
            defs = plan_decision_definitions(tmp_path) if with_decisions else []
            for width, height in ((120, 40), (90, 40)):
                modal = _Modal(
                    str(plan),
                    default_choice=choice,  # type: ignore[arg-type]
                    plan_content="# Plan\n",
                    decision_definitions=list(defs),
                    review_revision=3,
                    request_id=f"req-rail-{choice}-{with_decisions}-{width}",
                )
                async with _StyledApp().run_test(size=(width, height)) as pilot:
                    pilot.app.push_screen(modal)
                    await pilot.pause()
                    await pilot.pause()
                    rail = modal.query_one(".gate-review-actions", _VS)
                    content = rail.content_region
                    for btn in modal.query("#plan-verdict GateControlButton"):
                        assert content.contains_region(btn.region), (
                            choice,
                            with_decisions,
                            width,
                            btn.id,
                            btn.region,
                            content,
                        )
                    line2 = modal.query_one("#plan-verdict-line2")
                    line2_labels = " ".join(
                        str(b.label) for b in line2.query("GateControlButton")
                    )
                    if choice == "tale":
                        line1 = modal.query_one("#plan-verdict-line1")
                        labels1 = " ".join(
                            str(b.label) for b in line1.query("GateControlButton")
                        )
                        assert "Launch coder" in labels1
                        assert "Commit plan" in labels1
                        assert "1 ✅ Tale" in line2_labels
                        assert "2 ❌ Reject" in line2_labels
                        assert "3 💬 Feedback" in line2_labels
                    else:
                        assert not modal.query("#plan-verdict-line1")
                        assert "1 ✅ Epic" in line2_labels
                        assert "Commit plan" not in " ".join(
                            str(b.label) for b in modal.query("GateControlButton")
                        )
                    if with_decisions:
                        header = modal.query_one("#plan-decisions-header")
                        verdict = modal.query_one("#plan-verdict")
                        assert content.contains_region(header.region)
                        assert not header.region.overlaps(verdict.region)
                    if width == 120:
                        # Wide breakpoint: docked-left rail widths are exact.
                        # Decisions rails stay 50; decision-free plan rails
                        # keep the 44 cells the compact Verdict needs.
                        assert rail.region.width == (50 if with_decisions else 44), (
                            choice,
                            with_decisions,
                            rail.region,
                        )
                    pilot.app.pop_screen()
                    await pilot.pause()


async def test_generic_gate_rail_stays_42_with_stylesheet(tmp_path) -> None:
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import VerticalScroll as _VS

    from sase.ace.tui.modals.custom_gate_modal import (
        CustomGateModal as _CustomModal,
        CustomGateModalData as _CustomData,
    )
    from sase.ace.tui.modals.plan_approval_gate_data import (
        default_plan_gate_data as _plan_gate,
    )

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    data = _CustomData(
        request_id="req-generic-rail-1",
        title="Generic gate",
        sender="agent",
        icon="❓",
        notes=("note",),
        attachments=(),
        preview_name="Preview",
        preview_text="# Preview\n",
        gate=_plan_gate("tale"),
    )
    modal = _CustomModal(data)
    async with _StyledApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        rail = modal.query_one(".gate-review-body > .gate-review-actions", _VS)
        assert rail.region.width == 42, rail.region
        pilot.app.pop_screen()
        await pilot.pause()


async def test_first_frame_tint_keeps_syntax(tmp_path) -> None:
    from textual.app import App as _App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    class _App2(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "tint_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    defs = plan_decision_definitions(tmp_path)
    modal = _Modal(
        str(plan),
        default_choice="tale",
        plan_content=(
            "---\n"
            "tier: tale\n"
            "title: Tint\n"
            "goal: Keep colours\n"
            "size: small\n"
            "decisions:\n"
            "  grouping:\n"
            "    ask: Group?\n"
            "    choices:\n"
            "      pane: By pane\n"
            "      mode: By mode\n"
            "    default: pane\n"
            "---\n"
            "# Plan\n"
            "> [!decision] grouping = pane Order by pane.\n"
            "> [!decision] grouping = mode Order by mode.\n"
        ),
        decision_definitions=defs,
        review_revision=3,
        request_id="req-tint-1",
    )
    async with _App2().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        assert list(modal._callout_spans or []) != []  # type: ignore[attr-defined]
        from textual.widgets import Static as _Static

        content = modal.query_one("#plan-approval-content", _Static)
        rendered = content.render()
        text = rendered if hasattr(rendered, "plain") else rendered.__rich__()  # type: ignore[union-attr]
        # Static may hold a Syntax renderable when untinted; tinted path is Text.
        from rich.text import Text as _Text

        if not isinstance(text, _Text):
            # Fall back to the modal's own renderable for the tint asserts.
            folded = getattr(modal, "_folded_text", "") or ""
            text = modal._document_renderable(folded)  # type: ignore[attr-defined]
        assert isinstance(text, _Text)
        assert "Order by mode" in text.plain
        spans = list(getattr(text, "_spans", []) or [])
        assert spans, "expected tint + token spans"
        styles = [str(getattr(s, "style", "")) for s in spans]
        assert any("bold" in s and "green" in s for s in styles)
        assert any(s.strip() == "dim" or "dim" in s for s in styles)
        # At least one syntax token style survives alongside the tint overlay.
        assert (
            any("#" in s or "272822" in s or "monokai" in s.lower() for s in styles)
            or len(spans) >= 5
        )
        # Rendered output (the Textual Content path the Static widget paints):
        # the chosen header must be green+bold, the unchosen dim, and a
        # non-tinted token must keep its theme colour.
        from textual.content import Content as _Content

        rendered_content = _Content.from_rich_text(text)
        segments = list(rendered_content.render())
        assert segments, "expected rendered segments"

        def _style_for(marker: str):  # type: ignore[no-untyped-def]
            for chunk, style in segments:
                if marker in chunk:
                    return style
            raise AssertionError(f"marker {marker!r} missing from rendered output")

        chosen_style = _style_for("Order by pane")
        assert chosen_style.bold is True, chosen_style
        assert chosen_style.foreground is not None, chosen_style
        # Textual 8.2+ keeps ANSI colors (like this "bold green" tint)
        # unresolved until paint time, so the rendered placeholder carries
        # the palette slot (ansi 2, green) with a black RGB triple instead
        # of the resolved theme RGB. Accept either representation as green.
        chosen_foreground = chosen_style.foreground
        assert getattr(chosen_foreground, "ansi", None) == 2 or (
            chosen_foreground.g > chosen_foreground.r
            and chosen_foreground.g > chosen_foreground.b
        ), chosen_style
        unchosen_style = _style_for("Order by mode")
        assert unchosen_style.dim is True, unchosen_style
        token_style = _style_for("tier")
        assert token_style.dim is not True, token_style
        assert token_style.bold is not True, token_style
        assert token_style.foreground is not None, token_style
        assert not (
            token_style.foreground.g > token_style.foreground.r
            and token_style.foreground.g > token_style.foreground.b
        ), token_style


async def test_draft_edit_avoids_revalidate_relex(tmp_path) -> None:
    from textual.app import App as _App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    class _App3(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "keypress_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    modal = _Modal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=1,
        request_id="req-keypress-1",
    )
    async with _App3().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        import unittest.mock as _mock

        with (
            _mock.patch(
                "sase.sdd.plan_validate.validate_plan",
                side_effect=AssertionError("validate on keypress"),
            ),
            _mock.patch(
                "sase.ace.tui.modals.plan_decision_document.cache_callout_spans",
                side_effect=AssertionError("cache on keypress"),
            ),
            _mock.patch(
                "sase.ace.tui.util.frontmatter_syntax._lex_frontmatter_markdown",
                side_effect=AssertionError("lex on keypress"),
            ),
        ):
            modal._apply_draft_edit(lambda: modal._decision_draft.step("grouping", 1))  # type: ignore[attr-defined]
            await pilot.pause()


def test_settled_polling_reads_only_open_modal(tmp_path) -> None:
    import asyncio
    import os
    import types as _types
    import unittest.mock as _mock

    from sase.notifications import Notification

    # No modal open: full poll never verifies, even with a PlanApproval row.
    from tests._notification_toasts_helpers import _FakeApp, _make, _patch_snapshot

    notification = _make(
        action="PlanApproval",
        notes=["plan"],
        action_data={"request_id": "req-settled-1"},
        sender="agent",
    )
    app = _FakeApp()
    app._agents = []  # type: ignore[attr-defined]
    app._agents_with_children = []  # type: ignore[attr-defined]
    from tests.test_notification_completion_arrival import _install_captures

    _install_captures(app)
    loads = {"n": 0}
    real_load = None
    try:
        import sase.notification_gates.hashing as _hashing

        real_load = _hashing.load_and_verify_bundle
    except Exception:
        pass

    def _counting(root: object, *a: object, **k: object):  # type: ignore[no-untyped-def]
        loads["n"] += 1
        if real_load is None:
            raise AssertionError("no bundle")
        return real_load(root, *a, **k)

    with (
        _patch_snapshot([notification]),
        _mock.patch(
            "sase.notification_gates.hashing.load_and_verify_bundle",
            side_effect=_counting,
        ),
    ):
        asyncio.run(app._poll_agent_completions_once())
    assert loads["n"] == 0

    # Open modal: missing response never verifies; present verifies once per mtime.
    from sase.ace.tui.actions.agents._notification_polling import (
        _prepare_settled_for_open_modal,
    )

    request_id = "req-modal-7"
    fake_notification = Notification(
        id=request_id,
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(tmp_path / "plan.md")],
        action="PlanApproval",
        action_data={"request_id": request_id},
    )
    response = tmp_path / "response.json"
    if response.exists():
        response.unlink()
    bundle = _types.SimpleNamespace(
        root=tmp_path,
        request=tmp_path / "request.json",
        response=response,
        cancellation=tmp_path / "cancel.json",
        legacy=False,
    )
    poll_app: object = _types.SimpleNamespace()

    def _counting_fake(root: object, *a: object, **k: object):  # type: ignore[no-untyped-def]
        loads["n"] += 1
        return ({"kind": "tale", "payload": {"decisions": []}}, object())

    with (
        _mock.patch(
            "sase.notification_gates.paths.resolve_notification_bundle",
            return_value=bundle,
        ),
        _mock.patch(
            "sase.notification_gates.hashing.load_and_verify_bundle",
            side_effect=_counting_fake,
        ),
        _mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate_load._settled_text_for_bundle",
            return_value="Approved via CLI",
        ),
    ):
        loads["n"] = 0
        assert (
            _prepare_settled_for_open_modal(poll_app, fake_notification, request_id)
            == {}
        )
        assert loads["n"] == 0
        response.write_text("{}", encoding="utf-8")
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 1
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 1
        prev = response.stat().st_mtime_ns
        os.utime(
            response,
            ns=(
                response.stat().st_atime_ns,
                max(response.stat().st_mtime_ns, prev + 1),
            ),
        )
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 2
