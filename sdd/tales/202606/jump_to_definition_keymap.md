---
create_time: 2026-06-28 10:39:55
status: done
prompt: sdd/prompts/202606/jump_to_definition_keymap.md
---
# Plan: `Ctrl+]` Jump-to-Definition Keymap for the Prompt Input Widget

## 1. Goal & Product Context

Add a new normal-mode `Ctrl+]` keymap to the `sase ace` prompt input widget (`PromptTextArea`) that acts as
**jump-to-definition** for the **xprompt / xprompt skill / file path under the cursor**. Instead of jumping immediately,
it opens a small, beautiful **action menu** offering one-keypress ways to reach the target's definition.

Why `Ctrl+]`? In vim, `Ctrl+]` is the canonical _tag jump_ — "go to the definition of the thing under the cursor." It is
the most idiomatic, discoverable choice and complements the recently-added `K` (preview) keymap: `K` _looks at_ the
thing under the cursor; `Ctrl+]` _goes to_ it. This keeps muscle memory intact for vim users and matches the widget's
existing vim-faithful normal mode.

This feature is the natural sequel to the `K` preview keymap (`sdd/tales/202606/prompt_preview_keymap.md`). It **reuses
that feature's token detection and resolution machinery** wholesale and swaps the read-only preview panel for an
interactive action menu.

### Behavior contract

When the user presses `Ctrl+]` in normal mode in the prompt input:

1. **Cursor not on any xprompt/skill/file token** → a helpful warning toast
   (`Move the cursor onto an xprompt, skill, or file path to jump to its definition`). Nothing else happens.
2. **Cursor on a token that does NOT resolve** (unknown `#foo`, missing file, or an xprompt with no on-disk definition
   file) → a **distinct, specific** warning toast (`No xprompt or skill named '#foo' found` / `File not found: <path>` /
   `No definition file found for #foo`). No menu opens.
3. **Cursor on a resolvable token** → open the **jump action menu** (a small modal), offering the applicable actions,
   each selectable with a single keypress:
   - **`t` — Open in a new tmux pane** (split a vertical pane next to the TUI and launch `$EDITOR` on the definition).
     _Shown only when the TUI is running inside a tmux session._
   - **`e` — Open in this pane** (suspend the TUI, launch `$EDITOR` on the definition in the TUI's own terminal, resume
     on exit). _Always available when a definition file exists; this is the universal fallback._
   - **`l` — Load into the prompt input** (stash the whole current prompt bar as one bundle, then load the xprompt /
     skill into the bar for editing). _Shown only when the target is an xprompt/skill that can be represented as
     prompt-bar markdown — i.e. **not** a YAML-defined xprompt/workflow._
   - `Esc` / `q` cancels.
4. **Only one action is applicable** → **skip the menu entirely** and perform that single action directly (e.g. not in
   tmux + a plain file path → just open it in this pane). A one-item menu is noise.

**vim / nvim cursor positioning:** for _both_ editor-open actions (`t` and `e`), when `$EDITOR` is vim or nvim, the
cursor is positioned at the **correct line and column** of the definition (best-effort; see §4.6). Other editors simply
open the file. This is the "jump to the _right place_, not just the right file" polish.

### Design principles for this feature

- **Intuitive:** idiomatic `Ctrl+]`; mnemonic one-key actions (`t`mux / `e`ditor / `l`oad); distinct, specific error
  messages; the menu header states exactly _what_ the target is and _where its definition lives on disk_ (with `:line`).
- **Reliable:** detection and resolution reuse the battle-tested resolvers shared with the `K` preview feature
  (`detect_preview_target_at_cursor`, `get_xprompt_or_workflow`, the file-path resolver). The "is this a YAML xprompt?"
  gate reuses the codebase's own canonical predicate `is_yaml_backed_source`. The stash-then-load step reuses the
  existing, core-backed prompt-stash pipeline. Pure logic (detection, resolution, command building) is split from
  side-effects (subprocess/tmux/suspend) so it is trivially unit-testable.
- **Beautiful:** the action menu matches the existing single-key chooser visual language (the shared `duration-choice-*`
  modal styling used by `PromptSubmitChoiceModal`), with a crisp header badge + dim source path, validated by a PNG
  visual snapshot.

## 2. Architecture & Boundary Decision

### Rust core boundary (`rust_core_backend_boundary`)

The litmus test: _would another frontend (web/CLI/editor) need this to match the TUI?_

This feature is **presentation + local process orchestration**, and **reuses existing backend logic without adding new
backend domain behavior**:

- **Token detection & target resolution** (what is this token; where does its definition live; is it a loadable markdown
  xprompt) reuses existing Python domain logic — the same resolvers the `K` preview feature already composes
  (`iter_xprompt_references` / `detect_preview_target_at_cursor`, `get_xprompt_or_workflow`, `resolve_file_path`,
  `resolve_source_to_file_path`, `is_yaml_backed_source`). xprompt resolution lives in Python today; this feature does
  **not** reimplement or relocate it. _(Same boundary call as the `K` preview plan — flagged again here: seeding token
  resolution into `sase-core` is a separate, larger workstream and is out of scope.)_
- **Stash-then-load** reuses the existing prompt-stash pipeline, which **already** round-trips through the Rust
  `sase_core_rs` store via `prompt_stash_facade` (`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`). We
  add **no new wire/API** — we re-emit the existing `PromptInputBar.Stashed` message. No `sase-core` change.
- **Editor / tmux launching, menu, key handling, layout, theming** are unambiguously presentation / local-process glue
  and stay in this repo, matching existing patterns (`suspend_for_external_tool`, `tmux split-window`).

**Decision:** implement entirely in this repo; no `sase-core` changes expected.

### Component overview

```
PromptTextArea (normal mode)
  │  presses Ctrl+]   (Textual key name: "ctrl+right_square_bracket")
  ▼
_handle_normal_mode_key()                 # _vim_normal.py — intercept early (like K), gated to top-level command
  │
  ▼
_jump_to_definition_under_cursor()        # NEW mixin method (PromptJumpMixin), mirrors PromptPreviewMixin
  │  1. detect token under cursor    ──►  detect_jump_target_at_cursor()   [NEW; reuses preview detection + :line:col]
  │  2. resolve (worker thread)      ──►  resolve_jump_target()            [NEW; reuses existing resolvers]
  │  3a. None            → notify "move the cursor…"
  │  3b. JumpError       → notify distinct message
  │  3c. success         → build applicable actions; if 1 → run it; if >1 → push JumpActionModal
  ▼
JumpActionModal(ModalScreen[JumpChoice|None])  # NEW — dumb single-key chooser, snapshot-tested
  • header: icon + kind badge + title + dim source path (+ :line:col)
  • rows: t / e / l (only the applicable ones) ; footer hint ; esc/q close
  ▼
_perform_jump_action(choice, target)      # NEW — side-effecting; on the mixin
  • "tmux"   → open_in_tmux_pane(argv, cwd)         (tmux split-window -h)
  • "editor" → suspend_for_external_tool(...) + subprocess.run(argv)
  • "load"   → bar.stash_all_and_load_xprompt_markdown(markdown)
```

The split between **syntactic detection** and **resolution** is preserved from the preview feature: detection tells us
"the cursor is on `#foo`" even when `#foo` does not resolve, which is what lets us emit the _distinct_ "does not exist"
error (contract #2) instead of the generic "nothing here" error (contract #1).

### Reuse map (what already exists)

| Need                                                                             | Existing asset to reuse                                                                                                      |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Token-under-cursor detection (`#foo`, `@path`, `dir/f.ext`, `~/x`)               | `detect_preview_target_at_cursor` + `FILE_PATH_RE` (`widgets/_prompt_preview_target.py`, `prompt_panel/_file_path_hints.py`) |
| xprompt/workflow lookup                                                          | `get_xprompt_or_workflow` (`xprompt/loader.py`); `XPrompt` vs `Workflow` models                                              |
| "Is this xprompt defined in YAML?" gate                                          | `is_yaml_backed_source` (`modals/xprompt_browser_helpers.py`)                                                                |
| Source-id → real file path (incl. `config` → `~/.config/sase/sase.yml`)          | `resolve_source_to_file_path` (`modals/xprompt_browser_helpers.py`)                                                          |
| Relative file path → absolute                                                    | `resolve_file_path` (`prompt_panel/_file_path_hints.py`)                                                                     |
| Suspend TUI + telemetry to run an external editor                                | `suspend_for_external_tool` (`tui/util/external_tool.py`)                                                                    |
| Build `[editor] + files` argv                                                    | `build_editor_args` (`ace/hints.py`); robust editor pick `get_editor` (`workflows/commit/editor_utils.py`)                   |
| nvim cursor positioning precedent                                                | `tui/actions/agent_workflow/_editor.py` (`-c "call cursor(l, c)"`)                                                           |
| tmux session detection                                                           | `is_tmux_session` (`tui/graphics/_viewer_tmux_common.py`)                                                                    |
| tmux vertical split + run command pattern                                        | `tui/graphics/_viewer_tmux.py` (`tmux split-window -h -c <dir> -P -F '#{pane_id}' <shlex.join(cmd)>`)                        |
| Single-key chooser modal pattern + styling                                       | `PromptSubmitChoiceModal` (`modals/prompt_submit_choice_modal.py`) + `.duration-choice-*` in `styles.tcss`                   |
| Stash whole bar as ONE bundle (panes + frontmatter/properties)                   | `stash_all_panes` → `PromptInputBar.Stashed(source="all")` → `_persist_stashed_panes` (joins panes `\n---\n` into one row)   |
| Load an xprompt `.md` back into the bar (frontmatter→property panel, body→panes) | `load_stack_from_xprompt_markdown` (`widgets/_prompt_input_bar_stack_rendering.py`)                                          |
| Async-resolve + request-id guard + refocus                                       | `PromptPreviewMixin` (`widgets/_prompt_preview.py`); `_refocus_if_needed`                                                    |

## 3. Design Decisions / Interpretations (flagged for review)

The request explicitly asked me to lead the design. These are the decisions I made on ambiguous points; please correct
any during plan review.

1. **"Vertical tmux pane" = a side-by-side split (`tmux split-window -h`).** In tmux, `-h` produces a left/right split
   (a _vertical divider_), which is the "editor opens beside me" layout people usually mean and matches the existing
   `_viewer_tmux.py` pattern. Trivially switchable to `-v` if you meant top/bottom.
2. **Auto-skip the menu when only one action applies.** Interpreting "otherwise, don't show this menu and default to the
   next option": a one-item menu is pure friction, so when exactly one action is applicable we run it immediately (e.g.
   not-in-tmux + plain file → open in this pane with no modal).
3. **"Loadable into the prompt input" ⟺ the xprompt is _not_ YAML-backed.** Using the codebase's own
   `is_yaml_backed_source(source_id)` predicate. This cleanly excludes multi-step `.yml` workflows, single-part `.yml`
   xprompts, **and** inline `sase.yml` / config-defined xprompts (all "defined in a YAML"), while including `.md`
   xprompts and `.md`-based skills — exactly the stated rule. File-path targets never offer "load".
4. **vim/nvim line:col targets (best-effort, "if appropriate"):**
   - **File token** with a trailing `:line` or `:line:col` (the universal `path:line:col` convention, also endorsed by
     `CLAUDE.md`) → jump there.
   - **`.md` xprompt** → cursor at the first body line _after_ the YAML frontmatter (lands on the actual prompt
     content); line 1 if no frontmatter.
   - **YAML-defined xprompt/workflow** (`.yml`, or `config` → `sase.yml`) → the line where the named definition key
     appears (cheap text scan); line 1 fallback.
   - Only vim/nvim get cursor args; every other editor just opens the file.
5. **Editor-open actions work for _every_ resolvable target** (including YAML workflows and config xprompts — we open
   `sase.yml` at the right line). Only the **load** action is restricted (decision #3).
6. **`Ctrl+]` is hardcoded in Python**, like every other prompt-input normal-mode key (`K`, `/`, `gj`…). Confirmed: only
   app-level keymaps live in `default_config.yml`; prompt-input vim keys do not. So **no `default_config.yml` change** —
   noting explicitly to preempt the `gotchas` "Default Keymap Config" rule, which applies only to configurable app-level
   keymaps.

## 4. Implementation Plan

### 4.1 Token detection + jump resolution (new module)

New module `src/sase/ace/tui/widgets/_prompt_jump_target.py` (presentation-adjacent; lives with the prompt widget
mixins, mirroring `_prompt_preview_target.py`). Pure, no Textual imports, no side-effects → fully unit-testable.

**Detection** — reuse the preview detector, then layer optional `:line:col` for files:

```
@dataclass(frozen=True, slots=True)
class JumpToken:
    kind: Literal["xprompt", "file"]
    raw: str
    target: str          # xprompt name, or file path (without @, without :line:col)
    line: int | None     # parsed from a file token's :line[:col] suffix
    col: int | None
    start: int
    end: int

def detect_jump_target_at_cursor(text: str, cursor_offset: int) -> JumpToken | None
```

- Delegate to `detect_preview_target_at_cursor(text, offset)` for the base token (xprompt precedence over file, span
  containment — identical behavior to `K`).
- For a `file` token, scan `text[token.end:]` for `^:(\d+)(?::(\d+))?` and fold the parsed `line`/`col` in. (The
  existing `FILE_PATH_RE` deliberately stops before a `:line` suffix, so this is additive and cannot regress preview.)
- xprompt tokens carry `line=col=None` here (their line/col is computed at resolve time from the definition file).

**Resolution** — reuse existing resolvers; the only layer that touches disk/catalog:

```
@dataclass(frozen=True, slots=True)
class JumpTarget:
    kind_label: str             # "xprompt" | "skill" | "workflow" | "file"
    icon: str                   # "#" for xprompt-family, "@" for file
    title: str                  # "#foo" or the raw file token
    source_path: str            # ABSOLUTE path to open in the editor
    line: int | None            # 1-based; best-effort
    col: int | None             # 1-based; best-effort
    loadable_markdown: str | None   # the .md source text to load into the bar, else None

class JumpError(Exception): ...  # user-facing message for the toast

def resolve_jump_target(token, *, project: str | None, base_dir: str) -> JumpTarget
```

- **xprompt/skill/workflow** (`token.kind == "xprompt"`):
  - `obj = get_xprompt_or_workflow(token.target, project)`; `None` →
    `JumpError("No xprompt or skill named '#<t>' found")`.
  - `kind_label`: `"skill"` if `XPrompt.skill`, `"workflow"` for a non-simple `Workflow`, else `"xprompt"`.
  - `source_path = resolve_source_to_file_path(obj.source_path)`; if it is not a real, readable file →
    `JumpError("No definition file found for #<t>")` (covers programmatic built-ins with `source_path is None`).
  - **Loadable** ⟺ `not is_yaml_backed_source(obj.source_path)` **and** the source file is a readable `.md`. When
    loadable, `loadable_markdown` = the file's text (full fidelity: frontmatter + body); else `None`.
  - **line/col:** if loadable `.md` → first line after the YAML frontmatter (else 1), col 1. If YAML-defined → scan the
    file for the definition key line (top-level `<name>:` or an entry under `xprompts:`/`workflows:`), col = key indent
    - 1; line 1 fallback.
- **file** (`token.kind == "file"`):
  - `resolved = Path(resolve_file_path(token.target, base_dir)).expanduser()`; not exists →
    `JumpError("File not found: <path>")`; is a directory → `JumpError("'<path>' is a directory, not a file")`.
  - `line/col` carried over from the token's `:line:col` suffix. `loadable_markdown = None`.

**Editor argv builder** (pure, here so it is unit-testable):

```
_VIM_FAMILY = {"vim", "nvim", "vi", "view", "gvim", "mvim", "nv"}

def build_jump_editor_argv(editor: str, file_path: str, line: int | None, col: int | None) -> list[str]:
    if os.path.basename(editor) in _VIM_FAMILY and line:
        return [editor, "-c", f"call cursor({line}, {max(1, col or 1)})", file_path]
    return [editor, file_path]      # delegates to build_editor_args semantics for non-vim / no line
```

`project`/`base_dir` come from the existing `self._preview_context()` (already on the widget via `PromptPreviewMixin`),
so the two keymaps resolve relative paths identically.

### 4.2 Wire `Ctrl+]` (normal mode)

In `src/sase/ace/tui/widgets/_vim_normal.py`, `_handle_normal_mode_key`, intercept the key **right next to the `K`
block** (a command, not a mutation, so it is never recorded for `.`-repeat), gated by the existing top-level predicate
so multi-key sequences still treat it as a literal:

```
if event.key == "ctrl+right_square_bracket" and self._can_start_prompt_search_from_normal_key():
    self._jump_to_definition_under_cursor()
    return True
```

- Match on `event.key` (not `event.character`): for `Ctrl+]` Textual sets `event.key == "ctrl+right_square_bracket"`
  (verified: `Keys.ControlSquareClose`), while `event.character == "\x1d"` — so the `key = event.character or event.key`
  local would otherwise be the raw control char.
- `Ctrl+]` falls through to this dispatcher: `_on_key`'s early ctrl handlers only consume `ctrl+s/c/k/g/r/...`, and
  there is no app-level `ctrl+right_square_bracket` binding (only bare `]`/`[` are app-bound). The widget consumes and
  `event.stop()`s it anyway.
- Add `_jump_to_definition_under_cursor` to the `TYPE_CHECKING` stubs in `_vim_normal.py` (next to
  `_preview_token_under_cursor`).

### 4.3 Widget action mixin (new)

New `src/sase/ace/tui/widgets/_prompt_jump.py`: `class PromptJumpMixin`, mixed into `PromptTextArea` alongside
`PromptPreviewMixin`, structured exactly like the preview mixin (async resolve on a worker thread, request-id guard,
`is_mounted` checks):

1. `_jump_to_definition_under_cursor()`: compute `offset`, `token = detect_jump_target_at_cursor(self.text, offset)`;
   `None` → warning toast (contract #1); else bump `_prompt_jump_request_id`,
   `run_worker(self._resolve_jump_async(...))`.
2. `_resolve_jump_async(...)`: `payload = await asyncio.to_thread(resolve_jump_target, ...)`; `JumpError` → distinct
   toast (contract #2); unexpected `Exception` → error toast; on success and still-current request + mounted → hand off
   to `_present_jump_actions(payload)`.
3. `_present_jump_actions(payload)`: build the applicable action list
   (`[("t", tmux) if is_tmux_session()] + [("e", editor)] + [("l", load) if payload.loadable_markdown]`); if exactly one
   → `_perform_jump_action(only_choice, payload)` directly (contract #4); else
   `push_screen(JumpActionModal(...), on_result)` and run the chosen action in the callback, then
   `_refocus_if_needed()`.
4. `_perform_jump_action(choice, payload)`: dispatch to the three side-effecting helpers (§4.5).

Initialize `_prompt_jump_request_id = 0` in `PromptTextArea.__init__` (mirroring `_prompt_preview_request_id`) and add
`PromptJumpMixin` to the class's mixin list (`prompt_text_area.py`).

### 4.4 The jump action menu modal (new)

New `src/sase/ace/tui/modals/jump_action_modal.py`: `class JumpActionModal(ModalScreen[JumpChoice | None])`, modeled
directly on `PromptSubmitChoiceModal` (single-key chooser; dumb/presentational; takes already-resolved data so it is
deterministic and snapshot-testable).

- `type JumpChoice = Literal["tmux", "editor", "load"]`.
- `__init__(self, *, title, kind_label, icon, source_display, choices: list[JumpChoice])` — `source_display` is the dim
  path line with `:line:col` appended when present; `choices` is the pre-filtered, ordered list.
- `BINDINGS`: `t`/`e`/`l` → `dismiss(<choice>)` (only those present matter); `escape`/`q` → `dismiss(None)`.
- `compose()`: reuse the `.duration-choice-*` vocabulary — a title (`"Jump to {kind_label}"`), a header line
  (`{icon} {title}` + dim `source_display`), one styled row per applicable choice (`t  Open in new tmux pane`,
  `e  Open in this pane`, `l  Load into prompt input`), and a dim footer hint listing only the available keys (e.g.
  `t pane · e editor · l load · esc cancel`).
- Export it from `modals/__init__.py` (mirroring the `PromptSubmitChoiceModal` export).

### 4.5 Action execution (side-effecting helpers)

On `PromptJumpMixin` (kept thin; the pure argv/command building lives in the testable module §4.1):

- **`editor` (open in this pane):**
  ```
  editor = get_editor()
  argv = build_jump_editor_argv(editor, payload.source_path, payload.line, payload.col)
  with suspend_for_external_tool(self.app, action="jump_to_definition", tool_kind="editor",
                                 command=editor, path_count=1, status_message="Opening definition…"):
      subprocess.run(argv, check=False)
  ```
  Wrap in `try/except OSError` → error toast; `_refocus_if_needed()` afterward.
- **`tmux` (open in a new vertical pane):** no suspend (the TUI keeps running in its own pane).
  ```
  cmd = ["tmux", "split-window", "-h", "-c", base_dir, "-P", "-F", "#{pane_id}",
         shlex.join(build_jump_editor_argv(editor, payload.source_path, payload.line, payload.col))]
  result = subprocess.run(cmd, check=False, capture_output=True, text=True)
  ```
  Non-zero exit / `FileNotFoundError` → error toast. The pane closes when the editor exits (default tmux behavior).
- **`load` (stash + load):** `bar = self._find_prompt_bar()`; guard `bar is not None`; call the new
  `bar.stash_all_and_load_xprompt_markdown(payload.loadable_markdown)` (§4.7).

### 4.6 Editor command building — see §4.1 `build_jump_editor_argv`

Covered above. The `-c "call cursor(L, C)"` form is supported by both vim and nvim (the existing nvim precedent uses
exactly this), so one code path serves the whole vim family; everything else falls back to a plain open.

### 4.7 Stash-then-load (new bar method)

Add to the prompt-input bar (the `PromptInputBarStashActionsMixin`, `widgets/_prompt_input_bar_stash_actions.py`, where
`stash_all_panes` already lives):

```
def stash_all_and_load_xprompt_markdown(self, markdown: str) -> None:
    """Stash the whole bar as ONE bundle, then load *markdown* in its place."""
    if self._mode != "prompt":
        return
    self._sync_state_from_widgets()
    panes = [StashedPromptPane(text=stripped, frontmatter=self._stack.frontmatter, pane_index=i)
             for i, item in enumerate(self._stack.items) if (stripped := item.text.strip())]
    if not panes and self._stack.frontmatter.strip():
        # Capture a frontmatter-only bar so xprompt PROPERTIES aren't lost.
        panes = [StashedPromptPane(text="", frontmatter=self._stack.frontmatter,
                                   pane_index=self._stack.selected_index)]
    if panes:
        self._clear_active_completion_state()
        self.post_message(self.Stashed(panes, source="all", dismiss_bar=False))   # persist as one bundle, KEEP the bar
    self.load_stack_from_xprompt_markdown(markdown)                               # replace bar with the xprompt
```

Why this composes correctly and reliably:

- `StashedPromptPane` snapshots are captured **before** posting, so even though `Stashed` is processed asynchronously
  (after `load_stack_from_xprompt_markdown` mutates `self._stack`), the persisted data is the _pre-load_ bar — exactly
  the bundle we want to be able to restore later.
- `source="all"` routes through `_persist_stashed_panes`, which joins panes with `\n---\n` into **one canonical
  multi-prompt row** (a _bundle_) carrying the shared frontmatter (the xprompt properties) — the user's "bundled prompt
  stash." The app toasts "Stashed N prompts as a bundle" and the badge updates, all via the existing pipeline.
- `dismiss_bar=False` (vs `stash_all_panes`'s `True`) keeps the bar mounted so we can load into it.
- `load_stack_from_xprompt_markdown` lifts the xprompt's leading frontmatter into the shared stack frontmatter (so the
  **xprompt property panel** shows its declared inputs/properties) and splits real `---` separators into panes — a
  faithful, editable reconstruction of the xprompt.
- Empty bar (nothing to stash) → no `Stashed` posted, just load. Correct ("stash … if any").

### 4.8 Styling

Add `JumpActionModal` to the shared "Duration Choice Modal" block in `src/sase/ace/tui/styles.tcss` (the
`PromptSubmitChoiceModal, QuitOptionsModal, …` selector list) so it inherits `align: center middle` and the
`.duration-choice-*` look (double `$primary` border, `$surface` background). Add a
`#jump-action-container { width: 64; }` rule (a touch wider than the submit chooser to fit the source path), and a dim
style for the header source-path line. Goal: visually identical idiom to the existing single-key choosers.

## 5. Testing

1. **Unit — detection** (`tests/ace/tui/widgets/test_prompt_jump_target.py`): cursor on `#foo`, `#foo:arg`, `#proj/foo`,
   `@path`, bare `dir/file.ext`, `~/x`; **`:line` and `:line:col` suffix parsing** on file tokens (and that a bare path
   yields `line=col=None`); cursor in prose → `None`; xprompt-vs-file precedence (inherited from preview detector).
2. **Unit — resolution** (same file): `.md` xprompt → `loadable_markdown` set, body-start line; skill (`skill: true`) →
   `kind_label == "skill"`; multi-step `.yml` workflow → not loadable, definition-key line, `source_path` ends `.yml`;
   single-part `.yml` xprompt → **not** loadable (YAML); inline `config` xprompt → `source_path` is `…/sase.yml`, not
   loadable, def-key line scanned; missing xprompt → `JumpError` (distinct msg); programmatic built-in
   (`source_path is None`) → `JumpError("No definition file found…")`; file found (line/col carried through), file
   missing → distinct `JumpError`, directory → `JumpError`.
3. **Unit — editor argv** (same file): nvim + line/col → `["nvim","-c","call cursor(L, C)", f]`; vim same; `code`/other
   editor → `[editor, f]` (no cursor args); no line → plain open even for nvim.
4. **Keymap / widget behavior** (`tests/ace/tui/widgets/test_prompt_normal_mode_jump.py`, in the style of
   `test_prompt_normal_mode_*` and `test_prompt_normal_mode_preview.py`):
   - `Ctrl+]` on a resolvable token with ≥2 applicable actions pushes `JumpActionModal`.
   - `Ctrl+]` with exactly one applicable action runs it directly (no modal) — assert via a stubbed
     `_perform_jump_action`.
   - `Ctrl+]` on nothing → the "move the cursor…" toast, no screen.
   - `Ctrl+]` on a non-existent `#foo` / missing file → the _distinct_ toast.
   - **Regression:** `Ctrl+]` does not disturb a pending operator/motion sequence and is never `.`-repeatable
     (extend/assert alongside the existing normal-mode tests).
5. **Modal** (`tests/ace/tui/modals/test_jump_action_modal.py`): only the passed-in `choices` render; `t`/`e`/`l`
   dismiss with the right value; absent keys do nothing; `esc`/`q` → `None`.
6. **Stash-then-load** (`tests/ace/tui/widgets/test_prompt_stack_*` style): `stash_all_and_load_xprompt_markdown` posts
   one `Stashed(source="all", dismiss_bar=False)` carrying the pre-load panes+frontmatter, then the bar holds the loaded
   xprompt (frontmatter lifted into the property panel, body in the pane); empty-bar case posts nothing and just loads.
7. **Visual PNG snapshot** (`tests/ace/tui/visual/test_ace_png_snapshots_jump_action.py`, using the `AcePage` +
   `ace_png_visual` fixtures, mirroring the preview-panel snapshot test): one snapshot of `JumpActionModal` showing all
   three options for an xprompt target (header badge + source path + rows + footer). Regenerate with
   `--sase-update-visual-snapshots`.

Side-effecting paths (subprocess/tmux/suspend) are exercised by stubbing the thin executor helpers; the pure
argv/command building and the decision logic (which actions apply, single-vs-menu) are tested directly.

## 6. Docs / Help / Config Sync (repo conventions)

- **Help popup (`?`)** — _required by `src/sase/ace/AGENTS.md` "Help Popup Maintenance."_ Add a row to
  `PROMPT_INPUT_SECTION` in `src/sase/ace/tui/modals/help_modal/binding_common.py`, next to the `K` row, e.g.
  `("Ctrl+]", "Jump to xprompt/skill/file def")` (description = 30 chars ≤ 32-char limit). Bump the expected binding
  count in `tests/test_keymaps_display_help.py` (the `K` change did the same +1).
- **Footer** (`keybinding_footer.py`) — surfaces conditional keymaps for the selected Agents/ChangeSpec entry, not
  prompt-input normal-mode keys, so `Ctrl+]` does **not** belong there (matches the `K` decision).
- **`default_config.yml`** — no change (see §3 decision #6).

## 7. Out of Scope / Possible Follow-ups

- A "preview then jump" bridge (e.g. a jump key from inside the `K` preview panel).
- Jumping from **visual** mode using the active selection (v1 is normal-mode + cursor, like `K`).
- Loading **inline `sase.yml`** / YAML-defined xprompts into the bar (intentionally excluded; we open the YAML instead).
- Directory targets (v1 errors on directories, like preview).
- A configurable editor setting and a configurable tmux split orientation (currently `$EDITOR`/`get_editor` and `-h`).
- Pushing token classification/resolution into `sase-core` for cross-frontend reuse (separate, larger workstream).

## 8. Files Touched (summary)

**New:**

- `src/sase/ace/tui/widgets/_prompt_jump_target.py` — `JumpToken` / `JumpTarget` / `JumpError`,
  `detect_jump_target_at_cursor`, `resolve_jump_target`, `build_jump_editor_argv` (pure, unit-tested).
- `src/sase/ace/tui/widgets/_prompt_jump.py` — `PromptJumpMixin` (detect → async resolve → present → perform).
- `src/sase/ace/tui/modals/jump_action_modal.py` — `JumpActionModal` single-key chooser + `JumpChoice`.
- Tests: jump target, normal-mode keymap, modal, stash-then-load, visual snapshot.

**Modified:**

- `src/sase/ace/tui/widgets/_vim_normal.py` — intercept `ctrl+right_square_bracket` (+ TYPE_CHECKING stub).
- `src/sase/ace/tui/widgets/prompt_text_area.py` — mix in `PromptJumpMixin`; init `_prompt_jump_request_id`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_stash_actions.py` — add `stash_all_and_load_xprompt_markdown`.
- `src/sase/ace/tui/modals/__init__.py` — export `JumpActionModal`.
- `src/sase/ace/tui/styles.tcss` — `JumpActionModal` styling.
- `src/sase/ace/tui/modals/help_modal/binding_common.py` — document `Ctrl+]`.
- `tests/test_keymaps_display_help.py` — bump expected binding count.

## 9. Validation

Run `just install` then `just check` (lint + mypy + tests) and `just test-visual` for the new PNG snapshot. The change
is presentation-layer Python + Textual reusing existing resolvers and the existing (core-backed) stash pipeline, so no
`sase-core` changes are expected.
