"""CSS for the reusable pager reading surface."""

from __future__ import annotations

PAGER_CSS = """
PagerScreen {
    layout: vertical;
    background: $background;
}

PagerScreen .hidden {
    display: none;
}

PagerScreen #pager-subject {
    height: 1;
    padding: 0 1;
    background: $boost;
}

PagerScreen #pager-trail {
    height: 2;
    padding: 0 1;
    background: $surface;
    color: $text;
}

PagerScreen #pager-trail.compact {
    height: 1;
}

PagerScreen #pager-chrome-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerScreen #pager-body-scroll {
    height: 1fr;
}

PagerScreen #pager-body {
    width: 100%;
    padding: 0 1;
}

PagerScreen #pager-search-command {
    height: 1;
    padding: 0 1;
}

PagerScreen #pager-goto-command {
    height: 1;
    padding: 0 1;
}

PagerScreen #pager-footer-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerScreen #pager-footer {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerHelpScreen {
    background: transparent;
    align: center middle;
}

PagerHelpScreen #pager-help {
    width: 88;
    max-width: 92%;
    height: 80%;
    max-height: 90%;
    border: round $accent;
    background: $surface;
}

PagerHelpScreen #pager-help-header {
    height: 1;
    padding: 0 1;
    background: $boost;
}

PagerHelpScreen #pager-help-scroll {
    height: 1fr;
    padding: 1 2;
}

PagerHelpScreen #pager-help-content {
    width: 100%;
}

PagerHelpScreen #pager-help-footer {
    height: 1;
    padding: 0 1;
    background: $boost;
    color: $text-muted;
}
"""

__all__ = ["PAGER_CSS"]
