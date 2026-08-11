"""Tests for prompt stack item, frontmatter, and source-binding models."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    SourceFingerprint,
    XPromptBinding,
    split_frontmatter,
)
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from tests.ace.tui.widgets._prompt_stack_helpers import (
    snippet_target as _snippet_target,
)


# --- split_frontmatter: public lift of leading frontmatter -----------------


def test_split_frontmatter_lifts_leading_block() -> None:
    frontmatter = "---\ndescription: hi\n---"
    raw, body = split_frontmatter(f"{frontmatter}\nbody text")
    assert raw == frontmatter
    assert body == "body text"


def test_split_frontmatter_returns_empty_when_absent() -> None:
    raw, body = split_frontmatter("no frontmatter here")
    assert raw == ""
    assert body == "no frontmatter here"


# --- structured frontmatter model wiring ----------------------------------


def test_frontmatter_model_parses_raw_string() -> None:
    state = PromptStackState.from_text("---\nname: x\ndescription: hi\n---\nbody")
    model = state.frontmatter_model
    assert model.name == "x"
    assert model.description == "hi"


def test_frontmatter_model_empty_when_no_frontmatter() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    assert state.frontmatter_model.is_empty


def test_set_frontmatter_model_writes_canonical_string() -> None:
    state = PromptStackState.from_text("seg1\n---\nseg2")
    model = PromptFrontmatter(name="x")
    model.set_input(InputArg(name="svc", type=InputType.WORD))
    state.set_frontmatter_model(model)
    assert state.frontmatter == "---\nname: x\ninput:\n  svc: word\n---"


def test_set_empty_frontmatter_model_clears_frontmatter() -> None:
    state = PromptStackState.from_text("---\nname: x\n---\nbody")
    state.set_frontmatter_model(PromptFrontmatter())
    assert state.frontmatter == ""
    # No stray delimiters leak into a whole-stack join.
    assert state.join() == "body"


def test_join_byte_stable_after_model_round_trip() -> None:
    """Reading then writing back the model leaves join() byte-identical."""
    text = "---\nname: x\ntags:\n- a\n- b\n---\nseg1\n---\nseg2"
    state = PromptStackState.from_text(text)
    before = state.join()
    state.set_frontmatter_model(state.frontmatter_model)
    assert state.join() == before


def test_attach_frontmatter_unchanged_after_model_edit() -> None:
    state = PromptStackState.from_text("---\nname: x\n---\nseg1\n---\nseg2")
    model = state.frontmatter_model
    model.description = "added"
    state.set_frontmatter_model(model)
    # attach_frontmatter still prepends the (now-updated) canonical block.
    assert state.attach_frontmatter("seg1") == (
        "---\nname: x\ndescription: added\n---\nseg1"
    )


# --- per-item editor state ------------------------------------------------


def test_item_defaults() -> None:
    item = PromptStackState.single("hi").selected_item
    assert item.mode == "insert"
    assert item.cursor == (0, 0)
    assert item.last_height is None


def test_reorder_preserves_item_editor_state() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    state.selected_item.cursor = (3, 7)
    state.selected_item.mode = "normal"
    state.move_selected(1)
    moved = state.selected_item
    assert moved.text == "a"
    assert moved.cursor == (3, 7)
    assert moved.mode == "normal"


def test_prompt_stack_item_is_constructible() -> None:
    item = PromptStackItem(text="t", item_id="p0")
    assert item.text == "t"
    assert item.item_id == "p0"


def test_snippet_target_accessors_and_dirty_state() -> None:
    state = PromptStackState.single("agent")
    target = _snippet_target(loaded_body="original")
    snippet = state.append_snippet_pane("original", target)

    assert state.snippet_item is snippet
    assert state.snippet_index == 1
    assert state.has_snippet_pane is True
    assert state.agent_count == 1
    assert state.snippet_is_dirty is False

    snippet.text = "changed"
    assert state.snippet_is_dirty is True


def test_retarget_snippet_pane_keeps_body() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("draft body", _snippet_target("old"))

    new_target = _snippet_target("new")
    state.retarget_snippet_pane(new_target)

    assert state.snippet_item is not None
    assert state.snippet_item.text == "draft body"
    assert state.snippet_item.snippet_target is new_target


def test_binding_dirty_and_external_change_detection(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    state = PromptStackState.from_text("body\n")
    state.bind(XPromptBinding.for_file(source))
    assert not state.is_dirty
    assert not state.source_changed()

    state.selected_item.text = "changed"
    assert state.is_dirty
    source.write_text("external\n", encoding="utf-8")
    assert state.source_changed()


def test_source_fingerprint_stat_signature_is_cheap_staleness_hint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    fingerprint = SourceFingerprint.from_path(source)

    assert SourceFingerprint.stat_signature(source) == (
        fingerprint.mtime_ns,
        fingerprint.size,
    )
    assert fingerprint.matches_stat(source)

    source.write_text("external\n", encoding="utf-8")
    assert not fingerprint.matches_stat(source)


def test_binding_uses_chezmoi_source_for_fingerprint_and_staleness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "xprompts" / "review.md"
    write_path = source_root / "sase" / "xprompts" / "review.md"
    read_path.parent.mkdir(parents=True)
    write_path.parent.mkdir(parents=True)
    read_path.write_text("applied\n", encoding="utf-8")
    write_path.write_text("body\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("sase.xprompt.write_targets.CHEZMOI_HOME", source_root)
    monkeypatch.setattr("sase.xprompt.write_targets.get_use_chezmoi", lambda: True)

    binding = XPromptBinding.for_file(read_path, reference="#review")
    state = PromptStackState.from_text("body\n")
    state.bind(binding)

    assert binding.path == str(read_path)
    assert binding.write_path == str(write_path)
    assert binding.apply_target == str(read_path)
    assert binding.via_chezmoi is True
    assert binding.reference == "#review"
    assert not state.source_changed()

    read_path.write_text("applied changed\n", encoding="utf-8")
    assert not state.source_changed()

    write_path.write_text("source changed\n", encoding="utf-8")
    assert state.source_changed()


def test_mark_written_refreshes_binding_and_clears_dirty(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    state = PromptStackState.from_text("body")
    state.bind(XPromptBinding.for_file(source))
    state.selected_item.text = "changed"
    source.write_text("changed\n", encoding="utf-8")
    state.mark_written()
    assert not state.is_dirty
    assert not state.source_changed()


def test_bound_markdown_preserves_untouched_body_bytes(tmp_path: Path) -> None:
    source_text = "---\ndescription: old\n---\n\n  body with spaces  \n"
    source = tmp_path / "review.md"
    source.write_text(source_text, encoding="utf-8")
    state = PromptStackState.from_text(source_text)
    state.bind(XPromptBinding.for_file(source), source_markdown=source_text)

    frontmatter = state.frontmatter_model
    frontmatter.description = "new"
    rewritten = state.markdown_preserving_unchanged_body(frontmatter)

    assert rewritten == "---\ndescription: new\n---\n\n  body with spaces  \n"
