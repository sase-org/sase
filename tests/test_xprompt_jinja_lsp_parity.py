"""LSP/binary parity for Jinja completion.

The Rust engine is the single source of truth for Jinja completion: the
``sase-xprompt-lsp`` binary calls it directly, and the TUI calls it through
:mod:`sase.xprompt.jinja_assist`. For each shared fixture and cursor, this
suite runs both surfaces and asserts identical ordered names, kinds,
source/availability labels, and documentation.

The lifted-frontmatter cases prove the two scope spellings agree: the
adapter gets ``frontmatter=<yaml>`` plus the body, while the LSP gets the
full document with the frontmatter block inline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.xprompt.jinja_assist import (
    JinjaCompletion,
    JinjaCompletionItem,
    JinjaScope,
    jinja_completion,
)
from tests._xprompt_directive_completion_parity_lsp_session import LspSession

_CURSOR = "▮"

_PROMPT_HEAD = """\
---
input:
  - name: topic
    type: line
    description: What to research.
  - name: count
    type: int
    default: "3"
---
%repeat:3
{% set greeting = "hello" %}
{% for item in items %}
"""

_PROMPT_TAIL = """\
{% endfor %}
"""

_PROMPT_CURSORS = {
    "variables": "{{ ",
    "prefixed": "{{ pa",
    "filters": "{{ topic | ",
    "tests": "{{ topic is ",
    # ``loop`` (not ``wait``): this fixture declares ``input:``, where run-time
    # names such as ``wait`` are hidden on both surfaces. ``loop`` is live
    # inside the fixture's ``{% for %}`` body.
    "members": "{{ loop.",
    "statements": "{% ",
}

_INPUT_DECLARING_DOC = """\
---
input:
  - name: topic
    type: line
    description: What to research.
---
Write about {{ ▮ }}.
"""

_XPROMPT_SKILL_DOC = """\
---
skill: true
input:
  - name: prompt
    type: text
    description: What to render.
---
Render {{ ▮ }} with _1.
"""

_LIFTED_YAML = """\
input:
  - name: topic
    type: line
    description: What to research.
"""

_LIFTED_BODY_CURSORS = {
    "lifted-variables": "Write about {{ ▮ }}.\n",
    "lifted-prefixed": "Write about {{ to▮ }}.\n",
}

# Names the engine must hide in an input-declaring prompt: the launch
# renders such prompts through ``render_prompt_with_inputs`` before any
# agent run exists, so run-time names are undefined there.
_RUN_NAMES = frozenset(
    {
        "wait",
        "patch_name",
        "workspace_num",
        "cl_name",
        "n",
        "N",
        "agents",
        "wait_chats",
    }
)

# LSP ``CompletionItemKind`` numbers for the engine's item kinds.
_EXPECTED_KINDS = {
    "variable": 6,  # VARIABLE
    "member": 5,  # FIELD
    "function": 3,  # FUNCTION
    "filter": 3,  # FUNCTION
    "test": 3,  # FUNCTION
    "keyword": 14,  # KEYWORD
}

_EXPECTED_SOURCE_BASE = {
    "local": "local",
    "sase": "sase",
    "positional": "arg",
    "provider": "skill",
    "jinja": "jinja",
}


def _split_cursor(document: str) -> tuple[str, int]:
    """Remove the cursor marker, returning ``(text, python_offset)``."""
    assert document.count(_CURSOR) == 1
    offset = document.index(_CURSOR)
    return document.replace(_CURSOR, ""), offset


def _offset_to_cursor(text: str, offset: int) -> tuple[int, int]:
    """Convert a Python offset to an ACE-style ``(row, column)`` pair."""
    row = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return row, offset - line_start


def _expected_description(item: JinjaCompletionItem) -> str:
    """Mirror the LSP's source/availability label for one adapter item."""
    if item.source == "input":
        base = "input · required" if item.required else "input"
    else:
        base = _EXPECTED_SOURCE_BASE[item.source]
    if item.availability.state == "conditional":
        hint = item.availability.hint or ""
        if "%repeat" in hint:
            return f"{base} · needs %repeat"
        if "%wait" in hint:
            return f"{base} · needs %wait"
        return f"{base} · conditional"
    if item.closes is not None:
        return f"closes {item.closes}"
    if item.legacy_for is not None:
        return f"{base} · legacy"
    return base


def _expected_type_detail(item: JinjaCompletionItem) -> str | None:
    text = item.signature or item.type_label
    return f" {text}" if text else None


def _assert_lsp_matches_adapter(
    adapter: JinjaCompletion | None,
    lsp_raw: list[dict[str, Any]],
) -> None:
    """Assert one LSP completion list equals one adapter completion."""
    assert adapter is not None, "adapter left the tag (expected in-tag)"
    ordered = sorted(lsp_raw, key=lambda item: str(item.get("sortText") or ""))
    assert [item.get("label") for item in ordered] == [
        item.name for item in adapter.items
    ]
    for lsp_item, adapter_item in zip(ordered, adapter.items, strict=True):
        label_details = lsp_item.get("labelDetails")
        assert isinstance(label_details, dict)
        assert lsp_item.get("kind") == _EXPECTED_KINDS[adapter_item.kind]
        assert label_details.get("detail") == _expected_type_detail(adapter_item)
        assert label_details.get("description") == _expected_description(adapter_item)
        assert lsp_item.get("detail") == adapter_item.summary
        documentation = lsp_item.get("documentation")
        assert isinstance(documentation, dict)
        assert documentation.get("value") == adapter_item.documentation
        text_edit = lsp_item.get("textEdit")
        assert isinstance(text_edit, dict)
        assert text_edit.get("newText") == adapter_item.insertion
        assert str(lsp_item.get("sortText")) == f"{adapter_item.rank:04}"
        assert lsp_item.get("filterText") == adapter_item.name
        if adapter_item.legacy_for is not None:
            assert lsp_item.get("tags") == [1]  # DEPRECATED
    if ordered:
        assert ordered[0].get("preselect") is True


def _lsp_raw_items(session: LspSession, text: str, offset: int) -> list[dict[str, Any]]:
    rows = session.complete_list(text, cursor=_offset_to_cursor(text, offset))
    return [row.raw for row in rows.items if isinstance(row.raw, dict)]


def _adapter_completion(
    text: str, offset: int, scope: JinjaScope
) -> JinjaCompletion | None:
    return jinja_completion(text, offset, scope)


def _check_parity(
    tmp_path: Path,
    text: str,
    offset: int,
    scope: JinjaScope,
    *,
    uri: str | None = None,
    language_id: str = "sase",
) -> JinjaCompletion:
    adapter = _adapter_completion(text, offset, scope)
    with LspSession(tmp_path, uri=uri, language_id=language_id) as lsp:
        lsp_raw = _lsp_raw_items(lsp, text, offset)
    _assert_lsp_matches_adapter(adapter, lsp_raw)
    assert adapter is not None
    return adapter


def test_prompt_fixture_cursors_match_lsp(
    tmp_path: Path,
) -> None:
    scope = JinjaScope("prompt", None)
    for name, cursor_line in _PROMPT_CURSORS.items():
        document = f"{_PROMPT_HEAD}{cursor_line}{_CURSOR}{_PROMPT_TAIL}"
        text, offset = _split_cursor(document)
        adapter = _check_parity(tmp_path, text, offset, scope)
        assert adapter.items, f"{name}: expected candidates on both surfaces"


def test_input_declaring_prompt_hides_run_names(tmp_path: Path) -> None:
    text, offset = _split_cursor(_INPUT_DECLARING_DOC)
    adapter = _check_parity(tmp_path, text, offset, JinjaScope("prompt", None))
    names = {item.name for item in adapter.items}
    assert names.isdisjoint(_RUN_NAMES)
    assert {"topic", "root"} <= names


def test_xprompt_skill_path_matches_lsp(tmp_path: Path) -> None:
    uri = (tmp_path / "xprompts" / "skill.md").as_uri()
    text, offset = _split_cursor(_XPROMPT_SKILL_DOC)
    adapter = _check_parity(
        tmp_path,
        text,
        offset,
        JinjaScope("xprompt", None),
        uri=uri,
        language_id="markdown",
    )
    names = {item.name for item in adapter.items}
    assert "_args" in names
    assert "provider_name" in names


def test_lifted_frontmatter_matches_inline_document(tmp_path: Path) -> None:
    for name, body_line in _LIFTED_BODY_CURSORS.items():
        body, body_offset = _split_cursor(body_line)
        full = f"---\n{_LIFTED_YAML}---\n{body}"
        full_offset = len(f"---\n{_LIFTED_YAML}---\n") + body_offset
        adapter = jinja_completion(
            body, body_offset, JinjaScope("prompt", _LIFTED_YAML)
        )
        with LspSession(tmp_path) as lsp:
            lsp_raw = _lsp_raw_items(lsp, full, full_offset)
        _assert_lsp_matches_adapter(adapter, lsp_raw)
        assert adapter is not None and adapter.items, name
