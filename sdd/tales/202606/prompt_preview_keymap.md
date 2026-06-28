---
create_time: 2026-06-28 09:47:57
status: done
prompt: sdd/prompts/202606/prompt_preview_keymap.md
---
# Plan: `K` Preview Keymap for the Prompt Input Widget

## 1. Goal & Product Context

Add a new normal-mode `K` keymap to the `sase ace` prompt input widget (`PromptTextArea`) that **previews the xprompt,
xprompt skill, or file path under the cursor** in a dedicated, beautiful, syntax-highlighted, scrollable panel.

Why `K`? In vim, `K` runs `keywordprg` — it looks up the keyword under the cursor (e.g. opens the man page). So `K` =
"look up / preview the thing under the cursor" is the idiomatic, discoverable choice. This keeps muscle memory intact
for vim users and matches the widget's existing vim-faithful normal mode.

### Behavior contract

When the user presses `K` in normal mode in the prompt input:

1. **Cursor on an xprompt reference (`#foo`, `#foo:arg`, `#proj/foo`) that resolves** → open the preview panel showing
   the xprompt's definition (front matter + body) with markdown/YAML syntax highlighting. The panel header labels it as
   an **xprompt** (or **skill** when the resolved xprompt has `skill: true`, or **workflow** when it resolves to a
   workflow).
2. **Cursor on a file path (`@path`, `path/to/file.ext`, `~/x`, `./x`, `.sase/x`) that exists** → open the preview panel
   showing the file contents with extension-based syntax highlighting.
3. **Cursor on a previewable token, but it does NOT exist** (unknown xprompt name, missing file) → show a **distinct,
   specific** toast (e.g. `No xprompt or skill named '#foo' found` / `File not found: path/to/file.ext`). No panel
   opens.
4. **Cursor is not on any previewable token** → show a helpful toast
   (`Move the cursor onto an xprompt, skill, or file path to preview it`). No panel opens.

The preview panel must be scrollable with `Ctrl+D` / `Ctrl+U` (half-page, vim-style) and dismissable with `Esc` / `q`.

### Design principles for this feature

- **Intuitive:** idiomatic `K`; clear, distinct error messages; the panel header states exactly _what_ is being
  previewed and _where it lives on disk_.
- **Reliable:** resolution reuses the codebase's existing, battle-tested xprompt and file-path resolvers (no new
  parallel logic); large/binary content is handled gracefully via the existing capped renderer; pure-presentation modal
  is trivially unit/snapshot testable.
- **Beautiful:** matches the existing modal visual language (thick `$primary` border, `$surface` background, dim accent
  header rule, monokai syntax theme, line numbers, footer hint line), validated by a PNG visual snapshot.

## 2. Architecture & Boundary Decision

### Rust core boundary (`rust_core_backend_boundary`)

The repo's boundary rule says shared backend/domain behavior belongs in `../sase-core`. The litmus test: _would another
frontend (web/CLI/editor) need this to match the TUI?_

This feature splits cleanly:

- **Token resolution** ("what is this token, and where does its definition live?") _reuses existing Python domain logic_
  — `iter_xprompt_references()`, `get_xprompt_or_workflow()`, and the file-path resolver. The entire xprompt
  parsing/resolution subsystem already lives in Python today (the Rust side only ships a separate `sase-xprompt-lsp` for
  editor completion; it is **not** the source of truth for xprompt resolution in this app). This feature therefore
  **does not reimplement core logic** and does **not** introduce new backend domain behavior — it composes existing
  resolvers behind a thin presentation adapter.
- **Preview presentation** (token-under-cursor detection from the editor buffer, the modal, syntax highlighting,
  scrolling, layout, theming) is unambiguously presentation and stays in this repo / Textual.

**Decision:** implement entirely in this repo, reusing existing Python resolvers; do **not** push resolution into
`sase-core`. Rationale: xprompt resolution is not in Rust yet, so relocating it would be a large, separate effort far
beyond this UI feature, and would duplicate logic that is currently Python's responsibility. _(Flagging this explicitly
for review — if the preference is to seed token resolution in `sase-core` now, that is a distinct, larger workstream and
should be scoped separately.)_

### Component overview

```
PromptTextArea  (normal mode)
  │  presses K
  ▼
_handle_normal_mode_key()              # _vim_normal.py — intercept K early (like `/`)
  │
  ▼
_preview_token_under_cursor()          # NEW mixin method on PromptTextArea
  │  1. detect token under cursor      ──►  detect_preview_target_at_cursor()   [NEW, syntactic only]
  │  2. resolve to content + metadata  ──►  resolve_preview_target()            [NEW, reuses existing resolvers]
  │  3a. None / error  → self.notify(...)  (distinct messages)
  │  3b. success       → self.app.push_screen(PreviewPanelModal(payload))
  ▼
PreviewPanelModal(ModalScreen[None])   # NEW — dumb, presentational, snapshot-tested
  • header: icon + kind badge + name + source path
  • VerticalScroll(#preview-scroll) → Static(lazy_renderable(content, lexer))
  • footer hint; Ctrl+D/U scroll, Esc/q close
```

The split between **syntactic detection** and **resolution** is deliberate: detection tells us "the cursor is on `#foo`"
even when `#foo` does not resolve, which is exactly what lets us emit the _distinct_ "does not exist" error (requirement
#3) instead of the generic "nothing here" error (requirement #4).

## 3. Implementation Plan

### 3.1 Token detection + resolution helper (new module)

New module `src/sase/ace/tui/widgets/_prompt_preview_target.py` (presentation-adjacent, lives with the prompt widget
mixins). Two layers:

**Layer A — syntactic detection (no disk access, no catalog lookup):**

```
@dataclass(frozen=True)
class PreviewToken:
    kind: Literal["xprompt", "file"]
    raw: str        # exact text span, e.g. "#foo:bar" or "@src/x.py"
    target: str     # xprompt name "foo" / "proj/foo", or file path "src/x.py"
    start: int
    end: int

def detect_preview_target_at_cursor(text: str, cursor_offset: int) -> PreviewToken | None
```

- xprompt: iterate `iter_xprompt_references(text)`; return the reference whose span `[start, end)` contains
  `cursor_offset`, as `kind="xprompt"`, `target=ref.name`. (Cursor anywhere within the whole reference — name or args —
  previews the xprompt.)
- file: use the existing `_FILE_PATH_RE` from `prompt_panel/_file_path_hints.py` (handles `@`-prefix, absolute, `~`,
  `./`, `../`, `.sase/...`, and `dir/file.ext`). Return the match whose path span contains the cursor as `kind="file"`,
  `target=group(2)` (path without `@`).
- xprompt detection takes precedence (the `#` marker is unambiguous and cannot overlap a file path). Return `None` when
  the cursor is on neither.

**Layer B — resolution (reuses existing resolvers; the only place that touches disk/catalog):**

```
@dataclass(frozen=True)
class PreviewPayload:
    kind_label: str       # "xprompt" | "skill" | "workflow" | "file"
    icon: str             # e.g. "#" badge for xprompt, file glyph for file
    title: str            # "#foo" or "src/x.py"
    source_path: str | None   # absolute path shown dim in header
    content: str
    lexer: str            # for lazy_renderable / Syntax

class PreviewError(Exception):
    """Carries a user-facing message + severity for the toast."""

def resolve_preview_target(token, *, project: str | None, base_dir: str) -> PreviewPayload
```

- **xprompt/skill/workflow:** `obj = get_xprompt_or_workflow(token.target, project)`.
  - `None` → raise `PreviewError("No xprompt or skill named '#<name>' found")` _(distinct "does not exist" message —
    requirement #3)._
  - Otherwise, **prefer reading the on-disk source file** (`obj.source_path`) when it is a real existing file: this
    gives the most faithful preview (full front matter + body) and a correct lexer from the file extension (`.md` →
    markdown, `.yml`/`.yaml` → yaml).
  - Fall back to in-memory content when `source_path` is not a readable file (e.g. xprompts defined inline in
    `sase.yml`, whose `source_path == "config"`): use `XPrompt.content` (or `Workflow.get_prompt_part_content()` / a
    structured workflow preview mirroring `xprompt_select_modal._create_workflow_preview`) with the `markdown` lexer.
  - `kind_label` = `"skill"` when `XPrompt.skill` is truthy, `"workflow"` for a `Workflow`, else `"xprompt"`.
- **file:** `resolved = _resolve_file_path(token.target, base_dir)` (reuse existing helper).
  - missing → `PreviewError("File not found: <path>")` _(distinct message — requirement #3)._
  - directory → `PreviewError("'<path>' is a directory, not a file")` _(v1; directory listing is a possible later
    enhancement)._
  - binary (null-byte sniff on a bounded read) → `PreviewError("Cannot preview binary file: <path>")`.
  - else read the file (bounded read for very large files; `lazy_renderable` additionally caps highlighting). lexer via
    the existing extension→lexer map (`file_panel/_messages.py:_EXTENSION_TO_LEXER`, default `"text"`).

`base_dir` (for relative file paths) = the directory `sase ace` was launched from / the current project root, obtained
from `self._ace_app`. _(Implementation note: confirm the exact accessor on `AceApp` for the launch cwd / project root;
relative file previews resolve against it. Absolute and `~` paths ignore `base_dir`.)_

### 3.2 Wire the `K` key (normal mode)

In `src/sase/ace/tui/widgets/_vim_normal.py`, `_handle_normal_mode_key`, intercept `K` **right after the `/`,`?` search
block and before the dot-repeat mutation-buffer append** (so `K` is never recorded for `.` repeat — it is a command, not
a mutation), gated by the existing top-level predicate so multi-key sequences still treat `K` as literal data:

```
if key == "K" and self._can_start_prompt_search_from_normal_key():
    self._preview_token_under_cursor()
    return True
```

The `_can_start_prompt_search_from_normal_key()` guard ensures `K` only triggers as a fresh top-level command. While a
pending operator/motion/replace is active (`fK`, `dtK`, `rK`, surround targets, etc.), the guard is false, so `K` falls
through to the pending handler as a literal character — preserving existing behavior. (A count prefix like `2K` is
treated the same as `2/` today and is a no-op; acceptable, and called out in tests.)

### 3.3 Widget action method

Add `_preview_token_under_cursor()` to the prompt widget — a new small mixin `PromptPreviewMixin` in
`src/sase/ace/tui/widgets/_prompt_preview.py`, mixed into `PromptTextArea` (alongside the other mixins listed in
`prompt_text_area.py`). It:

1. `offset = self._absolute_offset(self.cursor_location)`.
2. `token = detect_preview_target_at_cursor(self.text, offset)`; if `None` →
   `self.notify("Move the cursor onto an xprompt, skill, or file path to preview it", severity="warning")`; return.
3. `try: payload = resolve_preview_target(token, project=<proj>, base_dir=<cwd>)`
   `except PreviewError as e: self.notify(str(e), severity="warning"); return`.
4. `self.app.push_screen(PreviewPanelModal(payload))`.

Keep resolution (disk/catalog) in the action, so the modal stays pure/presentational.

### 3.4 The preview modal (new)

New `src/sase/ace/tui/modals/preview_panel_modal.py`: `class PreviewPanelModal(ModalScreen[None])`, modeled on
`activity_modal.py` and the preview pane of `xprompt_select_modal.py`.

- `__init__(self, payload: PreviewPayload)` — stores the already-resolved payload (no disk access in the modal →
  trivially testable + deterministic snapshots).
- `compose()`:
  - `Container(id="preview-modal-container")`
    - `Static(header, id="preview-title")` — icon + kind badge + `title`, with `source_path` rendered dim on a second
      line (Rich `Text`, matching the activity modal's header styling vocabulary).
    - `VerticalScroll(id="preview-scroll")` → `Static(renderable, id="preview-content")` where
      `renderable = lazy_renderable(payload.content, payload.lexer, line_numbers=True, theme="monokai", render_cache=<modal-owned cache>)`.
    - `Static("Ctrl+D/U scroll • g/G top/bottom • Esc/q close", id="preview-footer")`.
- `BINDINGS`: `escape`/`q` → `close`; `ctrl+d`/`ctrl+u` → half-page scroll (same `scrollable_content_region.height // 2`
  pattern as `activity_modal`); plus `j`/`k` (line scroll) and `g`/`G` (top/bottom) for a polished vim-flavored viewer.
- Actions: `action_close`, `action_scroll_down`, `action_scroll_up`, `action_scroll_top`, `action_scroll_bottom`.

### 3.5 Styling

Add a `PreviewPanelModal` block to `src/sase/ace/tui/styles.tcss`, matching the existing modal idiom
(`border: thick $primary; background: $surface; padding: 1 2;`). Size it larger than the activity modal since it shows
file contents — e.g. `width: 85%; height: 85%; max-width/height` — with
`#preview-scroll { height: 1fr; scrollbar-gutter: stable; border: solid $secondary; }` and dim styling for the
source-path line and footer. Goal: visually consistent with existing panels while giving content room to breathe.

## 4. Testing

1. **Unit — detection** (`tests/.../test_prompt_preview_target_detection.py`): cursor on `#foo`, on `#foo:arg` (name and
   args region), on `#proj/foo`, on `@path`, on bare `dir/file.ext`, on `~/x`; cursor at span boundaries; cursor in
   plain prose → `None`; xprompt-vs-file precedence.
2. **Unit — resolution** (`tests/.../test_prompt_preview_target_resolve.py`): xprompt found (reads source file, markdown
   lexer), skill (`skill: true` → `kind_label == "skill"`), workflow, inline/config xprompt fallback to in-memory
   content, missing xprompt → `PreviewError` with the distinct message; file found (extension→lexer), file missing →
   distinct `PreviewError`, directory → `PreviewError`, binary → `PreviewError`.
3. **Keymap / widget behavior** (new `tests/.../test_prompt_normal_mode_preview.py`, in the style of the existing
   `test_prompt_normal_mode_*.py`):
   - `K` with cursor on a resolvable token pushes `PreviewPanelModal`.
   - `K` with cursor on nothing emits the "move the cursor…" toast and pushes no screen.
   - `K` with cursor on a non-existent `#foo` / missing file emits the _distinct_ toast.
   - **Regression:** `K` is still literal data inside `fK`, `dtK`, `rK`, and surround targets (extend
     `test_prompt_normal_mode_char_search.py` / surround tests).
   - `K` does not become a `.`-repeatable mutation (dot-repeat unaffected).
4. **Modal scrolling**: `Ctrl+D`/`Ctrl+U` (and `g`/`G`) move the scroll offset; `Esc`/`q` dismiss.
5. **Visual PNG snapshot** (`tests/ace/tui/visual/test_ace_png_snapshots_preview.py`, using the `AcePage` +
   `ace_png_visual` fixtures): one snapshot for an xprompt preview and one for a file preview, asserting the panel
   renders with header, highlighted body, and footer. Regenerate goldens with `--sase-update-visual-snapshots`.

## 5. Docs / Help / Config Sync (repo conventions)

- **Help popup (`?`)** — _required by `src/sase/ace/AGENTS.md` ("Help Popup Maintenance": any `sase ace` option change
  MUST update the help popup)._ Add `K` (preview xprompt/skill/file under cursor) to the appropriate normal-mode /
  prompt-input section of the help modal (`src/sase/ace/tui/modals/help_modal/`). Respect the documented 57-char box
  width / 32-char description constraints.
- **Footer** (`keybinding_footer.py`) — the footer surfaces conditional keymaps for the selected **Agents/ChangeSpec
  entry**, not prompt-input normal-mode keys, so `K` likely does **not** belong there. Confirm during implementation;
  _optionally_ surface a "K preview" hint in any existing prompt-bar hint line when a previewable token is under the
  cursor (nice-to-have for discoverability).
- **`default_config.yml`** — normal-mode keys are **hardcoded in Python**, not configurable via YAML (confirmed: only
  app-level keymaps live in `default_config.yml`). So **no config change is needed**; `K` stays hardcoded to match every
  other normal-mode key. (Explicitly noting this so the implementer does not go looking — the `gotchas` "Default Keymap
  Config" rule applies only to configurable app-level keymaps.)

## 6. Out of Scope / Possible Follow-ups

- Previewing a directory (render a listing) — v1 errors on directories.
- Previewing from **visual** mode using the active selection — v1 is normal-mode + cursor.
- Pushing token classification/resolution into `sase-core` for cross-frontend reuse — a separate, larger workstream (see
  boundary decision in §2).
- Inline "jump to definition" (open the source file in `$EDITOR`) from the preview panel.

## 7. Files Touched (summary)

New:

- `src/sase/ace/tui/widgets/_prompt_preview_target.py` (detection + resolution)
- `src/sase/ace/tui/widgets/_prompt_preview.py` (`PromptPreviewMixin` + action)
- `src/sase/ace/tui/modals/preview_panel_modal.py` (`PreviewPanelModal`)
- Tests: detection, resolution, keymap behavior, visual snapshot

Modified:

- `src/sase/ace/tui/widgets/_vim_normal.py` (intercept `K`)
- `src/sase/ace/tui/widgets/prompt_text_area.py` (mix in `PromptPreviewMixin`)
- `src/sase/ace/tui/styles.tcss` (modal styling)
- `src/sase/ace/tui/modals/help_modal/` (document `K`)

## 8. Validation

Run `just install` then `just check` (lint + mypy + tests) and `just test-visual` for the new PNG snapshot. The change
is presentation-layer Python + Textual, so no `sase-core` changes are expected.
