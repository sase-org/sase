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

PagerScreen #pager-root {
    height: 1fr;
}

PagerScreen #pager-panes {
    height: 1fr;
}

PagerScreen #pager-panes.-single {
    layout: vertical;
}

PagerScreen #pager-panes.-below {
    layout: vertical;
}

PagerScreen #pager-panes.-beside {
    layout: horizontal;
}

PagerView {
    layout: vertical;
    height: 1fr;
    width: 1fr;
}

PagerView .hidden {
    display: none;
}

PagerView #pager-subject {
    height: 1;
    padding: 0 1;
    background: $boost;
}

PagerView #pager-trail {
    height: 2;
    padding: 0 1;
    background: $surface;
    color: $text;
}

PagerView #pager-trail.compact {
    height: 1;
}

PagerView #pager-time {
    height: 1;
    padding: 0 1;
    background: $surface;
    color: $text;
}

PagerView #pager-time.two {
    height: 2;
}

PagerView #pager-chrome-rule {
    height: 1;
    padding: 0 1;
    color: $text-muted;
}

PagerView #pager-body-scroll {
    height: 1fr;
}

PagerView #pager-body {
    width: 100%;
    padding: 0 1;
}

PagerView #pager-search-command {
    height: 1;
    padding: 0 1;
}

PagerView #pager-goto-command {
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

TimelinePickerScreen {
    background: transparent;
    align: center middle;
}

TimelinePickerScreen #pager-timeline {
    width: 88;
    max-width: 94%;
    height: 80%;
    max-height: 90%;
    border: round $accent;
    background: $surface;
}

TimelinePickerScreen #pager-timeline-header {
    height: 1;
    padding: 0 1;
    background: $boost;
}

TimelinePickerScreen #pager-timeline-list {
    height: 1fr;
    padding: 1 2;
}

TimelinePickerScreen #pager-timeline-footer {
    height: 1;
    padding: 0 1;
    background: $boost;
    color: $text-muted;
}
"""

__all__ = ["PAGER_CSS"]
