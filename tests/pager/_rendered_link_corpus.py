"""Deterministic fixture corpus for pager rendered-link contract tests.

Mirrors the screenshot plan table and capture sources without depending on
live bob-cli / bob-mac-capture checkouts. Inventory/store roots are replaced
by an explicit ``ArtifactRefContext``; the resolver itself is not stubbed.
"""

from __future__ import annotations

from tests.pager._rendered_link_assertions import (
    assert_expected_rendered,
    forbid_checkout_allocation,
    install_inventory,
    owner_for_checkout,
    rendered_spans,
)
from tests.pager._rendered_link_expected import (
    ExpectedOccurrence,
    kitchen_expected,
    screenshot_expected,
)
from tests.pager._rendered_link_fixtures import (
    CONTROLLER,
    CYCLING_URL,
    DESIGN_LINE_TARGET,
    EXACT_URL,
    KITCHEN_BODY,
    LINE_TARGET,
    PLAN_CYCLING,
    PLAN_LINE_TARGET,
    PLAN_PREVIOUS,
    PLAN_SPACED,
    PREVIOUS_URL,
    ROUTER,
    ROUTER_TESTS,
    SCREENSHOT_BODY,
)
from tests.pager._rendered_link_tree import RenderedLinkCorpus, build_corpus

__all__ = [
    "CONTROLLER",
    "CYCLING_URL",
    "DESIGN_LINE_TARGET",
    "ExpectedOccurrence",
    "EXACT_URL",
    "KITCHEN_BODY",
    "LINE_TARGET",
    "PLAN_CYCLING",
    "PLAN_LINE_TARGET",
    "PLAN_PREVIOUS",
    "PLAN_SPACED",
    "PREVIOUS_URL",
    "ROUTER",
    "ROUTER_TESTS",
    "RenderedLinkCorpus",
    "SCREENSHOT_BODY",
    "assert_expected_rendered",
    "build_corpus",
    "forbid_checkout_allocation",
    "install_inventory",
    "kitchen_expected",
    "owner_for_checkout",
    "rendered_spans",
    "screenshot_expected",
]
