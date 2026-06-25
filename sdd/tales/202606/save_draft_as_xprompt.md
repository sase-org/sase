---
create_time: 2026-06-25 08:27:40
status: done
---
# Plan: Save the current prompt draft as an xprompt (`gx` / `<ctrl+g>x`)

## 1. Goal

Add a way to capture the **current prompt draft** — every visible prompt pane plus the xprompt property (frontmatter)
panel — and persist it as a reusable **xprompt**, either by **overwriting** an existing xprompt or **creating a new
one**.

Two keymaps on the prompt input widget trigger the flow:

- `gx` — normal (vim) mode
- `<ctrl+g>x` — insert mode

Both open a new, filterable picker panel. The user either picks an existing xprompt to overwrite, or chooses "Create new
xprompt…", which then asks where to put it (a valid xprompt directory or config file) and what to name it.

The feature must be **intuitive** (mirrors muscle-memory of the existing `g`-prefix keymaps and existing xprompt
browser/location modals), **reliable** (never silently clobbers; confirms destructive overwrites; writes off the event
loop; round-trips cleanly through the loader), and **beautiful** (matches the existing modal aesthetic: filter +
two-pane list/preview, group headers, icons, color tokens).

## 2. Why this is a natural fit

The prompt bar already has a family of "save the current draft somewhere" keymaps that this slots directly into:

- `gs` / `<ctrl+g>s` — stash all panes
- `gS` / `<ctrl+g>S` — update pinned stash
- `<ctrl+g>p` — open stash picker

`gx` / `<ctrl+g>x` ("**x**prompt") becomes the "save the draft as a _named, reusable_ xprompt" sibling of those. The
plumbing pattern (bar captures panes+frontmatter → posts a Textual message → app orchestrates a modal and the
persistence off-thread) is reused verbatim, so the feature stays consistent with the codebase instead of inventing a new
path.

The "create new xprompt" half already exists in the XPrompt Browser (`action_add_xprompt`): location picker →
name/inputs → write. We reuse those building blocks rather than duplicating them, and the only genuinely new persistence
logic is "serialize the _already-known_ draft (panes + frontmatter) into a `.md` file or a config `xprompts:` entry."

## 3. Designed user experience

### 3.1 Trigger

From any prompt bar pane (single or multi-agent stack), in normal mode press `gx`, or in insert mode press `<ctrl+g>x`.
A hint for it appears in the existing `g`-prefix / `<ctrl+g>`-prefix hint panel (label: e.g. "save as xprompt").
Available only in prompt mode and only when there is something to save (≥1 non-empty pane, or non-empty frontmatter);
otherwise it is a no-op that toasts "Nothing to save as an xprompt".

### 3.2 The Save-Target panel (new modal)

A centered modal titled **"Save draft as xprompt"** with:

- A **filter input** at top ("Type to filter…"); filtering as the user types.
- A **two-pane body**: a list on the left, a **preview** on the right.
- **Footer hints**: `^n/^p navigate • enter select • ^d/^u scroll • Esc cancel`.

List contents, top to bottom:

1. **`➕ Create new xprompt…`** — pinned at the very top, always visible (it also matches filters like "new"/"create" so
   typing never hides it; it stays first). Distinct accent styling.
2. A separator/group header, then **all known overwritable xprompts**, grouped by source category exactly like the
   XPrompt Browser (CWD, Home, Project, User sase.yml, Plugin, Built-in). Each row shows the xprompt **name** and its
   **source file path** (shortened `~/…`, `./…`). The right preview shows the **existing** content of the highlighted
   xprompt — i.e. _what will be overwritten_ — so the user can confirm the target before committing. The preview also
   shows a small "Will overwrite:" banner + the draft summary (pane count, whether frontmatter is included).

Overwrite-eligibility (what is selectable):

- **Selectable**: "simple" xprompts (`Workflow.is_simple_xprompt()` is true) whose source resolves to either a markdown
  `.md` file or a config `xprompts:` entry — these are the two formats our serializer produces and the loader
  round-trips.
- **Shown but disabled** (dimmed, with an inline reason): multi-step `.yml` **workflows**
  (`(workflow — can't overwrite with a prompt draft)`). Listing them keeps the panel an honest "all known xprompts" view
  while preventing a category error that would corrupt a workflow file. (Disabled rows are skipped by `j/k` navigation,
  same as group headers.)

### 3.3 Overwrite an existing xprompt

Selecting an eligible existing xprompt opens a **confirmation** (`ConfirmActionModal`): "Overwrite xprompt `<name>` at
`<path>` with the current draft?" On confirm, the draft is written over that target (file rewrite for `.md`; entry
replace-in-place for a config `xprompts:` key — `insert_xprompt_into_config` already overwrites a same-named entry). On
success, toast "Saved draft as xprompt `<name>`" and offer the existing git commit-and-push prompt (reuse
`_offer_git_commit`). The prompt bar stays mounted and unchanged (saving is non-destructive to the draft).

### 3.4 Create a new xprompt

Selecting **`➕ Create new xprompt…`** runs:

1. **Location picker** — reuse `XPromptLocationModal`. It already enumerates valid directories (CWD/home/project
   `xprompts/`) and config files (`sase.yml`, overlays, local, built-in/plugin) and marks `(new)` targets. Returns an
   `XPromptLocation`.
2. **Name input** — a small new modal (`XPromptNameModal`) asking for the xprompt **name** (single field; validates
   non-empty, no spaces; warns/asks-to-confirm if the name already exists at that location). We ask only for a _name_
   (not inputs) because the draft's inputs/properties already come from the frontmatter panel.
   - Directory target → write `<dir>/<name>.md`.
   - Config target → insert entry `<name>` under that file's `xprompts:` key.
3. Write, toast "Created xprompt `<name>`", reload, offer git commit (reuse `_offer_git_commit`).

We intentionally do **not** open `$EDITOR` (unlike the browser's create flow): the content already exists in the draft,
so we write it directly. Multi-agent drafts are written as a single `.md` whose body has `---` separators (the canonical
multi-agent xprompt format).

## 4. What gets written (serialization contract)

Source of the content:

- **Body** = the panes joined into the canonical multi-prompt string. Reuse the existing stack join semantics: non-empty
  panes stripped and joined with `\n---\n` (`PromptStackState.join(include_frontmatter=False)` gives exactly the body).
  A single pane yields a plain body with no separators.
- **Frontmatter / properties** = the bar's shared frontmatter, parsed into the structured `PromptFrontmatter` model
  (`name`, `description`, `tags`, `input`, `xprompts`, `skill`, `snippet`).

Two output formats:

- **Markdown `.md`** (existing `.md` target or new file in a directory): `PromptFrontmatter.serialize()` already emits
  the canonical `---`-delimited block; the file is `frontmatter_block + "\n\n" + body + "\n"` (or just `body + "\n"`
  when there is no frontmatter). For a new file whose stem is the name, drop a redundant `name:` key (the filename is
  the name) to match repo conventions; keep it harmless if present.
- **Config `xprompts:` entry** (existing config-entry target or new in a `sase.yml`/overlay): serialize the **full**
  property set (`description`, `tags`, `input`, `xprompts`, `skill`, `snippet`) plus `content:` for the body, as a
  single YAML entry, then place it alphabetically — replacing any existing same-named entry — via the existing
  `insert_xprompt_into_config` section surgery.

Both outputs must round-trip: parsing the written file back through the xprompt loader (Python and the Rust
`sase_core_rs` catalog) yields the same prompt + properties. New unit tests assert this round-trip for both formats,
including a multi-agent (`---`) body and the full property set.

### 4.1 Extending config serialization (the one real gap)

`xprompt_config_yaml._generate_xprompt_yaml` today only emits `name`/`input`/`content`. It must be extended to emit the
complete `PromptFrontmatter` property set + `content`. Plan: build the entry mapping from
`PromptFrontmatter.to_mapping()` (already canonical-ordered, minus `name`) plus `content`, render the properties with
`yaml.safe_dump`, and keep a literal-block (`content: |`) representation for the (possibly multi-line, `---`-containing)
body so config files stay readable. `insert_xprompt_into_config` keeps its alphabetical-insert + overwrite-by-name
behavior unchanged (it already replaces a same-named entry, which is what overwrite needs).

## 5. Architecture & component changes (high level)

All paths are repo-relative.

### 5.1 Keymap (smallest possible surface)

The prompt `g`-prefix system is a single declarative table that drives **both** dispatch and hints, and the `<ctrl+g>`
insert path reuses the same table. Adding one row gives us **both** `gx` (normal) and `<ctrl+g>x` (insert) for free.

- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`
  - Add one
    `_PromptGPrefixBinding("x", "request_save_as_xprompt", "_g_prefix_label_save_xprompt", "_g_prefix_available_save_xprompt")`
    to `_PROMPT_G_PREFIX_BINDINGS` (`ctrl_g_only=False` so it serves both surfaces).
  - Add `request_save_as_xprompt()` — sync widgets, capture non-empty panes + frontmatter into `StashedPromptPane`s
    (reusing the same capture shape as `request_update_pinned_stash`), and post a new `SaveAsXpromptRequested` message.
    No-op outside prompt mode.
  - Add `_g_prefix_label_save_xprompt()` → "save as xprompt".
  - Add `_g_prefix_available_save_xprompt()` → prompt mode and (any non-empty pane or non-empty frontmatter).

### 5.2 New bar→app message

- `src/sase/ace/tui/widgets/_prompt_input_bar_messages.py`
  - Add `SaveAsXpromptRequested(Message)` carrying `panes: list[StashedPromptPane]` (text + shared frontmatter,
    mirroring `UpdatePinnedRequested`).
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
  - Re-export it as `PromptInputBar.SaveAsXpromptRequested` (same pattern as the other nested message classes).

### 5.3 App-side orchestration mixin

- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py` (new)
  - `PromptBarSaveXpromptMixin` with `on_prompt_input_bar_save_as_xprompt_requested`: builds the body from the captured
    panes (`\n---\n` join) and parses the captured frontmatter into a `PromptFrontmatter`, then pushes
    `XPromptSaveTargetModal`.
  - Result handling: existing target → `ConfirmActionModal` → write off-thread; "create new" sentinel →
    `XPromptLocationModal` → `XPromptNameModal` → write off-thread.
  - The actual file/config writes run via `asyncio.to_thread` (TUI perf rule: no synchronous disk I/O on the event
    loop), with success/error toasts on the UI thread, then `_offer_git_commit` (reused) and a stash-style task ref
    hold.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`
  - Add `PromptBarSaveXpromptMixin` to `PromptBarMixin`'s bases (next to `PromptBarStashMixin`).

### 5.4 New picker modal

- `src/sase/ace/tui/modals/xprompt_save_target_modal.py` (new)
  - `XPromptSaveTargetModal(OptionListNavigationMixin, ModalScreen[XPromptSaveTarget | None])` modeled on
    `XPromptBrowserPane` / `XPromptLocationModal`: filter input + grouped `OptionList` + preview, `j/k`/`^n`/`^p`
    navigation that skips headers **and disabled rows**, `enter` selects.
  - Reuses `get_all_prompts` + `get_all_project_local_prompts` + `classify_source` + `resolve_source_to_file_path` (from
    `xprompt_browser_helpers`) to build the list and resolve each row's real write path; computes per-row eligibility
    (simple-xprompt + `.md`/config) and disables the rest.
  - Result dataclass `XPromptSaveTarget` is a small union: either `kind="create"` (the sentinel) or `kind="overwrite"`
    with `name`, resolved `path`, and `target_format` (`"markdown"` | `"config"`) plus the config entry key when
    relevant.
  - Preview pane renders the highlighted target's current content (what will be overwritten) and a draft summary banner.
- `src/sase/ace/tui/modals/xprompt_name_modal.py` (new)
  - `XPromptNameModal(ModalScreen[str | None])` — single-field name entry (mirrors `XPromptFilenameModal`, minus the
    extension requirement), validates non-empty/no-spaces, surfaces an inline "already exists — will overwrite" note
    when applicable.
- `src/sase/ace/tui/modals/__init__.py` — export the two new modals + the result dataclass.

### 5.5 Pure persistence module (testable, frontend-agnostic)

- `src/sase/xprompt/save.py` (new) — pure logic, no Textual:
  - `build_markdown_xprompt(frontmatter: PromptFrontmatter, body: str) -> str`
  - `save_markdown_xprompt(path, frontmatter, body) -> None`
  - `save_config_xprompt(config_path, name, frontmatter, body) -> bool` (wraps the extended config generator +
    `insert_xprompt_into_config`)
  - A small `SaveTargetFormat` enum / result type.
- `src/sase/ace/tui/modals/xprompt_config_yaml.py` — extend `_generate_xprompt_yaml` (or add a sibling) to serialize the
  full property set + content; keep `insert_xprompt_into_config` behavior.

### 5.6 Styling

- `src/sase/ace/tui/styles.tcss` — add `XPromptSaveTargetModal` / `XPromptNameModal` blocks mirroring the existing
  browser/location modal styling (centered, `thick $primary` border, `$surface` bg, two-pane list/preview, muted hint
  row, accent for the "create new" row). No new color tokens.

### 5.7 Docs / discoverability (required by repo conventions)

- `src/sase/ace/tui/modals/help_modal.py` — document `gx` / `<ctrl+g>x` in the prompt-input help section (repo rule:
  keep the `?` help popup in sync; respect the 32-char keybinding description budget).
- `memory/glossary.md` — only if the user approves a memory edit; otherwise leave memory untouched (memory files are not
  modified without approval).

## 6. Rust core backend boundary

Per `memory/rust_core_backend_boundary.md`, shared backend behavior belongs in `sase-core`. Findings that determine the
boundary call here:

- xprompt **loading/parsing/cataloging** lives in both Python and Rust (`sase-core .../xprompt_catalog.rs`) for the
  editor/LSP — the **format is the shared contract**, and both sides already parse it.
- xprompt **writing** is currently **Python-only** everywhere (`prompt_frontmatter.serialize`,
  `xprompt_config_yaml.insert_xprompt_into_config`, the browser's create flow). There is no Rust xprompt writer and no
  second frontend that writes xprompts today.

Decision: keep the new **write/serialization in Python**, but factor the pure logic into `src/sase/xprompt/save.py` (not
buried in TUI widgets) so a future CLI/web frontend could reuse it, and so it is unit-testable without an app. The
cross-frontend invariant we must preserve is that **what we write is exactly what the Rust catalog parses back** —
covered by round-trip tests. (If, in review, the team prefers a `sase xprompt save`-style core entry point, the pure
module is the seam to lift into `sase-core` later; not in scope now.)

## 7. Reliability / edge cases

- **No double-clobber surprises**: overwriting an existing xprompt always passes through an explicit confirm modal
  showing name + path; creating a new one warns when the name already exists at the chosen location.
- **Workflows protected**: `.yml` multi-step workflows are shown disabled, never writable with markdown-format content.
- **Read-only/edge sources**: rows resolve their write path up front; if a path can't be resolved or isn't writable, the
  row is disabled with a reason (no failed half-writes).
- **Off the event loop**: all disk/config writes via `asyncio.to_thread`; UI mutations and toasts on the UI thread (TUI
  perf rules 1–2). Writes are fast single-file ops, so a tracked task is not required, but the git commit/push offer
  reuses the existing confirm path.
- **Empty draft**: keymap gated off when there's nothing to save; defensive toast otherwise.
- **Frontmatter-only / body-only drafts**: both supported (frontmatter omitted when empty; body may be empty if only
  properties are defined — rare but valid).
- **Multi-agent bodies in config**: `---` lines live safely inside a `content: |` literal block; covered by tests.
- **Name with `/`**: config entry keys allow `a/b` style names (the entry-key regex already supports them); directory
  targets sanitize to a filename. Validation messages guide the user.

## 8. Testing

- `tests/xprompt/test_save.py` (new) — pure serializer + round-trip:
  - markdown build/parse round-trip with full property set and a multi-agent body;
  - config entry generation, alphabetical placement, and **overwrite-in-place** of an existing same-named entry;
    round-trip through `get_all_prompts`/loader.
- `tests/ace/tui/modals/test_xprompt_save_target_modal.py` (new) — list building (create-new pinned first, workflows
  disabled, eligible targets selectable), filtering, and result payloads for both overwrite and create paths.
- `tests/ace/tui/widgets/` — extend prompt-bar stack-action tests: `gx`/`<ctrl+g>x` availability gating, capture shape,
  and that `request_save_as_xprompt` posts `SaveAsXpromptRequested` with the expected panes/frontmatter.
- App-handler test for the orchestration (target → confirm/create → write) using the existing prompt-bar action test
  harness, asserting the write lands and the draft is preserved.
- `just check` (lint + mypy + tests) before completion; run `just install` first because of ephemeral workspaces.

## 9. Out of scope (call out, don't build)

- A `sase xprompt save` CLI command (the pure module makes it a small future add).
- Editing inputs/properties _inside_ the save flow (the frontmatter panel already owns that; the save flow just
  serializes what's there).
- Overwriting `.yml` workflows or converting a draft into a multi-step workflow.
- Moving xprompt writing into `sase-core` (documented as the future seam).

## 10. Decisions already made (so implementation is unambiguous)

- One binding row gives both `gx` and `<ctrl+g>x`; no per-mode special-casing.
- "Create new" is a pinned, always-first list item, not a separate key.
- Overwrite is confirmed; create warns on name collision.
- `.yml` workflows are listed-but-disabled, not hidden, for an honest "all known" view.
- Content is written directly from the draft (no `$EDITOR` round-trip).
- Persistence is Python, factored into `src/sase/xprompt/save.py`; format parity with the Rust catalog is enforced by
  round-trip tests.
