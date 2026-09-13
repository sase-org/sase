"""Tests for retired directive diagnostics."""

from __future__ import annotations

import pytest

from sase.xprompt.directive_diagnostics import find_retired_directive_usages


@pytest.mark.parametrize(
    ("content", "line", "source", "message"),
    [
        (
            "%wait(priority=20)\nDo work",
            1,
            "%wait(priority=20)",
            "%wait(priority=...) has moved to %queue",
        ),
        (
            "Prepare\n%w(runners=2)\nDo work",
            2,
            "%w(runners=2)",
            "%wait(runners=...) has moved to %queue",
        ),
        (
            "%wait(capacity=1)\nDo work",
            1,
            "%wait(capacity=1)",
            "%wait(capacity=...) belongs on %queue",
        ),
        (
            "%wait(p=3)\nDo work",
            1,
            "%wait(p=3)",
            "%wait(p=...) is unsupported",
        ),
        (
            "%name:foo\nDo work",
            1,
            "%name:foo",
            "use %id/%i",
        ),
    ],
)
def test_retired_directive_usages_report_line_and_message(
    content: str,
    line: int,
    source: str,
    message: str,
) -> None:
    usages = find_retired_directive_usages(content)

    assert [(usage.line, usage.source) for usage in usages] == [(line, source)]
    assert message in usages[0].message


def test_retired_wait_usage_reports_line_in_multi_segment_body() -> None:
    content = "\n".join(
        [
            "%id:first",
            "---",
            "%id:second",
            "---",
            "Third segment",
            "%wait(priority=20)",
            "Do work",
        ]
    )

    usages = find_retired_directive_usages(content)

    assert len(usages) == 1
    assert usages[0].line == 6
    assert usages[0].source == "%wait(priority=20)"


@pytest.mark.parametrize(
    "content",
    [
        "%q(p=20)\nDo work",
        "%queue(priority=20)\nDo work",
        "%wait:agent %q:1\nDo work",
        "%w(builder, time=5m) %q(1, p=20)\nDo work",
        "```\n%wait(priority=1)\n```\nDo work",
        (
            "%wait:{{ wait }} {% endif %}%q(w=0.25"
            "{% if runners is not none %}, capacity={{ runners }}{% endif %}"
            "{% if priority is not none %}, priority={{ priority }}{% endif %})"
        ),
        "%wait(time=5m)\nDo work",
        "%{%wait(priority=1) | no queue control here}",
    ],
)
def test_retired_directive_usages_ignore_supported_or_inactive_syntax(
    content: str,
) -> None:
    assert find_retired_directive_usages(content) == []
