---
title: Prompt completion panels
description: Glossary, memory, snippets, repo-name, and spellcheck completion panels in the sase TUI prompt.
---

# Prompt completion panels

This page lists the glossary, memory, snippets, repo-name, and spellcheck completion
panels in the sase TUI prompt widget.

## Glossary terms

Project glossary entries are authored as strand files under `sase/memory/glossary/`, one
term per strand file, described by the `sase/memory/glossary.md` web descriptor; see
[Memory Webs](../memory/memory.md#memory-webs). sase's TUI highlights matched
glossary phrases in the prompt after the catalog is warm, rendering them bold,
underlined, and in a muted blue so they read apart from the lavender repo-name highlight
— the same "you can preview this with `K` or jump to it with `Ctrl+]`" affordance, a
different hue. Matching skips inline code and fenced code and uses the shared
longest-match rules from the macro LSP. Loading, validation, and matcher compilation run
off the render path and are cached per project/source signature. Strand edits, project
changes, and watched memory changes invalidate the cache.

`K` on a glossary phrase opens a compact definition card. The title shows the canonical
term and discloses the matched phrase only when you opened an alias. The body renders
the definition as prose, followed by display-alias chips, numbered `SEE ALSO` chips for
glossary terms mentioned by the definition, and a property grid for project, source, and
match count. Press `1`-`9` to follow a `SEE ALSO` term in place and `Backspace` to walk
back through the card history. `y` copies the definition, while `Y`, `o`, and `Z` copy
the source path, open the owning strand file's definition line in `$EDITOR`, or hand the
file to the artifact viewer when a source path is available. `Ctrl+]` opens the
project-local strand file's definition range through the normal editor/tmux jump flow.
If the catalog is still loading, sase's TUI schedules a warm and asks you to retry
rather than falling through to word lookup or an unrelated jump target.

The card's `SEE ALSO` chips are the depth-1 case of the same closure resolver behind
`sase memory show`/`read glossary:<keyword>` (see
[Memory Webs](../memory/memory.md#memory-webs)): both walk outgoing reference
spans from the shared `sase.memory.web.resolution` module, so the preview card and the
CLI can never disagree about which terms a definition references.

## Memory panel {#memory-panel}

The **Memory panel** is the browse-and-edit surface for SASE memory notes, webs, and
strands -- the Markdown files under a content root's `sase/memory/` (see
[Memory](../memory/memory.md)). From a prompt pane, press `gm` in NORMAL mode or
`Ctrl+G m` in INSERT or NORMAL. `K` previews one highlighted glossary phrase in place
(see [Glossary terms](#glossary-terms)); `gG` in NORMAL mode or `Ctrl+G G` in INSERT or
NORMAL opens this same panel seeded on the glossary strand under the cursor, or on the
`glossary` web when the cursor is not on a highlighted term. The which-key hint row
lists `memory…` on both prefixes. If the cursor sits on a `#memory/<stem>` macro
reference, that note is selected; otherwise the panel opens on the first note. Closing
with `Esc` or `q` restores the prompt pane and the vim mode you left.

The header reads `MEMORY · <scope> · N notes · scope i/N`, always using the configured
`PROJECT_NAME:` for a project scope, never a `ProjectSpec` key, plus a right-aligned
`⚠ UNPUBLISHED` badge once this scope has panel writes that have not been published (see
below).

The note rail is a tree, not a flat list, so the `parent` edge is visible before you
follow any link: core (`type: core`) notes sort first by priority then path, then memory
webs (such as `glossary`) sort by priority then slug, then reference (`type: reference`)
root notes sort alphabetically, each immediately followed by its children indented one
level under a `└ ` mark. `toggle_web` (`space`) expands or collapses a web row in place,
nesting its strands one level deeper the same way note children nest. Each row shows `●`
for a core note, `○` for a reference note, or `◆` for a memory web, then `⚙` for a
generated note and `⚠` for a note with an invalid `type` or `parent`, then the stem and
a dim description snippet.

Two navigation axes stay synchronized:

- **Tree.** `j`/`k` move the note rail cursor; the note card follows. `g`/`G` jump to
  the first and last note. `next_strand`/`prev_strand` (`s`/`S`) jump the cursor
  directly between an expanded web's strands without walking every intervening row. `/`
  filters notes by stem and description; `>` extends the match into note bodies. `Esc`
  closes the filter and keeps the selection when it is still visible. An empty result
  reads `no notes matched: <pattern>`.
- **Relational.** An ordinary note's card carries a numbered `PARENT` chip (omitted when
  the parent is `AGENTS.md` rather than another memory note) and numbered `CHILDREN`
  chips. A strand's card carries the same chip row labeled `SEE ALSO` (outbound) and
  `REFERENCED BY` (inbound) instead, when its web sets `link_reference: implicit` — the
  same mention graph `sase memory read`'s depth-limited resolution walks, plus the
  same-web `[[target]]` links the strand bodies author (see
  [Memory Webs](../memory/memory.md#memory-webs) and
  [Memory Links](../memory/memory.md#memory-links)). Numbering is continuous
  across both rows so `.1`–`.9` is never ambiguous. `Tab` / `Shift+Tab` move a chip
  cursor, and `l` follows the focused chip -- or chip ① when none is focused. `.` then
  `1`–`9` jumps straight to a numbered chip. Following pushes the previous note onto a
  trail bounded at 32 entries and clears an active filter when the target is hidden. `h`
  or `Backspace` walks back. A non-empty trail renders as `TRAIL  a › b › c` above the
  footer. On the embedded Admin Center Config sub-tab, bare `1`–`9` remain top-level
  Admin Center tab selectors.

`follow_link` ships as `enter,l`, but only `l` currently follows a chip: the note rail
holds focus and consumes `Enter` for its own selection action. Use `l` or `.1`–`.9`.

The note card also shows a badge row (`CORE · always loaded` /
`REFERENCE · read on demand`, plus `GENERATED`, `SHADOWS HOME`, `ORPHANED`, and
`INVALID` when they apply), the description, the rendered Markdown body, and a property
grid: type, parent, child count, size (lines and approximate tokens), last modified,
last audited read, and the on-disk source path. A web row instead shows `WEB` plus
`EXPANDED`/`COLLAPSED`, and its property grid names strand count and scope -- a web
descriptor declares no `type:`, so there is no rendering-type row.

The card head is pinned: the title row plus the path line with the pager's state pill
(`NOW`, `uncommitted`, `UNTRACKED`, `NO VCS`), then a reserved two-row time strip (one
row on short cards). At clean now the second row names what changed last; honest states
use the pager's exact words. `(` and `)` step the card through committed versions (`{`
jumps to the first, `}` returns to now); a violet frame marks the past and `Esc` returns
to now before closing. `=` toggles a sticky word-diff view: the shown version against
its parent, the latest change at clean now, or pending edits at dirty now. `H` opens the
selection in the pager at the card's exact version and view, and `C` opens the Changes
lens (below). A strand row shows `STRAND`, plus `AUDITED`, `AUDITING`, or `AUDIT FAILED`
once the panel has recorded (or tried to record) an audited read for it: selecting a
strand's card records an audited read the same way `sase memory read <web>:<keyword>`
does, so previewing a strand in the panel is itself an attributable access, not a silent
peek.

`@` turns the rail into the selected subject's timeline: one row per version in the
pager picker's exact cells, with `▸` on the cursor, `●` on the version the card showed
when the lens opened, and `◇` on the compare base. The highlight moves at once while the
card previews through the usual 150 ms debounce (a `loading vN…` strip covers the
fetch); rail motion pushes no trail entries and never changes the Notes filter. `b`
marks the cursor row as the compare base (again clears it); the footer reads
`Compare vA → vB · b clear`, oldest first, or `Same version`. `.` reveals hidden
versions (chip shortcuts are inert in the lens) and `/` filters the version rows. `⏎`,
`l`, and `H` open the pager at the cursor's pin, view, and base -- a `now` target can
compare against a committed base. Leaving (`Esc`, `@`, or `h`) restores the Notes rail
exactly (cursor, filter, expansion, trail) while the card stays on the cursor's version,
so a second `Esc` returns it to now. `C` is inert inside the lens, and `r` or a scope
switch leaves the lens first. Clicking the time strip opens the lens.

`C` turns the rail into a day-grouped Changes review of the current scope (or
`All scopes` via `p`/`P`, which gains that lens-only entry): one row per changeset with
its clock time, first authored subject plus `+N more`, word delta, and `⌂` for home,
under `Today`/`Yesterday`/weekday headers that `j`/`k` skip. Regen-only changesets fold
into one count row per day, and the trailing `··· N older` row extends the 100-row
window by 100. The card shows the commit subject, `◈` bead / `⬡` agent / `◉` commit
provenance chips, subject totals, and one titled diff section per authored subject (at
most six inline, then `+N more`), filling progressively with stale loads dropped. `⏎`,
`l`, and `H` open the first authored subject in the pager diff view at that changeset's
version (`.1`–`.9` open subject N); `/` filters every fetched changeset by commit
subject, subject names, bead, and agent; `r` refetches. Leaving (`Esc`, `C`, or `h`)
restores the Notes rail exactly, and `@` is inert inside the lens. A scope that fails
(or has no VCS) shows as a header chip instead of being silently dropped.

Every Notes rail row ends with a recency glance: the newest change's class glyph and
compact age (`⇧ 8d`, `◆ 3h`, `⟳ 1h`), right-aligned and built off-thread from one
`subjects()` plus one `feed()` per scope load, so rows paint first and gain the column
when the map lands (a failed load omits the column and keeps the rail). Promotions
`⇧`/`⇩` keep their highlight; narrow rails shed the age first, then the glyph, and the
stem never wraps. `D` toggles a trailing `DELETED` group of subjects whose latest entry
is a deletion (newest deletion first; a deleted-then-recreated subject is not listed):
rows read `✖ name   deleted 3w`, the header gains `· N deleted`, and each card is the
tombstone -- the `✖ DELETED` pill, a deleted-style frame, the tombstone strip row, and
the last content. Tombstones are read-only (`(`/`{` step older, `@` and `H` work).

A collapsed `▸ INSTRUCTIONS · N` group closes the Notes rail, listing every `AGENTS.md`
instruction file (plus provider shims) with `≡ N shims`, `⚠ diverged`, and `TEMPLATE`
chips where they apply. `space` toggles it; the group header itself selects nothing.
Instruction cards are read-only -- managed files refuse edits
(`rendered from memory · edit its source notes`), hand-written ones point at `o` -- and
carry the pager's cause row instead of a meaning row. Stepping (`(`/`)`/`{`/`}`), diff
(`=`), the Timeline lens (`@`), and the pager hand-off (`H`) all work on instruction
rows exactly as on notes.

The Changes header leads with a review chip from the per-scope watermark: `● N new`,
`not reviewed yet · m to mark`, or `✓ nothing new` (omitted when the review state is
unavailable). Rows for changesets newer than the watermark carry a `●` dot. `m` marks
the shown scope reviewed -- optimistic, persisted off-thread -- and toasts
`marked N changesets reviewed`. The Config hub `MEMORY` sub-tab badges the same count
(`●N`), quiet until there is something new.

Memory history reaches the Agents tab too: the `SASE CONTEXT` / `MEMORY` lane appends a
version chip to each audited read with a captured blob -- dim `≡ now`, `vK ⟲ N newer`,
amber `◌ uncommitted at read`, or one `⟲ N of M changed` aggregate for a batch read --
and leads with an as-launched row: the recorded root bundle
(`Instructions as launched · NN-<provider>`) when delivery was `explicit`, or
the workspace `AGENTS.md` snapshot for native, fallback, and earlier runs
(`◌ as launched · not in git` or `snapshot unavailable` when it cannot match a commit).
Chips load in a later off-thread pass and append at the row end, so they never delay or
reflow the lane. A `v` hint on a chipped row opens the pager pinned to the version read;
see [Memory History](../memory/history.md#in-the-tui).

`p` and `P` cycle the scope ring -- every enabled project with a memory root, the
project you opened from even when it has none (so `a` can bootstrap it), and one `Home`
scope resolved through the active
[`use_chezmoi`](../config/core-behavior.md#usechezmoi) mode, always ordered by
display name with `Home` last. Precedence for the starting scope is the prompt's
launch-workspace project, then the [current project](projects-tab.md#current-project) when it appears
in the ring, then the first ring entry. Switching scopes clears the trail and the filter
and restores that scope's last-selected note for the life of the panel. `Ctrl+P` opens a
filterable scope picker showing each scope's display name and note count, for reaching a
scope with many registered projects without cycling through all of them.

`a` and `d` branch on the selected row. On an ordinary note row, `a` opens an add form
(stem, type, parent, and description) with live validation; the parent list offers
`AGENTS.md` plus every reference note in the scope, illegal stems, types, parents, and
parent cycles are rejected before any write, and a successful create offers to open the
new note's body in `$EDITOR`. `e` opens the same form pre-filled to retype, reparent, or
redescribe the selected note; the note body itself is not edited in the panel -- press
`o` to open it in `$EDITOR` instead. `d` confirms and deletes the selected note;
deleting a note that still has children is refused with an explanation of which children
must be reparented first, and deleting a `short` note warns that always-loaded agent
context is being removed. On a web row, `a` opens an add-strand form (keyword, optional
comma-separated aliases, optional summary, body) with the same live-validation shape,
against the same mutation engine described in
[Memory Webs](../memory/memory.md#memory-webs). On a strand row, `d` confirms and
deletes that strand, showing its relative path, keyword, aliases, the first line of its
body, and any inbound `Referenced by` strands before anything is written; there is no
strand edit form -- press `o` to open the strand file in `$EDITOR` instead. Every delete
leaves a timestamped backup and the success toast names it. A generated note
(`sase/memory/sase.md` and the project-only `task_types.md` / `sase_artifacts.md` /
`sase_beads.md` / `sase_sizes.md`) renders its `GENERATED` badge and refuses edit or
delete with an explanation; `sase/memory/glossary.md` and every other web descriptor are
ordinary user-owned notes, not generated ones. A concurrent external edit is caught as a
conflict: the write is refused, the panel toasts, and the scope reloads instead of
silently overwriting the change.

Every successful write marks its scope `UNPUBLISHED`, because the write is not visible
to agents until `sase memory init` regenerates `AGENTS.md`, the provider shims, and the
memory README. `I` -- also offered automatically right after a write -- opens a publish
confirmation with a prefilled, editable commit subject and two explicit choices:
**Publish & commit** runs `sase memory init --message "<subject>"`, and **Publish only**
runs `sase memory init --no-commit`. Both run as a captured, non-interactive command in
the scope's content root (`Home` for the Home scope); a failure surfaces the captured
error and leaves the badge set, while success clears it.

A scope with a memory root but no notes shows a centered invitation naming the scope and
pointing at `a`. A scope with no memory root yet says `sase/memory/` will be created on
the first add. A scope whose read root collided or failed to load shows its diagnostics
and the offending paths instead of a note card.

Passive keys: `o` opens the note body in `$EDITOR` and re-checks it for a conflicting
change on return; `Z` hands the source file to the artifact viewer; `y` copies the note
body and `Y` the source path; `r` re-reads the current scope; `?` opens a panel-scoped
help overlay.

The panel footer lists only conditional keys: scope keys when the ring has more than one
scope, link keys when chips exist, back when a trail exists, edit/delete when a writable
note is selected, and publish when the scope is unpublished. Always-available keys live
in `?` and in this guide.

Most keys named above are remappable under
[`ace.keymaps.memory`](../config/ace-keymap-configuration.md#acekeymaps); see
[Remapping Memory Panel Keys](global-controls.md#remapping-memory-panel-keys). Three sets are fixed and
are not part of that scope: `Esc` and `q` (close), the `.` then `1`–`9` link-chip
shortcuts, and the `↑`/`↓`/`Home`/`End`/`PageUp`/`PageDown` cursor keys the underlying
list widget supplies alongside the configurable `j`/`k`/`g`/`G`.

## Snippets panel {#snippets-panel}

The **Snippets panel** is the browse-and-edit surface for one project's composed snippet
catalog — the same catalog `sase snippet`, prompt expansion, and the editor helper use
(see [Snippets](snippets.md#snippets-1)). From a prompt pane, press `gT` in NORMAL mode or `Ctrl+G T`
in INSERT or NORMAL. Lowercase `gt` / `Ctrl+G t` / `Ctrl+G Ctrl+T` still opens the
snippet target pane. The which-key hint row lists `snippets…` on both prefixes. If the
cursor sits on a `#[trigger]` call or a bare trigger that is already in the in-memory
catalog, that entry is selected; otherwise the panel opens on the first visible entry.
Closing with `Esc` or `q` restores the prompt pane, vim mode, selection, and cursor.

The header reads `SNIPPETS · <project> · N snippets · project i/N` and always uses the
configured `PROJECT_NAME:`, never a `ProjectSpec` key. Generated initial-capital aliases
are metadata on their source entry, not extra rail rows. Macro-derived entries are
viewable and linkable but source-edited: `e` opens the real macro definition instead of
converting a generated template back into Jinja.

Two navigation axes stay synchronized:

- **Alphabetical.** `j`/`k` move the trigger-list cursor; the card follows. `g`/`G` jump
  to the first and last trigger. `/` filters triggers and source labels; `.` extends the
  match into raw and composed bodies. An empty result reads
  `no snippets matched: <pattern>`.
- **Relational.** The card keeps the authored template and composed expansion distinct,
  highlights `$0`/`$N` tabstops and `#[...]` call sites, and carries numbered `CALLS`
  chips (outbound) and `CALLED BY` chips (inbound). Alias calls land on the canonical
  explicit trigger. Missing targets and cycles stay visible as non-followable
  diagnostics. `Tab` / `Shift+Tab` move a chip cursor, `l` follows, and `1`–`9` jump
  straight to a numbered chip. Following a hidden match clears the filter with a toast.
  `h` or `Backspace` walks a trail bounded at 32 entries.

`p` and `P` cycle the enabled-project ring. Order is by display name. Switching projects
clears the trail and the filter and restores that project's last-selected trigger for
the life of the panel.

`a` opens a trigger/template form with live trigger and link diagnostics, destination
cycling (`Ctrl+N` / `Ctrl+P`), a composed preview, and explicit collision wording
(replace vs shadow). `e` preloads an authored config template and its source
fingerprint; on a macro entry it opens the real source. `d` confirms a delete naming
backlinks, the exact file being changed, and any lower-priority definition that will
become effective. Writes use the same engine as `sase snippet add` / `delete`, run as
tracked procs with one exclusive scope per project and destination, refresh the panel,
publish the change to every mounted prompt immediately (including removing a pending
session overlay on delete), and offer the usual commit/push and scoped chezmoi-apply
follow-ups. A stale-write conflict keeps the draft and offers reload. A failed write
leaves the panel open and unchanged.

A project with no snippets shows a centered empty state. A project whose catalog failed
to load shows the diagnostics. `?` opens a panel-scoped help overlay. `y` copies the raw
template, `Y` copies the source path, `o` opens the source in `$EDITOR`, `Z` hands the
file to the artifact viewer, and `r` re-reads the current project.

The panel footer lists only conditional keys: `e`/`d` when the selected definition is
writable config, relation keys when chips exist, `p`/`P` when the ring has more than one
project, and back when a trail exists. Always-available keys live in `?` and in this
guide.

Most keys named above are remappable under
[`ace.keymaps.snippets`](../config/ace-keymap-configuration.md#acekeymaps); see
[Remapping Snippets Panel Keys](global-controls.md#remapping-snippets-panel-keys). Three sets are fixed
and are not part of that scope: `Esc` and `q` (close), the `1`–`9` relation-chip
shortcuts, and the `↑`/`↓`/`Home`/`End`/`PageUp`/`PageDown` cursor keys the underlying
list widget supplies alongside the configurable `j`/`k`/`g`/`G`.

## Repo names

sase's TUI highlights the unambiguous identifier of every non-primary repo in the active
project — linked names (`sase-core`), sidecar slugs (`sase--beads`), and external names
(`gh:owner/repo`) — after the catalog is warm. Matches are bold, underlined, and
lavender. The project's own primary name, sidecar role words (`beads`, `plans`), and any
name the project glossary already claims are left as ordinary text so the two overlays
never fight over the same characters.

Matching skips inline and fenced code, ignores path-adjacent hits (`../sase-core`,
`sase-core/crates`), and drops the matcher's derived plurals so the highlighted
characters always equal a real identifier. Loading and compilation run off the render
path and are cached per project. Config edits, project changes, and watched `sase.yml`
changes invalidate the cache. A repo opened with `sase repo open` during a live sase's
TUI session does not appear until the next config-driven invalidation.

`K` on a repo mention opens a compact repo card: kind, description, checkout path, clone
coverage, remote URL, and where the repo is declared. The title shows the repo
identifier and discloses the matched text only when it differs in case from the
identifier — the exact-identifier filter above rules out any other difference. Chips
mark the kind, plus `AUTO-CLONE` and/or `AUTO-SYNC` when set, and `ENV <name>` when the
record has one. `Checkout` prefers the clone registered for the active workspace, else
the record's own path; when that path does not exist locally it is suffixed
` (not cloned)` and the card prints the exact `sase repo open <name>` command as a hint
— sase's TUI never runs that command itself. `Clones` shows
`<existing> of <registered> workspaces` when the repo has clone records, and rows whose
value is unknown (no remote, no declaration site) are omitted rather than shown empty.
`y` copies the description, `p` copies the checkout path, and `Y`, `o`, and `Z` copy the
declaration path, open the owning `sase.yml` line in `$EDITOR`, or hand the file to the
artifact viewer — all three warn cleanly for an external repo, which has no declaration
site. If the catalog is still loading, sase's TUI schedules a warm and asks you to retry
rather than falling through to word lookup or an unrelated jump target.

`Ctrl+]` on a repo mention opens the resolved checkout — the clone registered for the
active workspace, else the record's own path — in `$EDITOR` or a new tmux pane through
the normal jump action chooser, which gains a `c` — Open declaration choice whenever the
repo has one (external repos do not). When the checkout is not cloned in the active
workspace, `Ctrl+]` notifies that the repo is not cloned and prints the exact
`sase repo open <name>` command to run instead of offering to open a path that does not
exist: it opens the declaration directly when one exists, or just notifies with no
chooser at all for an external repo. sase's TUI never runs `sase repo open` itself.

## Word definitions & spellcheck

When no macro, slash skill, workflow, or file target matches, `K` treats a plain
natural-language word that is not a glossary match as a lookup target. Correctly spelled
words open a dictionary card: the headword pill and the highlighted first definition
with its source attribution stay pinned on top, and the cleaned per-source entries
scroll below. When the displayed headword differs from the word under the cursor, a
`looked up` disclosure names the original word. Use `j` / `k`, `Ctrl+D` / `Ctrl+U`, and
`g` / `G` to navigate the entries, and press `y` to copy the highlighted definition.
Misspelled words open a compact correction panel: press `1`–`9` to apply a suggestion
immediately, or move with `j` / `k` and press `Enter`. The replacement is an ordinary
undoable prompt edit.

Definitions require the optional `dict` command. Spell checking requires GNU `aspell`
with an English dictionary (`aspell-en` on Debian; Homebrew's package bundles English).
If either tool is absent, sase's TUI explains the unavailable feature without affecting
the rest of prompt preview. Run `sase doctor -D` to see the exact optional-tool status
and installation hint.

Every word `K` proves misspelled is remembered durably and gets a red underline in every
prompt input from that moment on, in every `sase tui` session -- no live spell-checking
runs on every keystroke; only what `K` has already checked is ever squiggled. This is
distinct from the bold blue glossary underline and the bold lavender repo-name
underline, which mark a definable project term or repo rather than a spelling issue. The
correction panel offers two ways to stop fighting a word, at two different scopes. Press
`a` to accept a word for SASE only: it is recorded in `prompt_misspellings.json`, `K` on
it does not open the panel, but `aspell` itself -- and every other consumer of it on
the machine -- still rejects the word. Press `d` to add the word to your `aspell`
personal dictionary instead (usually `~/.aspell.en.pws`, though `aspell` configuration
can relocate it), so it stops being flagged everywhere on the machine, not just in
sase's TUI; this is reversible by editing that file directly. The add is verified by
re-checking the word in a fresh `aspell` process afterwards, so the squiggle clears only
once `aspell` genuinely accepts it -- a failure leaves the word flagged and reports
`aspell`'s own explanation. Case follows `aspell`: a word added capitalized (`Bugyi`)
stays flagged in lowercase (`bugyi`). Hyphenated words cannot be added with `d` --
`aspell` does not permit `-` inside a personal-dictionary entry -- and the panel reports
that explicitly rather than pretending the add worked. A `K` press on a
now-correctly-spelled remembered word clears its squiggle automatically. The remembered
words are stored at `sase_home()/prompt_misspellings.json`; see
[`ace.prompt_spellcheck`](../config/ace-prompts.md#acepromptspellcheck) to
disable the highlight or change how many words are retained.

sase's TUI also computes a non-disruptive live suggestion after a short debounce while
the prompt input is in INSERT mode. The suggestion appears in the prompt bar subtitle as
`[^L] accept ...`; press `Ctrl+L` to accept it. `Enter` still submits the prompt as
typed, so live suggestions cannot accidentally replace text on send.

Live soft completion covers directives, macro names, macro argument names, and enum/bool
argument values from the same shared choice rows. File-path soft completion is disabled
by default because it can scan the filesystem while typing; enable it with
`ace.prompt_completion.auto_file_paths: true`. The macro/skill menu also opens
automatically while typing matching `#name`, `#!name`, or `/skill` tokens; disable that
macro auto-open behavior with `ace.prompt_completion.auto_macro_menu: false`. The
directive menu likewise opens automatically while typing matching `%` directive tokens,
fixed values such as `%model:`, and `=alias` / `==model` shortcuts; disable it with
`ace.prompt_completion.auto_directive_menu: false`. That setting is sase's TUI-only and
does not change macro LSP trigger characters in an external editor. The macro/skill
auto-menu opens only once at least one identifier character follows its marker, so bare
`#` and `/` stay quiet. Directive completion opens from a valid bare `%`, and no
automatic menu ever auto-accepts a single match. The grouped `@` reference menu opens
from a bare `@`, narrowed artifact/file queries such as `@pl` or `@src/`, and
syntactically valid `@kind:` payload contexts; disable automatic opening with
`ace.prompt_completion.auto_artifact_menu: false`. On an un-narrowed bare-`@` menu,
`Enter` submits the prompt as typed and `Ctrl+F` accepts the highlighted first row. The
project/Patch picker opens when `+` completes a token at the start of the prompt or
directly after whitespace, `{`, or `|`, and is also available through manual `Ctrl+T`.
The VCS ref-root menu opens when `:` or `(` completes a known workflow ref trigger such
as `#gh:` and local candidates exist. The VCS repository menu opens when `/` completes a
known workflow ref trigger such as `#gh:owner/`; cached rows appear immediately and
uncached namespaces fetch in a background worker. Placeholder auto-completion opens only
for an incomplete `<...` context; saved common placeholders join automatic results after
the prefix is non-empty, while manual `Ctrl+T` can show them from a bare `<`. Manual
`Ctrl+T` inserts a lone match in the highest-priority placeholder source group outright;
automatic completion only opens the menu, even for one match. Manual `Ctrl+T` completion
still supports file paths, macro names, directives, skills, `=alias` / `==model`
shortcuts, `@` references, project/Patch tags, VCS ref roots, VCS repository refs,
prompt-local prose words, placeholders, and enabled history words regardless of the
automatic settings. Live suggestions pause while the manual completion panel is open,
while snippet tabstops are active, in NORMAL mode, and during feedback prompts.

For file completion, directories appear before files in the candidate list. Dotfiles are
hidden unless the partial prefix starts with `.`. Accepting a directory automatically
re-opens completion for the next level (drill-down). The completion panel shows up to
eight candidates at a time — seven when more candidates remain, so the `↓ N more…` line
always fits, and one fewer again when the grouped `@` reference menu draws its
`── files · <base-dir>` rule — and scrolls to keep the highlight visible. When exactly
one macro or file candidate matches, accepting completion inserts the canonical
reference immediately.

Accepting a macro completion, or selecting a macro from the `#@` picker, opens an
`macro args` hint panel when the macro has required user-facing inputs. The panel shows
the supported arguments and highlights the active one. Press `:` while the accepted
reference is still current to switch to colon syntax, or press `(` to insert a
required-argument named snippet and use `Tab` to advance through the snippet fields.

The same smart insertion rules apply to `#@` selections and `Ctrl+T` completions. A
selected macro with no required inputs inserts a trailing space, a single required
non-text input inserts colon syntax, a single required text input inserts double-colon
shorthand, and multiple required inputs insert a parenthesized named-argument snippet.
When that trailing space sits at a live snippet tabstop and the next keystroke is `Tab`
or `Shift+Tab`, the jump removes the space on its way to the next tabstop; when the jump
has nowhere to go, the space is kept and ordinary snippet/list fallback continues.

The same hint panel appears while typing narrow, known argument forms such as `#name:`,
`#!name:`, `#ns/name:`, `#ns__name:`, `#name!!:`, `#name??:`, `#name(`, and
`#name(arg=`. The hint is advisory; the backend macro parser still owns expansion
semantics when the prompt is submitted. Detection intentionally stays conservative, so
prose shorthand, URLs, unknown macro names, `#name+`, and completed colon text such as
`#name: value` do not keep the prompt-bar hint open.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt completion](prompt-completion.md) — token completion and next-word prediction.
- [Snippets](snippets.md) — snippet expansion and the Macro Browser.
- [Memory](../memory/memory.md) — memory notes, webs, and audited reads.
