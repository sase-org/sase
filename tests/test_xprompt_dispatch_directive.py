"""Runtime parser and side-effect-free scanner coverage for `%dispatch`."""

from __future__ import annotations

import pytest

from sase.xprompt._directive_scan import scan_dispatch_directive
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_dispatch_directive_extracts_without_alias() -> None:
    cleaned, directives = extract_prompt_directives(
        "%dispatch:apollo %id:worker do the work",
    )

    assert directives.dispatch == "apollo"
    assert directives.name == "worker"
    assert cleaned == "  do the work"


def test_dispatch_scan_strips_only_dispatch_directive() -> None:
    scan = scan_dispatch_directive("%dispatch(apollo) %id:worker do the work")

    assert scan is not None
    assert scan.target == "apollo"
    assert scan.prompt == " %id:worker do the work"


@pytest.mark.parametrize(
    "prompt",
    [
        "%dispatch:local run here",
        "%dispatch(apollo, zeus) run there",
        "%dispatch(machine=apollo) run there",
        "%dispatch:apollo %wait:planner run there",
        "%dispatch:apollo %q:1 run there",
        "%dispatch:apollo %clan:builders run there",
    ],
)
def test_dispatch_scan_rejects_invalid_or_v1_unsupported_forms(prompt: str) -> None:
    with pytest.raises(DirectiveError):
        scan_dispatch_directive(prompt)
