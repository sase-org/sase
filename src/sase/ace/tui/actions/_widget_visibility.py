"""Defensive widget visibility helpers shared by TUI action mixins."""

from __future__ import annotations


def set_widget_hidden(widget: object, hidden: bool) -> None:
    if hidden:
        add_class = getattr(widget, "add_class", None)
        if callable(add_class):
            add_class("hidden")
    else:
        remove_class = getattr(widget, "remove_class", None)
        if callable(remove_class):
            remove_class("hidden")


def widget_has_class(widget: object, class_name: str) -> bool:
    has_class = getattr(widget, "has_class", None)
    return bool(has_class(class_name)) if callable(has_class) else False
