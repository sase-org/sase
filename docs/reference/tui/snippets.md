---
title: Snippets
description: Prompt snippets, variables, aliases, and the Macro Browser in the sase TUI.
---

# Snippets

This page lists prompt snippets, variables, aliases, and the Macro Browser in the sase
TUI.

## Macro Browser

Press `#` on any tab to open **SASE Admin Center**, press `1` for **Config**, then
choose the **Macros** child (`0` then `7`, or `[` / `]`; within a session, Config
reopens on the child you used last). It displays all discovered macros in a two-panel
layout: a filterable list on the left and a syntax-highlighted preview on the right.
Markdown macros with leading YAML frontmatter render the frontmatter and body with their
respective syntax styles.

Macros are grouped by source (project `sase/macros/`, home `~/sase/macros/`,
project-specific home, config `sase.yml`, plugins, built-in, plus labeled legacy
compatibility sources). Workflow macros (multi-step YAML) are marked with a gear icon;
standalone workflows are displayed with the `#!name` insertion syntax. Project-local
macros defined in each project's `sase.yml` file are also included, even though the
TUI's normal config loading does not read project-local config files.

The list rows and preview metadata show the same insertion form and visible input
metadata used by `Ctrl+T` completion. Step-only inputs are hidden from this user-facing
surface because they are supplied by workflow execution rather than typed by the user.

### Keybindings

| Key       | Action                                                                     |
| --------- | -------------------------------------------------------------------------- |
| `j` / `↓` | Navigate to next macro                                                     |
| `k` / `↑` | Navigate to previous macro                                                 |
| `Ctrl+N`  | Navigate to next macro                                                     |
| `Ctrl+P`  | Navigate to previous macro                                                 |
| `'`       | Jump to a non-header row via adaptive hints                                |
| `/`       | Show and focus the filter input                                            |
| `[` / `]` | Switch to the previous / next Config child                                 |
| `Ctrl+D`  | Scroll preview panel down                                                  |
| `Ctrl+U`  | Scroll preview panel up / clear input                                      |
| `Enter`   | Target the highlighted macro: load it into the home prompt bar for editing |
| `E`       | Open the highlighted definition in `$EDITOR`                               |
| `Ctrl+O`  | Add a new macro                                                            |
| `Ctrl+I`  | Inline-expand the highlighted macro into the home prompt bar               |
| `Esc`     | Close SASE Admin Center                                                    |

The filter input starts hidden. Press `/` to reveal it, then type to narrow the list in
real time; `Enter` or `Esc` closes the input and returns to the list. While the input is
focused, every printable key — including digits and `'` — is ordinary filter text, so
values such as `bug2` can be typed normally; `Ctrl+N` / `Ctrl+P`, `Ctrl+D` / `Ctrl+U`,
`Ctrl+O`, and `Ctrl+I` still reach the list. From the list itself, `'` arms entry-jump
over the non-header rows.

### Editing Macros

Press `Enter` on any macro to load its definition into the home prompt bar and target it
for editing — see
[Editing an Existing Macro from the TUI](prompt-input.md#editing-an-existing-macro-from-the-tui) for
the full targeting loop, including the visual chip states, the target-aware `Enter` save
menu, and the chezmoi-aware write path. Project, home, and config sources are editable
and bind the bar to their source file. Read-only sources (legacy, plugin, and built-in)
load without a target: the bar shows a persistent read-only marker instead, and `gw`
falls through to the save-as flow so your edits land in a new, editable copy rather than
being silently discarded. Press `E` to open an editable definition directly in `$EDITOR`
instead; after saving, the browser offers the applicable follow-up actions (commit/push,
a scoped chezmoi apply, or `sase memory init` / `sase skill init`).

### Creating Macros

Press `Ctrl+O` to start the guided creation flow:

1. **Location modal** — Choose where to save the new macro (project `sase/macros/`, home
   `~/sase/macros/`, project `sase/sase.yml`, or a global config file). Legacy sources
   remain browseable but are never new-write destinations. Press `Ctrl+G` to open the
   selected config file in `$EDITOR` instead of proceeding with creation.
2. **Filename modal** — Enter a filename (`.md` for prompt parts, `.yml` for workflows).
   Workflow files are pre-filled with a YAML template containing the workflow scaffold.
3. **Editor** — The file opens in `$EDITOR` for editing.
4. **Follow-up actions** — After saving, the browser offers the actions that apply to
   the new file: commit/push, and — when `use_chezmoi` redirected the write to the
   chezmoi source — a scoped `chezmoi apply` of just that file.

## Snippets {#snippets-1}

The prompt input supports expandable text snippets triggered by pressing `Tab`. Snippets
are configured in the `ace.snippets` section of `sase.yml` as a mapping of trigger words
to template strings. Inspect or edit the same catalog from the shell with
[`sase snippet`](../macros/fields.md#snippet-cli) (`list`, `show`, `add`,
`delete`), or from sase's TUI with the [Snippets panel](prompt-completion-panels.md#snippets-panel) (`gT` /
`Ctrl+G T`).

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    bug: "Bug in $1:\n\nExpected: $2\nActual: $3\n\nPlease fix.$0"
```

### Usage

1. Type a trigger word (e.g., `fix`) in the prompt input.
2. Press `Tab`. If the word before the cursor matches a snippet, it is replaced with the
   template text.
3. If the template contains tabstop markers (`$1`, `$2`, ...), the cursor jumps to `$1`
   first. Press `Tab` again to advance to `$2`, then `$3`, and so on. `Shift+Tab`
   retreats through already visited tabstops. `$0` marks the final cursor position after
   all tabstops are visited. If there are no tabstop markers, the cursor moves to the
   end of the expanded text.

**Tab priority:** Snippet expansion always takes priority over tabstop advancement. If
you type a trigger word at an active tabstop and press `Tab`, the snippet expands rather
than jumping to the next tabstop. Expanding inside the live snippet nests the new
snippet session: sase's TUI visits the nested snippet's tabstops first, then resumes the
enclosing snippet at the next outer stop. Expanding outside the current snippet resets
the tabstop session.

**Multi-line indentation:** When a multi-line snippet is expanded on an indented line,
continuation lines automatically inherit the leading whitespace of the trigger line.
Tabstop positions are adjusted accordingly.

Trigger words are matched against the alphanumeric/underscore word immediately before
the cursor. If no snippet matches, `Tab` advances to the next tabstop (if any are
remaining from a previous expansion), and `Shift+Tab` retreats to a previously visited
tabstop. If neither snippet action succeeds, the key falls back to INSERT-mode list
shifting when the cursor is on a supported marker line. Advancing from the final tabstop
clears the session before that same fallback check runs.

Macro-derived snippets compose normal macro references before they enter the snippet
registry. After macro-derived snippets and `ace.snippets` are merged, any snippet can
splice another snippet by trigger with `#[trigger]`. `#[trigger(value)]` and
`#[trigger:value]` fill the referenced snippet's `$1`, `$2`, ... tabstops before
splicing. The final template is renumbered so tabstops from the caller and referenced
snippets do not collide.

### Snippet variables

Snippet templates can reference the prompt's target project with the `#{project}`
variable, which is substituted when the snippet expands on `Tab`:

```yaml
ace:
  snippets:
    epic: "the #{project}-$1 epic bead"
```

With `+sase` leading the prompt, `epic<Tab>` inserts `the sase-` and leaves the cursor
at `$1`; with `+bob-cli` it inserts `the bob-cli-`. The value is the project's display
name (its `PROJECT_NAME`, the same prefix bead IDs use), never the directory key.

Resolution order on expansion:

1. The prompt's own explicit target: a leading `+<project>` tag or `#gh:`/`#git:` VCS
   ref, then a non-home prompt context.
2. The SASE current project (the TUI's `+<project>` chip value).
3. Otherwise the token stays unresolved.

Only a known variable with a resolved value is replaced. Any other `#{name}` (for
example Ruby's `"#{x}"`) passes through verbatim, as does an unresolved `#{project}` --
in that case the TUI shows a warning suggesting a `+<project>` tag. There is no escape
syntax. Because substitution happens at expansion time, composed callers inherit the
variable for free: a `repic` snippet built on `#[epic]` resolves `#{project}` the same
way. Capitalized aliases uppercase only the template's first character before
substitution, so a substituted project name keeps its own case.

### Capitalized aliases

Every effective snippet also gains a generated initial-capital alias. For each explicit
trigger, SASE uppercases only its first character — the rest of the trigger is preserved
byte-for-byte — to form a companion trigger, and uppercases only the first character of
the resolved template to form the companion expansion. So authoring only

```yaml
ace:
  snippets:
    foo: "foo bar baz"
```

exposes both `foo` → `foo bar baz` and `Foo` → `Foo bar baz`.

- Only the first character changes. Triggers that are already capitalized,
  digit-leading, or underscore-leading produce no extra entry, and a template whose
  first character has no uppercase form expands unchanged (its distinct trigger alias is
  still created).
- An explicitly authored capitalized trigger always wins. If both `foo` and `Foo` are
  defined, each keeps its own template, and no alias is generated over the authored
  `Foo`.
- Aliases are runtime-only. They are never written back to `sase.yml`, macro front
  matter, or chezmoi source files, and they never prevent you from later defining the
  capitalized name yourself.
- Both spellings participate in `#[trigger]` composition, so `#[foo]` and `#[Foo]` both
  resolve, and generated templates preserve tabstop and escape behavior.

The rule applies uniformly to macro-derived snippets, merged `ace.snippets`, and
snippets saved into the current sase's TUI session — including a second save that
updates an already-pending trigger. The same pairs appear through sase's TUI,
`sase editor helper-bridge snippet-catalog`, normal LSP completion, and the native Rust
fallback.

You can also create a snippet on the fly from the prompt save panel, opened with `gX` or
`Ctrl+G X`. Press `Ctrl+X` in that panel to switch to snippet mode and choose which
config file should store the new `ace.snippets` entry. In snippet mode, rows are grouped
by source and sorted alphabetically by trigger; snippet completions elsewhere are listed
in trigger order, too, for stable display. As soon as sase's TUI reports the snippet as
created or saved, it is available to every prompt input already open in the current TUI;
no prompt remount or restart is needed. When
[`ace.snippet_config_path`](../config/ace-prompts.md#acesnippetconfigpath) is
configured, this panel's row list always offers it, pre-selected, as a synthetic
destination row — even when it points outside the standard discovered locations — and
shows why if it falls back to a discovered location instead (for example
`configured path unusable: read-only`).

When `use_chezmoi` is enabled, the save panel writes the chezmoi source file first.
sase's TUI keeps that successfully written snippet live as session state even before
deployment. Skipping or failing the optional commit/push/apply step does not remove it
from the running TUI, but another SASE process will not see the source-only change until
chezmoi is applied. SASE applies chezmoi from this flow only after the user confirms the
optional commit-and-push action.

Editors using `sase lsp` can receive the same registry as LSP snippet completions after
bare trigger words when the client advertises `completionItem.snippetSupport`. The
server uses the editor helper operation `sase editor helper-bridge snippet-catalog` as
the authoritative source and falls back to native Rust loading only for simple snippets
if the helper is unavailable. Clients without snippet support do not receive these
entries, because raw `$1` / `$0` markers would not behave like sase's TUI tabstops.

### Save location picker

Starting a new mini-macro (`gx`, `Ctrl+G x`, `Ctrl+G Ctrl+X`) or a new snippet (`gt`,
`Ctrl+G t`) first shows a location picker: one panel that asks where the new entry
should live. The picker opens synchronously, before any disk reads, so keys typed while
destinations load are buffered and applied — never dropped into the prompt pane.

An **Existing** section sits at the top of the list, always in the same place: `e` opens
a fuzzy finder over every physical definition (`✎ Edit existing macro…` /
`✎ Edit existing snippet…`). While a pane of that kind is already open the row reads
`Switch to existing …` instead. The Existing row is never the `★` default. With zero
definitions it stays visible but disabled (`no macros yet` / `no snippets yet`).

One keypress picks a destination and `Enter` accepts the `★` default, whose reason is
shown (`★ current`, `★ last used`, `★ configured`, `★ default`, `★ override`). `j`/`k`
(or `↑`/`↓`, `Ctrl+N`/`Ctrl+P`) move the highlight and skip headers and unavailable
rows; `Esc` (or `q`) cancels and returns focus to the origin pane.

Hotkeys are mnemonic and scope-first: `e` is existing, `p` is the project destination,
and `h` is the home destination in both pickers. In the mini-macro picker the Shift
variant picks the config file of the same scope.

If the prompt pane that opened the picker is gone before you choose — closed, or no
longer in the stack — the picker closes and sase's TUI warns
`Prompt pane is no longer available - snippet discarded` or
`Prompt pane is no longer available - mini-macro discarded`. A destination load that
fails stays on the picker and replaces the list with one red error row. For a snippet
that row and the error toast both read `Failed to prepare snippet pane: …`. For a
mini-macro the row reads `Failed to load destinations: …` and the error toast reads
`Failed to prepare mini-macro pane: …`. Cancel still returns to the origin pane when
that pane is still there.

| Picker  | Key   | Destination                                            |
| ------- | ----- | ------------------------------------------------------ |
| both    | `e`   | Existing-definition fuzzy finder                       |
| macro   | `p`   | Project `sase/macros/` directory (`#<project>/…`)      |
| macro   | `P`   | Project `sase/sase.yml`                                |
| macro   | `h`   | Home `~/sase/macros/` directory                        |
| macro   | `H`   | User `sase.yml`                                        |
| macro   | `1–9` | Other Project/Home rows in display order               |
| snippet | `p`   | Project `sase/sase.yml`                                |
| snippet | `h`   | User `sase.yml`                                        |
| snippet | `c`   | Configured `ace.snippet_config_path` (own top section) |
| snippet | `1–9` | User `sase_*.yml` overlays in display order            |

The default (↵) precedence is:

- **Mini-macro:** `★ current` (the open pane's location when retargeting) →
  `★ last used` → `★ default` on the Project directory (the Home directory in home mode)
  → the first writable row.
- **Snippet:** `★ current` (the open pane's location when renaming) → `★ configured` (an
  explicit `ace.snippet_config_path`, which outranks last-used) → `★ last used` →
  `★ default` on the resolved default file → the first writable row.

The footer previews each destination
(`→ <dir>/<name>.md · called as #<ns>/<name> · N macros here` for directories,
`→ <file> · ace.snippets.<trigger> · N snippets here` for snippets). The Existing row
previews
`→ fuzzy-find N macros across M files · edit in place or override read-only ones`. Rows
that already define the typed name show `has #name` / `has ⇥ trigger`. Choosing a
destination locks it for the name step: the old destination cycling is gone, and `⇧Tab`
in the name step goes back to the picker while keeping the typed text. Writable plugin
and built-in rows stay collapsed behind one `Plugins & built-in` summary row (`+`,
`Enter`, or a click toggles it), so plain users never see clutter.

#### Existing-definition finder

`e` opens a two-pane finder: matches on the left, a preview on the right. Type to
filter; `↑`/`↓`/`Ctrl+N`/`Ctrl+P` move the highlight while focus stays in the query;
`Enter` opens the highlighted row; `Ctrl+D`/`Ctrl+U` scroll the preview; `⇧Tab` returns
to the location picker (the query is remembered for the next `e`); `Esc` cancels. Keys
typed as type-ahead after `e` while the picker is still loading become the finder's
initial query.

Each row is one physical definition. Status chips:

| Chip                                                            | Meaning                               | Enter                                                            |
| --------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------- |
| `● active`                                                      | Runtime winner, writable              | Edit in place                                                    |
| `◐ shadowed`                                                    | Writable, but another definition wins | Edit in place, with a warning                                    |
| `🔒 built-in` / `🔒 plugin` / `🔒 read-only` / `🔒 from #macro` | Not writable here                     | Override detour: pick a writable destination, then the name step |
| `✗ swarm` / `✗ workflow` / `✗ skill` / `✗ memory`               | Not a simple mini target              | Refused; the verdict explains why                                |

An in-place edit opens the mini-macro or snippet pane on that definition's body. If a
pane of the same kind is already open, picking a definition replaces the draft (body,
frontmatter, and target) after the usual discard confirmation when the draft is dirty.
Picking the definition the pane already targets just focuses it and reports
`Already editing #name`. A read-only pick reopens the location picker in **override
mode**: the Existing row is hidden, destinations that would change the callable name are
disabled, rows that would still lose after save are badged `⚠ shadowed by …`, and the
default is badged `★ override`. `⇧Tab` from that name step returns to the override
picker, not the original one.

### Authoring a snippet from the prompt bar

`gt` (NORMAL), `Ctrl+G t`, or `Ctrl+G Ctrl+T` (INSERT or NORMAL) opens a dedicated
snippet pane at the bottom of the prompt input stack, a faster loop than the general
save panel above when you already know you're authoring a trigger:

1. **Choose where.** `gt` first shows the [location picker](#save-location-picker): one
   keypress picks the config file and `Enter` accepts the `★` default. Press `e` to
   fuzzy-find an existing snippet and edit it in place, or start a guided override when
   the definition is read-only. Keys typed while the destinations load are kept as
   type-ahead for the next step.
2. **Name it.** The trigger-name panel shows the locked destination (`⇧Tab` goes back to
   change it): type a trigger and it validates live, lists up to six existing triggers
   that share your typed prefix (`Tab` completes to the highlighted one, and `↑`/`↓` or
   `Ctrl+P`/`Ctrl+N` move that highlight). The verdict line reports one of: an invalid
   trigger; `✓ Create` for a fresh trigger; a warning that the trigger already exists in
   the destination (`Enter` will load it for editing); a warning that it's defined in a
   different config file (saving here will shadow or be shadowed by that file, per your
   project's precedence); or a warning that the trigger is derived from a macro and this
   entry will override it.
3. **Open the pane.** `Enter` opens the snippet pane — empty for a new trigger, or
   pre-filled with the current definition (from the destination, the shadowing file, or
   the derived macro template) when the trigger already exists. The pane always opens in
   INSERT mode and is unmistakably not a prompt pane: its own separator rule names the
   `⇥ <trigger>` and destination, with a state marker (`✓` clean, `●` dirty, `new` for
   an unsaved trigger), and its own accent color and subtitle. It is never included in a
   launch, a stash, or a save-as — `Enter` in it means "save the snippet", not "submit
   the stack".
4. **Save it.** `Enter` in the pane opens the save confirmation, showing `[Draft]` for a
   brand-new trigger or opening straight on `Diff` — a real `difflib` unified diff
   against the existing entry — for an overwrite (`Ctrl+O` cycles Draft / Existing /
   Diff, `Ctrl+D`/`Ctrl+U` scroll). An empty body refuses to save; a byte-identical
   overwrite reports `✓ No changes` and closes without writing; a destination that
   changed on disk since the pane opened warns and offers `r` to reload the current
   definition instead of overwriting blindly. `Enter` writes the file, publishes the new
   template to every open prompt input in the session immediately (no restart needed),
   and closes the pane only once the write succeeds — a failed write leaves the draft in
   place to retry.
5. **Follow-ups.** A successful save runs the same post-write chooser as the general
   save panel: an optional commit & push, and — for a chezmoi-managed destination — a
   scoped `chezmoi apply` limited to the deployed snippet file.
6. **Discard or rename.** `Ctrl+C` discards the pane; if you've typed anything different
   from the loaded body, a confirmation guards against losing it. `Esc` returns to
   NORMAL mode without discarding. `gt` again while the pane is open shows the location
   picker first (defaulting to the pane's current file), then re-opens the trigger-name
   panel prefilled with the current trigger to rename or re-target it without touching
   the body you've written. On close (saved or discarded), focus and the cursor return
   to exactly the pane and position you were at before `gt`.

### Macro Picker (`#@`)

Typing `#@` (the `#` character followed by `@`) opens the Macro snippet picker modal.
This lists all available macros (including project-local macros from `sase/sase.yml`
files) and inserts the selected reference at the cursor position. Inline-capable macros
and workflows insert as `#name`; standalone workflows insert as `#!name`. The picker
uses the same argument-aware skeletons as macro completion, so typed inputs can be
filled immediately after selection. Markdown macro swarms are inline-capable and insert
as `#name`. This is separate from the `ace.snippets` mechanism — it provides quick
access to macro references rather than expanding static templates.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt input](prompt-input.md) — insert mode, alt-brace, search, and macro editing.
- [Prompt completion panels](prompt-completion-panels.md) — glossary, memory, snippets, repos, and spellcheck.
- [Macros](../macros/index.md) — reusable prompts and directives.
