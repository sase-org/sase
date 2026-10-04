"""Save-as-macro input inference skips engine builtins."""

from __future__ import annotations

from sase.macro.jinja_assist import JinjaScope
from sase.macro.jinja_inspect import undeclared_variables


def test_save_inference_skips_engine_builtins() -> None:
    body = "{{ wait.chats }} {{ patch_name }} {{ n }} {{ my_var }}"

    unknown = undeclared_variables(body, JinjaScope(kind="xprompt", frontmatter=None))

    assert unknown is not None
    assert "wait" not in unknown
    assert "patch_name" not in unknown
    assert "n" not in unknown
    assert "my_var" in unknown
