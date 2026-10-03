"""Opt-in collection of xprompt definition load issues."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class XPromptLoadIssue:
    """A non-fatal xprompt/workflow definition loading issue."""

    source: str
    error: str
    kind: str


_ISSUES: ContextVar[list[XPromptLoadIssue] | None] = ContextVar(
    "xprompt_load_issues",
    default=None,
)


def record_load_issue(source: object, error: object, *, kind: str) -> None:
    """Record a load issue when collection is active."""
    issues = _ISSUES.get()
    if issues is None:
        return
    source_text = str(source)
    error_text = str(error)
    if any(
        issue.source == source_text and issue.error == error_text for issue in issues
    ):
        return
    issues.append(XPromptLoadIssue(source_text, error_text, kind))


@contextmanager
def collect_xprompt_load_issues() -> Generator[list[XPromptLoadIssue]]:
    """Collect non-fatal xprompt definition loading issues in this context."""
    issues: list[XPromptLoadIssue] = []
    token = _ISSUES.set(issues)
    try:
        yield issues
    finally:
        _ISSUES.reset(token)


__all__ = [
    "XPromptLoadIssue",
    "collect_xprompt_load_issues",
    "record_load_issue",
]
