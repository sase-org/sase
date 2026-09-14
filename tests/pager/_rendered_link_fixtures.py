"""Fixture bodies and constants for the rendered-link corpus tests."""

from __future__ import annotations

from typing import Literal

Outcome = Literal[
    "document",
    "url_copy",
    "media",
    "unavailable",
    "ambiguous",
    "filtered",
    "attached",
]

PLAN_CYCLING = "plan:202609/capture_line_edge_cycling.md"
PLAN_LINE_TARGET = "plan:202609/line_target_plan.md"
PLAN_PREVIOUS = "plan:202609/capture_ctrl_u_previous_line.md"
PLAN_SPACED = "plan:spaced plan.md#L3"
ROUTER = "Sources/BobMacCapture/CaptureKeyCommandRouter.swift"
CONTROLLER = "Sources/BobMacCapture/CaptureKeyCommandController.swift"
ROUTER_TESTS = "Tests/BobMacCaptureTests/CaptureKeyCommandRouterTests.swift"
LINE_TARGET = "src/line_targets.py"
DESIGN_LINE_TARGET = "designs:line_target_design.md"
CYCLING_URL = (
    "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/"
    "202609/capture_line_edge_cycling.md"
)
PREVIOUS_URL = (
    "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/"
    "202609/capture_ctrl_u_previous_line.md"
)
EXACT_URL = "https://example.test/exact?q=1#frag"

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

SCREENSHOT_BODY = f"""# capture_line_edge_cycling

See {ROUTER}
and {CONTROLLER}
and {ROUTER_TESTS}.

<!-- sase:links:start -->

## Links

| Relation | Artifact | Why |
| --- | --- | --- |
| implements | [plan:202609/capture_line_edge_cycling.md][2] | screenshot |
| related | [plan:202609/capture_ctrl_u_previous_line.md][3] | screenshot |

[2]: {CYCLING_URL}
[3]: {PREVIOUS_URL}

<!-- sase:links:end -->
"""

KITCHEN_BODY = f"""# kitchen sink

Sigiled quoted @plan:"spaced plan.md"#L3
Unsigiled bead:sase-zz.n0 and sigiled @bead:sase-zz.n0
Patch patch:fixture-patch and @patch:fixture-patch
Agent agent:alice.athena.fixture
Stitch stitch:deadbee1deadbee1
Indexed file:explicit:0123456789abcdef01234567
Markdown dest [not the path](src/lined.swift:4:2)
Sigiled file @src/naïve.md
Unicode line docs/café.md:12
Line direct src/line_targets.py:12
Line column src/line_targets.py:12:5
Line range src/line_targets.py:12-40
GitHub line src/line_targets.py#L12
GitHub range src/line_targets.py#L12-L40
GitHub column src/line_targets.py#L12C5
Markdown range [range dest](src/line_targets.py:27-44)
Markdown GitHub [column dest](src/line_targets.py#L27C3)
Typed plan plan:202609/line_target_plan.md:12
Sigiled typed plan @plan:202609/line_target_plan.md:12-20
Typed plan GitHub plan:202609/line_target_plan.md#L3C2
Configured sidecar designs:line_target_design.md:40
Past EOF src/line_targets.py:9999
Directory ./docs/assets
Media docs/assets/dot.png
Missing Sources/DoesNotExist.swift
URL {EXACT_URL}
"""
