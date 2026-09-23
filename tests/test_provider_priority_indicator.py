"""ProviderPriorityIndicator pill and tooltip tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._override_pill import (
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.testing import AcePage
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _ACTIVE_STYLE,
)
from sase.ace.tui.widgets.provider_priority_indicator import (
    ProviderPriorityIndicator,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from sase.llm_provider.provider_priority import provider_routing_context_from_parts
from tests._provider_disables_indicator_helpers import (
    _disable,
    _patch_priority_facts,
    _priority,
)


def test_group_label_is_priority() -> None:
    assert ProviderPriorityIndicator.GROUP_LABEL == "priority"


def test_no_priority_renders_empty() -> None:
    assert ProviderPriorityIndicator._build_content(None, now=100.0).plain == ""


def test_priority_renders_countdown_without_state_word() -> None:
    text = ProviderPriorityIndicator._build_content(
        _priority("codex", expires_at=3_820.0),
        now=100.0,
    )

    assert text.plain == " CODEX ★ 1h2m "
    assert str(text.style) == PROVIDER_PRIORITY_PALETTE.base_style


def test_expired_priority_renders_empty() -> None:
    text = ProviderPriorityIndicator._build_content(
        _priority("codex", expires_at=99.0),
        now=100.0,
    )

    assert text.plain == ""


def test_hard_disabled_priority_renders_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable("codex", expires_at=None)
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )

    text = ProviderPriorityIndicator._build_content(
        context.priority,
        priority_availability=ProviderPriorityIndicator._priority_availability(context),
        now=100.0,
    )

    assert text.plain == " CODEX ★ unavailable 1h2m "


def test_soft_disabled_priority_renders_soft_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable(
        "codex",
        expires_at=None,
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )

    text = ProviderPriorityIndicator._build_content(
        context.priority,
        priority_availability=ProviderPriorityIndicator._priority_availability(context),
        now=100.0,
    )

    assert text.plain == " CODEX ★ soft-disabled 1h2m "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_missing_cli_priority_renders_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch, cli_available=False)
    priority = _priority("codex", expires_at=3_820.0)
    context = provider_routing_context_from_parts({}, priority, captured_at=100.0)

    availability = ProviderPriorityIndicator._priority_availability(context)
    text = ProviderPriorityIndicator._build_content(
        context.priority,
        priority_availability=availability,
        now=100.0,
    )
    tooltip = ProviderPriorityIndicator._build_tooltip(
        context.priority,
        priority_availability=availability,
        now=100.0,
    )

    assert text.plain == " CODEX ★ unavailable 1h2m "
    assert "CODEX - unavailable · 1h2m left" in (tooltip or "")


def test_tooltip_has_priority_heading_and_lines() -> None:
    tooltip = ProviderPriorityIndicator._build_tooltip(
        _priority("codex", expires_at=3_820.0),
        now=100.0,
    )

    assert tooltip is not None
    assert tooltip.startswith("Provider priority:\n")
    assert "CODEX - preferred · 1h2m left" in tooltip
    assert "Pools prefer the priority provider" in tooltip
    assert tooltip.endswith("Press ,m for Config > Launch.")


def test_no_plus_n_in_any_priority_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable("codex", expires_at=None)
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )

    for availability in (
        None,
        ProviderPriorityIndicator._priority_availability(context),
    ):
        text = ProviderPriorityIndicator._build_content(
            priority,
            priority_availability=availability,
            now=100.0,
        )
        assert "+1" not in text.plain
        assert "+N" not in text.plain


def test_unavailable_priority_uses_hard_accent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable("codex", expires_at=None)
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )
    text = ProviderPriorityIndicator._build_content(
        context.priority,
        priority_availability=ProviderPriorityIndicator._priority_availability(context),
        now=100.0,
    )

    assert str(text.style) == _ACTIVE_STYLE


async def test_single_peek_drives_both_routing_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.widgets.provider_disables_indicator as disables_module
    import sase.ace.tui.widgets.provider_priority_indicator as priority_module

    context = provider_routing_context_from_parts(
        {"claude": _disable("claude", expires_at=None)},
        _priority("codex", expires_at=None),
        captured_at=100.0,
    )
    calls = {"count": 0}

    def _peek(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return context

    monkeypatch.setattr(disables_module, "peek_provider_routing_context", _peek)
    monkeypatch.setattr(priority_module, "peek_provider_routing_context", _peek)
    async with AcePage(size=(220, 40)) as page:
        disables = page.app.query_one(
            "#provider-disables-indicator", ProviderDisablesIndicator
        )
        priority = page.app.query_one(
            "#provider-priority-indicator", ProviderPriorityIndicator
        )
        calls["count"] = 0
        disables._apply_content()
        await page.pause()
        assert calls["count"] == 1
        assert priority.group_visible
        assert disables.group_visible
        # Each fact gets its own label, color, and tooltip.
        assert "CODEX" in priority._body.plain
        assert "CLAUDE" in disables._body.plain
        assert "+1" not in priority._body.plain
        cluster = page.app.query_one("#top-bar-indicators", _cluster_type())
        visible_ids = [child.id for child in cluster.groups() if child.group_visible]
        assert "provider-priority-indicator" in visible_ids
        assert "provider-disables-indicator" in visible_ids

        # Clearing the priority hides the priority group.
        cleared = provider_routing_context_from_parts(
            {"claude": _disable("claude", expires_at=None)},
            None,
            captured_at=100.0,
        )
        monkeypatch.setattr(
            disables_module, "peek_provider_routing_context", lambda *a, **k: cleared
        )
        disables._apply_content()
        await page.pause()
        assert not priority.group_visible
        assert disables.group_visible


def _cluster_type():  # type: ignore[no-untyped-def]
    from sase.ace.tui.widgets.top_bar import TopBarIndicators

    return TopBarIndicators
