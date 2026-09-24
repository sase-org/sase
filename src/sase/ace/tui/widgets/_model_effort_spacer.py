"""Detect the ``%m:<model> `` spacer that ``@`` rewrites into an effort suffix."""

from __future__ import annotations

from sase.ace.tui.widgets._directive_completion_tokens import (
    classify_directive_completion,
)


def find_model_effort_spacer(line: str, col: int) -> int | None:
    """Return the column of the space to replace with ``@``, or ``None``.

    Matches when the cursor at *col* sits right after exactly one space that
    follows a completed colon-form ``%model`` value, at end of line or before
    whitespace.
    """
    if col < 2 or col > len(line) or line[col - 1] != " " or line[col - 2].isspace():
        return None
    if col < len(line) and not line[col].isspace():
        return None
    clause = classify_directive_completion(line, col - 1)
    if (
        clause is None
        or clause.kind != "directive_argument"
        or clause.directive_name != "model"
        or clause.syntax_form != "colon"
        or clause.value_role != "model"
        or not clause.token
        or clause.end != col - 1
    ):
        return None
    return col - 1
