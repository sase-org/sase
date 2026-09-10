"""Installed-binary ACE/LSP parity for equals model shortcuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.widgets.model_alias_completion import (
    build_model_alias_completion_candidates,
    detect_model_alias_completion_context,
    plan_model_alias_completion_edit,
)
from sase.ace.tui.widgets.model_explicit_completion import (
    build_model_explicit_completion_candidates,
    detect_model_explicit_completion_context,
    plan_model_explicit_completion_edit,
)
from sase.xprompt.model_completion import (
    ModelCompletionEntry,
    model_completion_entry_to_wire,
)
from tests._xprompt_directive_completion_parity_lsp import (
    LspSession,
    apply_lsp_text_edit,
)

PARITY_ENTRIES: tuple[ModelCompletionEntry, ...] = (
    ModelCompletionEntry(
        value="opus",
        display="opus",
        description="Claude",
        kind="model",
        provider="claude",
        aliases=("opus",),
    ),
    ModelCompletionEntry(
        value="claude-fable-5",
        display="claude-fable-5",
        description="Claude (fable)",
        kind="model",
        provider="claude",
        aliases=("fable",),
    ),
    ModelCompletionEntry(
        value="@large",
        display="@large",
        description="Large pool",
        kind="user_alias",
        aliases=("large",),
        alias_kind="user",
        target_provider="claude",
        target_model="opus",
        target_effort="high",
        provenance="configured",
    ),
    ModelCompletionEntry(
        value="@launch",
        display="@launch",
        description="Launch alias",
        kind="implicit_alias",
        aliases=("launch",),
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5",
        provenance="implicit",
    ),
    ModelCompletionEntry(
        value="large-model",
        display="large-model",
        description="Concrete model",
        kind="model",
        provider="codex",
        aliases=("large",),
    ),
    ModelCompletionEntry(
        value="@scout",
        display="@scout",
        description="Scout alias",
        kind="user_alias",
        aliases=("scout",),
        alias_kind="user",
        target_provider="claude",
        target_model="opus",
        provenance="configured",
    ),
    ModelCompletionEntry(
        value="@small",
        display="@small",
        kind="implicit_alias",
        aliases=("small",),
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5-mini",
        provenance="implicit",
    ),
    ModelCompletionEntry(
        value="claude/",
        display="claude/",
        description="Claude",
        kind="provider",
        provider="claude",
    ),
    ModelCompletionEntry(
        value="codex/",
        display="codex/",
        description="Codex",
        kind="provider",
        provider="codex",
    ),
)

_PROTECTED_EQUALS = (
    ("a=la", (0, 4)),
    ("path/=la", (0, 8)),
    (r"\=la", (0, 4)),
    ("`=la`", (0, 3)),
    ("```\n=la", (1, 3)),
    ("%model:=la", (0, 10)),
    ("{{ =la }}", (0, 6)),
    ("{% if =la %}", (0, 9)),
    ("---\nname: =la\n---\nbody", (1, 9)),
)
_PROTECTED_DOUBLE_EQUALS = (
    ("a==la", (0, 5)),
    ("path/==la", (0, 9)),
    (r"\==la", (0, 5)),
    ("`==la`", (0, 4)),
    ("```\n==la", (1, 4)),
    ("%model:==la", (0, 11)),
    ("{{ ==la }}", (0, 7)),
    ("{% if ==la %}", (0, 10)),
    ("---\nname: ==la\n---\nbody", (1, 10)),
    ("===la", (0, 5)),
    ("==bold==", (0, 4)),
)


def _parity_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entries": [model_completion_entry_to_wire(entry) for entry in PARITY_ENTRIES],
    }


def _parity_session(tmp_path: Path, **kwargs: Any) -> LspSession:
    return LspSession(tmp_path, model_catalog=_parity_catalog_payload(), **kwargs)


def _ace_alias_names(text: str, cursor: tuple[int, int]) -> list[str]:
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    return [
        candidate.insertion
        for candidate in build_model_alias_completion_candidates(
            context, PARITY_ENTRIES
        )
    ]


def _ace_plan(text: str, cursor: tuple[int, int], alias: str) -> Any:
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    selected = next(
        candidate
        for candidate in build_model_alias_completion_candidates(
            context, PARITY_ENTRIES
        )
        if candidate.insertion == alias
    )
    planned = plan_model_alias_completion_edit(text, cursor, PARITY_ENTRIES, selected)
    assert planned is not None
    return planned


def _ace_model_names(text: str, cursor: tuple[int, int]) -> list[str]:
    context = detect_model_explicit_completion_context(text, cursor)
    assert context is not None
    return [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            context, PARITY_ENTRIES
        )
    ]


def _ace_model_plan(text: str, cursor: tuple[int, int], model: str) -> Any:
    context = detect_model_explicit_completion_context(text, cursor)
    assert context is not None
    selected = next(
        candidate
        for candidate in build_model_explicit_completion_candidates(
            context, PARITY_ENTRIES
        )
        if candidate.insertion == model
    )
    planned = plan_model_explicit_completion_edit(
        text,
        cursor,
        PARITY_ENTRIES,
        selected,
    )
    assert planned is not None
    return planned


def test_lsp_advertises_equals_trigger_character(tmp_path: Path) -> None:
    with _parity_session(tmp_path) as lsp:
        assert "=" in lsp.trigger_characters
        assert "*" not in lsp.trigger_characters


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    [
        ("=", (0, 1), ["@large", "@launch", "@scout", "@small"]),
        ("=la", (0, 3), ["@large", "@launch"]),
        ("=LA", (0, 3), ["@large", "@launch"]),
        ("Use =la", (0, 7), ["@large", "@launch"]),
        ("first\nnext =SM", (1, 8), ["@small"]),
        ("  =scout", (0, 8), ["@scout"]),
    ],
)
def test_ace_and_lsp_equals_alias_names_and_order_match(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
    expected: list[str],
) -> None:
    context = detect_model_alias_completion_context(text, cursor)
    assert context is not None
    ace_names = [
        candidate.insertion
        for candidate in build_model_alias_completion_candidates(
            context, PARITY_ENTRIES
        )
    ]
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    lsp_names = [item.label for item in result.items]
    assert ace_names == expected
    assert lsp_names == expected
    assert result.is_incomplete is True
    assert "opus" not in lsp_names
    assert "large-model" not in lsp_names
    assert "claude/" not in lsp_names
    for item in result.items:
        raw = item.raw or {}
        assert raw.get("filterText") == f"={context.query}"


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    [
        ("==", (0, 2), ["opus", "claude-fable-5", "large-model"]),
        ("==la", (0, 4), ["large-model"]),
        ("==FA", (0, 4), ["claude-fable-5"]),
        ("Use ==la", (0, 8), ["large-model"]),
        ("first\nnext ==op", (1, 9), ["opus"]),
        ("  ==fable", (0, 9), ["claude-fable-5"]),
        ("==claude/fa", (0, 11), ["claude/claude-fable-5"]),
        ("==codex/la", (0, 10), ["codex/large-model"]),
    ],
)
def test_ace_and_lsp_double_equals_model_names_and_order_match(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
    expected: list[str],
) -> None:
    context = detect_model_explicit_completion_context(text, cursor)
    assert context is not None
    ace_names = [
        candidate.insertion
        for candidate in build_model_explicit_completion_candidates(
            context, PARITY_ENTRIES
        )
    ]
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    lsp_names = [item.label for item in result.items]
    assert ace_names == expected
    assert lsp_names == expected
    assert result.is_incomplete is True
    assert "@large" not in lsp_names
    assert "@launch" not in lsp_names
    assert "claude/" not in lsp_names
    assert "codex/" not in lsp_names
    for item in result.items:
        raw = item.raw or {}
        assert raw.get("filterText") == f"=={context.query}"


def test_ace_and_lsp_equals_alias_filter_text_preselect_and_expansion(
    tmp_path: Path,
) -> None:
    text = "=la"
    cursor = (0, 3)
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    assert result.is_incomplete is True
    assert [item.label for item in result.items] == ["@large", "@launch"]
    first = result.items[0].raw or {}
    second = result.items[1].raw or {}
    assert first.get("preselect") is True
    assert second.get("preselect") in {None, False}
    assert first.get("filterText") == "=la"
    assert second.get("filterText") == "=la"
    assert first.get("sortText") == "0000"
    assert second.get("sortText") == "0001"
    first_details = first.get("labelDetails") or {}
    assert first_details.get("detail") == " → %m:@large"
    assert "documentation" in first


def test_ace_and_lsp_double_equals_model_filter_text_preselect_and_expansion(
    tmp_path: Path,
) -> None:
    text = "==fa"
    cursor = (0, 4)
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    assert result.is_incomplete is True
    assert [item.label for item in result.items] == ["claude-fable-5"]
    first = result.items[0].raw or {}
    assert first.get("preselect") is True
    assert first.get("filterText") == "==fa"
    assert first.get("sortText") == "0000"
    first_details = first.get("labelDetails") or {}
    assert first_details.get("detail") == " → %m:claude-fable-5"
    assert first.get("detail", "").startswith("%m:claude-fable-5")
    documentation = first.get("documentation") or {}
    assert "Expansion" in str(documentation.get("value") or "")


@pytest.mark.parametrize(
    ("text", "cursor", "alias"),
    [
        ("=", (0, 1), "@large"),
        ("Use =la", (0, 7), "@large"),
        ("Use =la now", (0, 7), "@large"),
        ("Use =la   now", (0, 7), "@large"),
        ("Use =la\tnow", (0, 7), "@large"),
        ("Use =la\nnow", (0, 7), "@large"),
        ("Explain =laX later", (0, 11), "@large"),
        ("first\nnext =SM", (1, 8), "@small"),
        ("Title\r\nUse =la\ttail", (1, 7), "@large"),
        ("🙂 =la\r\nnext", (0, 5), "@large"),
    ],
)
def test_ace_and_lsp_equals_alias_edits_match(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
    alias: str,
) -> None:
    planned = _ace_plan(text, cursor, alias)
    ace_text = (
        f"{text[: planned.replacement_start]}"
        f"{planned.replacement}"
        f"{text[planned.replacement_end :]}"
    )
    assert planned.caret_offset == planned.replacement_start + len(planned.replacement)

    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)
    item = next(row for row in result.items if row.label == alias)
    raw = item.raw or {}
    text_edit = raw.get("textEdit")
    assert isinstance(text_edit, dict)
    lsp_text, lsp_caret = apply_lsp_text_edit(text, text_edit)
    assert lsp_text == ace_text
    assert lsp_caret == planned.caret_offset


@pytest.mark.parametrize(
    ("text", "cursor", "model"),
    [
        ("==", (0, 2), "opus"),
        ("Use ==la", (0, 8), "large-model"),
        ("Use ==la now", (0, 8), "large-model"),
        ("Use ==la   now", (0, 8), "large-model"),
        ("Use ==la\tnow", (0, 8), "large-model"),
        ("Use ==la\nnow", (0, 8), "large-model"),
        ("Explain ==laX later", (0, 12), "large-model"),
        ("first\nnext ==op", (1, 9), "opus"),
        ("Title\r\nUse ==la\ttail", (1, 8), "large-model"),
        ("🙂 ==la\r\nnext", (0, 6), "large-model"),
        ("==claude/fa", (0, 11), "claude/claude-fable-5"),
    ],
)
def test_ace_and_lsp_double_equals_model_edits_match(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
    model: str,
) -> None:
    planned = _ace_model_plan(text, cursor, model)
    ace_text = (
        f"{text[: planned.replacement_start]}"
        f"{planned.replacement}"
        f"{text[planned.replacement_end :]}"
    )
    assert planned.caret_offset == planned.replacement_start + len(planned.replacement)

    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)
    item = next(row for row in result.items if row.label == model)
    raw = item.raw or {}
    text_edit = raw.get("textEdit")
    assert isinstance(text_edit, dict)
    lsp_text, lsp_caret = apply_lsp_text_edit(text, text_edit)
    assert lsp_text == ace_text
    assert lsp_caret == planned.caret_offset


def test_equals_alias_no_match_is_empty_incomplete_list(tmp_path: Path) -> None:
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list("=zzz", cursor=(0, 4))

    assert result.is_incomplete is True
    assert result.items == []
    assert detect_model_alias_completion_context("=zzz", (0, 4)) is not None
    assert _ace_alias_names("=zzz", (0, 4)) == []


def test_double_equals_model_no_match_is_empty_incomplete_list(tmp_path: Path) -> None:
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list("==zzz", cursor=(0, 5))

    assert result.is_incomplete is True
    assert result.items == []
    assert detect_model_explicit_completion_context("==zzz", (0, 5)) is not None
    assert _ace_model_names("==zzz", (0, 5)) == []


@pytest.mark.parametrize(("text", "cursor"), _PROTECTED_EQUALS)
def test_protected_equals_does_not_own_empty_shortcut_list(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
) -> None:
    assert detect_model_alias_completion_context(text, cursor) is None
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    assert not (
        result.is_incomplete and result.items == [] and isinstance(result.raw, dict)
    )
    for item in result.items:
        raw = item.raw or {}
        new_text = ""
        text_edit = raw.get("textEdit")
        if isinstance(text_edit, dict):
            new_text = str(text_edit.get("newText") or "")
        assert not str(raw.get("filterText") or "").startswith("=")
        assert not new_text.startswith("%m:@")


@pytest.mark.parametrize(("text", "cursor"), _PROTECTED_DOUBLE_EQUALS)
def test_protected_double_equals_does_not_own_empty_shortcut_list(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
) -> None:
    assert detect_model_explicit_completion_context(text, cursor) is None
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    assert not (
        result.is_incomplete and result.items == [] and isinstance(result.raw, dict)
    )
    for item in result.items:
        raw = item.raw or {}
        new_text = ""
        text_edit = raw.get("textEdit")
        if isinstance(text_edit, dict):
            new_text = str(text_edit.get("newText") or "")
        assert not str(raw.get("filterText") or "").startswith("==")
        assert not new_text.startswith("%m:large-model")


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("*la", (0, 3)),
        ("Use *la", (0, 7)),
        ("**la", (0, 4)),
        ("Use **la", (0, 8)),
    ],
)
def test_legacy_star_inputs_do_not_produce_model_shortcut_edits(
    tmp_path: Path,
    text: str,
    cursor: tuple[int, int],
) -> None:
    assert detect_model_alias_completion_context(text, cursor) is None
    assert detect_model_explicit_completion_context(text, cursor) is None
    with _parity_session(tmp_path) as lsp:
        result = lsp.complete_list(text, cursor=cursor)

    for item in result.items:
        raw = item.raw or {}
        text_edit = raw.get("textEdit")
        if isinstance(text_edit, dict):
            assert not str(text_edit.get("newText") or "").startswith("%m:")


def test_missing_and_malformed_catalogs_stay_empty_shortcut(
    tmp_path: Path,
) -> None:
    with LspSession(tmp_path, omit_model_catalog=True) as lsp:
        missing_alias = lsp.complete_list("=la", cursor=(0, 3))
        missing_model = lsp.complete_list("==la", cursor=(0, 4))
    with LspSession(tmp_path, model_catalog_text="{not-json") as lsp:
        malformed_alias = lsp.complete_list("=la", cursor=(0, 3))
        malformed_model = lsp.complete_list("==la", cursor=(0, 4))

    assert missing_alias.is_incomplete is True
    assert missing_alias.items == []
    assert missing_model.is_incomplete is True
    assert missing_model.items == []
    assert malformed_alias.is_incomplete is True
    assert malformed_alias.items == []
    assert malformed_model.is_incomplete is True
    assert malformed_model.items == []


def test_ordinary_model_completion_still_includes_models_and_providers(
    tmp_path: Path,
) -> None:
    with _parity_session(tmp_path) as lsp:
        model_rows = lsp.complete("%model:")
        equals_rows = lsp.complete("=")

    model_labels = {row.label for row in model_rows}
    equals_labels = {row.label for row in equals_rows}
    assert {"opus", "claude-fable-5", "@large", "claude/", "codex/"} <= model_labels
    assert equals_labels == {"@large", "@launch", "@scout", "@small"}
    assert "opus" not in equals_labels
    assert "claude/" not in equals_labels
    assert "large-model" not in equals_labels
