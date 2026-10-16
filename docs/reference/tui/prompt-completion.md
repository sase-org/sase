---
title: Prompt completion
description: Token completion in the sase TUI prompt widget, including next-word prediction.
---

# Prompt completion

This page lists token completion in the sase TUI prompt widget, including next-word
prediction.

## Completion

Press `Ctrl+T` to activate token completion. The completion kind is determined by the
token under the cursor:

- **Macro completion**: When the cursor is on a `#`-prefixed token (e.g., `#my_pro`),
  completion shows matching macro names from all discovery sources, including registered
  workspace workflow macros. Completion rows include the macro kind and visible typed
  inputs, with required arguments shown as `name: type` and optional arguments shown as
  `name?: type` plus a default when the default is a simple scalar. Standalone workflow
  references use the `#!name` insertion form; typing `#!` filters completion to entries
  whose canonical insertion starts with `#!`.
- **Project/Patch completion**: When the cursor is on a `+query` token whose plus is at
  the start of the prompt or directly after whitespace (including a newline or tab),
  `{`, or `|`, completion opens a project/Patch picker. A plus glued to other text
  (`a+b`, `c++`) and `#+query` are not project triggers. The picker contains enabled
  launchable projects plus active PR-sized Patches in `WIP`, `Draft`, `Ready`, or
  `Mailed` status; system-managed `home`, disabled projects, internal sibling backing
  records, and non-launchable projects are excluded. Typing after the trigger filters by
  project name, project alias, or Patch name prefix. Project rows show `+name` in the
  project's accent color with a `provider · #<workflow>:<name>` detail (the current
  project's row adds a `current` badge), ordered current project first, then most
  recently launched, then by name; Patch rows keep their `[PR]` badge. Accepting a
  project row places its `+<project>` tag (or `#<workflow>:<name>` for names outside tag
  syntax) at the earliest existing workspace target in that `---` segment, or at the
  segment's leading tag position when it has none — and a Patch row places
  `#<workflow>:<patch>` the same way. Either way, the other workspace targets in that
  segment are removed. See
  [Project Tags](../macros/reference-syntax.md#project-tags).
- **VCS ref completion**: When the cursor is inside the root segment of a registered VCS
  workflow ref, such as `#gh:`, `#gh:sa`, or `#git(`, completion lists that provider's
  projects and active PR-sized Patches. Providers can add namespace rows, such as GitHub
  organization rows, from local project/config data. Accepting a project or Patch
  completes only the current ref token, producing `#gh:sase ` in colon form or
  `#gh(sase)` in parenthesized form. Accepting a namespace inserts a trailing slash such
  as `#gh:sase-org/` and immediately hands off to repository completion.
- **VCS repository completion**: When the cursor is inside a registered VCS workflow ref
  that already contains an owner or namespace plus `/`, completion lists repositories
  for that namespace through the owning workspace plugin. For example, `#gh:bbugyi200/`
  opens GitHub repositories for `bbugyi200`, and `#gh:bbugyi200/sa` narrows locally or
  through the LSP client's filtering. Accepting a row replaces only the current ref
  value, producing `#gh:bbugyi200/sase ` in colon form or `#gh(bbugyi200/sase)` in
  parenthesized form. Failed or empty lookups show a placeholder row in sase's TUI;
  stale cached results are reused when a refresh fails.
- **Slash-skill completion**: When the cursor is on a slash-skill token such as `/` or
  `/sase_`, completion filters the same catalog to skill sources and inserts
  `/<skill_name>` — the provider name, not the `#` reference. The same source completes
  as `#skill/sase_plan` after a `#`, and both forms resolve one definition, so argument
  hints, previews, and jumps agree. Packaged built-in skills are included, so
  `/sase_plan`, `/sase_questions`, and other bundled SASE skills are available without a
  project-local skill file.
- **Macro argument completion**: When the cursor is inside a known macro argument
  position, `Ctrl+T` completes the active argument instead of the macro name. For `path`
  inputs it delegates to file path completion, for `enum` and `bool` inputs it offers
  the shared Rust choice menu (canonical values with labels, descriptions, and a quiet
  `default` badge; `true`/`false` for bools). `model` inputs use the `%model` menu,
  including aliases after `@`, provider drill-down, and effort choices after the model's
  `@` suffix. Typed `model` inputs open the existing model picker. Inside parenthesized
  syntax it completes missing `name=` arguments without repeating names already present
  in the argument list. Each keyword row shows the shared type label, its default when
  optional, and its description. `#m:` and `#m(k=` open the value menu immediately when
  the active input has choices or is typed `model`. Accepting a `name=` row chains
  straight into its value menu, even from a single-candidate name menu; auto-open shows
  the choice without accepting it, and empty-prefix menus keep declared order with the
  first row selected. Accepting a choice replaces the whole value element and inserts
  the canonical value (quoted when needed), preserving adjacent values and surrounding
  syntax. At a keyword slot (right after `#review(`, or after a comma and space in
  `#review(a=1,`), the keyword menu also opens automatically while typing (unless
  `ace.prompt_completion.auto_macro_menu` is off), and INSERT-mode `Ctrl+N` / `Ctrl+P`
  open it with the first / last keyword highlighted. Accepting a keyword immediately
  opens its value menu when the input has one (enum/bool values, agent targets, paths,
  or model values). `Enter` always submits the prompt as typed, even on an automatically
  opened first-row menu; `Ctrl+F` accepts the highlighted row without requiring
  `Ctrl+N`, `Down`, or another ownership signal. Agent inputs such as `#fork` offer
  agent, proc/monitor, session, clan, and `@tribe` targets with kind and member context.
  A proc or monitor row inserts its exact durable proc ID while displaying the friendly,
  reusable proc name. Session rows also show the associated plan or bead when SASE can
  resolve one: the row reads `<kind> · <phases/waves> · <title>` (for example
  `Epic · 5 phases · 2 waves · Bead review hardening`), and its plan title is
  searchable, so typing part of the title filters to that session. Selecting the row
  fills the panel subtitle with more of the same artifact — phase titles for an epic,
  the goal for a tale or plain plan, the parent title for a phase or task bead. When
  nothing resolves, the row falls back to a snippet of the session's launch prompt and
  the subtitle falls back to member names; completion is never blocked either way.
  Numeric inputs keep the type hint visible but do not invent values.
- **Frontmatter panel input editing**: The frontmatter panel edits `input:` rows one
  cell at a time as `name`, `type`, `choices`, `default`, `description`. Inline `enum`
  inputs author their value set in the `choices` cell with a flow list such as
  `[wip, draft, {value: ready, label: Ready}]`; any other type must leave `choices`
  empty. Compact local-macro inputs (`name:type[=default], ...`) keep the existing rich
  declaration (choice labels and descriptions, input description, repeatability, and
  role) and only apply the compact default. Press `R` for raw-YAML editing, or declare a
  new inline `enum` as a top-level input, when the compact list cannot carry its
  choices.
- **Jinja completion**: When the cursor is inside a Jinja `{{ }}` or `{% %}` tag, the
  Jinja menu owns completion ahead of every other surface: variables at expression
  positions, filters after `|`, tests after `is`, members after `<namespace>.`, and
  statement keywords (closers for open blocks first) at the head of `{% %}`. Rows show
  the name, type or signature, source badge (`input`, `local`, `sase`, `jinja`,
  `%repeat` / `%wait` for conditional names, `legacy`, `closes for`), and description;
  the border title names the slot (`{{ variables`, `| filters`, `is tests`,
  `{% statements`, or `<namespace> members`) plus the scope label when the pane is
  macro-bound. The menu opens automatically while typing inside a tag — right after `{{`
  / `{%` auto-pair, on `|` and `.`, and on identifier characters — unless
  `ace.prompt_completion.auto_jinja_menu` is off; manual `Ctrl+T` still works when off.
  With the menu off, an in-tag cursor still claims completion, so placeholder,
  directive, `@`, and `#` menus leave the tag alone. Next-word ghosts and peeks stay off
  for the whole tag, whether or not the Jinja menu is open. A `|` inside a tag always
  inserts literally as a filter pipe and never triggers `%{...}` alternation
  normalization. String literals and new-name positions (`{% set x`, `{% for x`) offer
  no menu, and the open menu suppresses the Jinja diagnostics panel so a momentarily
  empty `{{ }}` never flashes red.
- **Directive completion**: When the cursor is on a `%`-prefixed directive token (e.g.,
  `%m`), completion lists user-facing prompt directives and accepts aliases into their
  canonical forms. For example, `%m` completes to `%model` and `%w` completes to
  `%wait`. The same shared directive matrix used by the macro LSP is documented in
  [Directive Completion Matrix](../macros/directive-syntax.md#directive-completion-matrix):
  `%model` completes live model catalog rows, aliases, provider drill-down rows, and
  parenthesized alias keys; `%effort`, `%auto`, `%repeat`, and `%macros_enabled`
  complete their fixed values; `%id`, `%clan`, and `%wait(...)` complete their supported
  keyword names and keyword-value rows. `%wait:` never offers structured keywords, so
  `time=` and `bead=` appear only in parenthesized `%wait(...)`. `capacity=`,
  `priority=`/`p=`, and `weight=`/`w=` complete on `%queue`/`%q` only. Keyword
  completion suppresses duplicates and mutually exclusive keywords, and
  `%model(..., alias=...)` suppresses the alias's own `@alias` value, while manually
  typed values still flow to launch-time validation. Dynamic agent and bead rows come
  from sase's TUI warmed snapshots rather than synchronous prompt-bar bead-store reads;
  if a dynamic refresh is unavailable, static directive names, aliases, keyword rows,
  and fixed values remain available.
- **Model shortcuts**: When the cursor is on a `=alias` or `==model` token at the start
  of a logical line or immediately after a literal ASCII space, completion opens a model
  shortcut menu. `=alias` lists alias rows only; for example, typing `=la` can select
  `@large` and rewrite the whole token to `%m:@large`. `==model` lists concrete model
  rows only; for example, typing `==gpt` can select `gpt-6.1-sol` and rewrite the token
  to `%m:gpt-6.1-sol`, while provider-qualified input such as `==codex/g` narrows to
  that provider. The second equals sign switches an open alias shortcut panel into the
  explicit model panel. If the token already has a following ASCII space, sase's TUI
  reuses it and leaves the cursor after that space; before a tab it inserts no extra
  space; before a newline or prompt end it appends one ASCII space. Typing `@` directly
  after a colon-form `%m:<model> ` / `%model:<model> ` value and its single trailing
  space (at end of line or before whitespace) replaces the space with `@` and opens the
  effort-level menu (subject to `auto_directive_menu`); undo if you meant a literal `@`
  reference after the space. `Ctrl+F` and `Ctrl+L` accept the highlighted row; `Enter`
  submits the prompt as typed and dismisses the menu instead of expanding the shortcut.
  No matches dismiss the panel and leave the literal query text intact, so unknown
  equals tokens submit as ordinary prose. These shortcuts do not fire inside inline
  code, fenced code, frontmatter, placeholder/directive contexts, escaped equals signs,
  Markdown-style `=text=` / `==text==` marker pairs, or path-like tokens such as
  `path/=`. The old `*alias` and `**model` forms are ordinary prompt text. The macro LSP
  uses the same shared filter and edit plans; see
  [Equals model shortcuts](../integrations/editor.md#equals-model-shortcuts).
  `ace.prompt_completion.auto_directive_menu` only controls whether sase's TUI
  auto-opens these menus and does not govern an external editor's `=` trigger.
- **`@` reference completion**: A bare `@` opens the artifact-kind menu before a `:`
  appears. Local file rows such as `@src/` and `@Justfile` from the prompt-selected base
  directory stay hidden while the typed text prefix-matches an artifact kind; the panel
  advertises `[^T] files`, and the first `Ctrl+T` reveals those rows without accepting
  or extending the kind. A second `Ctrl+T` behaves as normal completion. The reveal
  stays active while that menu remains open and the query is narrowed. When no kind
  prefix-matches, file rows appear automatically, so path-shaped tokens such as `@src/`
  naturally show only files. Matching is fuzzy, so a payload is reachable by any
  memorable fragment of its path or title — `@research:site` finds
  `@research:202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md` — and `@rsch`
  finds the `research` kind. Rows are tiered so a fuzzy hit never outranks a literal one
  (prefix, then basename prefix, then contiguous substring, then ordered subsequence),
  then ranked by score, shorter text, and case-insensitive text; see
  [Artifact references](../integrations/editor.md#lsp-features) for the shared tier table. An empty
  query is not ranked at all, so opening a menu keeps each group's provider order. After
  any file reveal, `Ctrl+T` extends the token to the shared prefix only while every
  leading row is a literal prefix match; once the query is fuzzy-only there is no shared
  prefix to insert, so a single remaining row is accepted outright instead. Directory
  navigation stays exact — only the trailing path segment is fuzzy. Accepting an
  artifact kind inserts `@kind:` and immediately opens its payload rows; accepting a
  directory inserts the `@`-prefixed directory and drills down; accepting a file inserts
  the `@`-prefixed path. Dotfiles are hidden unless the typed path segment starts with
  `.`. Documents, explicit artifact files, chats, beads, and agents come from bounded
  project-scoped catalogs warmed off-thread. Bead rows are loaded from an mtime-cached
  bead-store snapshot, and agent rows come from a bounded scan of the project's agents
  sidecar. Agent rows display the readable local name when possible but insert the
  durable global `@agent:<username>.<machine>.<name>` spelling. Commit and bug rows
  appear only from snapshots the mounted Artifacts panes have already loaded, so typing
  never launches Git, contacts a tracker, or performs unbounded filesystem scans, with
  one explicit, user-initiated exception: typing a second `:` right after `@<kind>:`
  with an empty payload (the `@<kind>::` gesture) consumes that keystroke and refreshes
  the kind's backing sources now — cloning a missing sidecar, force-pulling an existing
  one past the freshness TTL, or rescanning a local/session-only kind — then reopens the
  payload menu. A pinned, non-selectable status row shows a live spinner while the sync
  runs (`cloning <repo> …` on a first-ever clone, `syncing <repo> …` otherwise) and
  settles to `<repo> synced · N new` or `<repo> sync failed · <detail>`; rows that
  arrived from the sync are badged `[✦]` in place of their usual source badge until the
  panel closes. A successful sync dismisses its status row after 2.5 seconds; a failed
  one stays until the panel closes and falls back to a toast if the panel is already
  gone. The gesture never fires with a non-empty payload (so `@file:default:` still
  inserts a literal colon), and repeating it while a sync is already running for that
  kind is a no-op. Payload acceptance replaces the complete `@kind:payload` context,
  including when the cursor is in the middle of it. On an un-narrowed bare-`@` menu,
  `Enter` submits the unexpanded `@` and dismisses the menu; `Ctrl+F` accepts the
  highlighted row even when it is the untouched first row, and `Ctrl+L` remains a
  manual-menu alias. Payload rows are rendered path-first — the source badge, then the
  reference path with dim directories and a bright basename, then a dim
  `title · detail · age` tail truncated to the remaining panel width — so what you see
  is what gets inserted. Matched characters are highlighted in gold wherever they
  landed, in the path, in the title, in a kind name, or in a local file row, so every
  row shows why it is there. The panel subtitle reports the same context: `~ fuzzy` when
  any visible row matched below the literal tiers, `N of M` for matching rows out of
  that kind's known payloads, and a `⚠ K not scanned` warning when a catalog cap
  truncated the candidate set, so a bounded search never reads as an exhaustive one.
- **Placeholder completion**: When the cursor is inside an incomplete `<foobar>` tag,
  completion suggests matching placeholders from the current prompt first, then saved
  common placeholders learned from tags you have written before. Within the
  current-prompt group, live tags keep document order and literal-zone tags follow in
  document order. Current-prompt rows use the cyan `<>` badge; saved rows use the gold
  `◆` badge. sase's TUI retains up to `ace.prompt_completion.common_placeholder_count`
  saved placeholders. Automatic completion stays quiet for a bare `<` and adds saved
  placeholders only after you type at least one prefix character; manual `Ctrl+T` on a
  bare `<` shows the saved list explicitly. A lone match in the highest-priority group
  is inserted outright, so saved tags never suppress direct insertion of a lone
  current-prompt match. Set `common_placeholder_count: 0` to disable saving and display
  of common placeholders. In the completion panel, `Ctrl+D` deletes the highlighted
  saved (`◆`) placeholder from the store; current-prompt (`<>`) rows are not deletable.
  By default, submitting from sase's TUI opens **Fill in this prompt** and asks once for
  each distinct live tag before launch; `Ctrl+L` can keep a tag literal. Saving a new
  macro converts the same live tags to typed inputs. Inline-code, fenced-code, and
  disabled-region tags stay literal in both paths; see
  [Raw Prompt Placeholders](../macros/templating.md#raw-prompt-placeholders).

  By default (`ace.prompt_completion.placeholder_ranking: smart`) saved rows are ranked
  by the same weighted composite the history-word menu uses: how strongly a tag relates
  to the words and tags already in the prompt (weight `0.50`), how recently it was used
  (`0.30`), and how often it has been used (`0.20`). Each saved row shows the same
  5-cell stacked score meter and dominant-reason chip as history words —
  `⇄ <tag or word>` for relation, `◷ <age>` for recency, or `✦ <count>×` for frequency —
  with the current-prompt and saved groups aligned on one shared label column. The
  panel's border subtitle adds a matching `⇄ related · ◷ recent · ✦ frequent` legend
  alongside the `<> prompt   ◆ saved` source legend when both are visible; a narrowing
  panel drops the source legend first (the badges are already visible in the rows), then
  the signal legend, leaving today's subtitle, and finally just the `[^D] delete` hint.
  The meter and chip degrade the same way on individual rows too narrow to fit them —
  the chip is dropped first, then the meter. Set `placeholder_ranking: recent` to
  restore the previous most-recent-use ordering with no signal column, or
  `placeholder_ranking_signals: false` to keep smart ranking but hide the meter, chip,
  and legend.

- **File path completion**: When the cursor is on a path-like token (starting with `/`,
  `./`, `../`, `~/`, or containing `/`), completion shows matching filesystem entries.
  Tokens starting with `@` are also recognized — the `@` prefix is preserved in the
  completed path (useful for file-reference arguments). Relative paths use the
  prompt-selected base directory: `+<project>`
  [project tags](../macros/reference-syntax.md#project-tags), registered
  workspace-provider refs, and known-project refs such as `#git:<project>` or
  `#gh:<owner>/<repo>` can root completion in that project checkout. If no prompt
  workspace ref resolves, sase's TUI uses the TUI process directory.
- **File-history completion**: `Ctrl+G r` opens a list of recently referenced files and
  well-formed `@kind:payload` artifact references drawn from prompt history, ranked by
  recency. Project-local `.sase/` paths are filtered out so internal bead/plan artifacts
  don't pollute the suggestions. Artifact references retain their leading `@`. Press
  `Ctrl+D` in the completion panel to delete the highlighted entry from the on-disk
  history. With `ace.prompt_completion.next_word: off`, `Ctrl+T` at a whitespace
  boundary (or an empty prompt prefix) opens this menu instead, preserving the old slot
  when there is no next-word chain to request.
- **Prompt-local word completion**: As the first fallback for a plain prose token,
  `Ctrl+T` filters words already in the active prompt by the word prefix immediately
  left of the cursor. Candidates are drawn only from complete words earlier in the
  prompt, before that prefix; words later in the prompt (including any suffix already
  sitting to the right of the cursor) are never candidates. Identifier-like candidates
  may include ASCII hyphens, so `bob-mac-capture` is matched and replaced as one word;
  Unicode dash punctuation still acts as a boundary. Matching is case-insensitive and
  case variants collapse into one row. Insertion honors the casing you started: a prefix
  with at least two cased characters that are all uppercase uppercases the rest (`GITHU`
  → `GITHUB`); otherwise intrinsic spellings such as `GitHub`, `README`, and `iPhone`
  stay intact, while a plain word keeps the typed prefix's case and appends its
  remembered remainder. Accepting a candidate replaces only the typed prefix, so
  completion works safely in the middle of a word: `foo<cursor>baz` completing to
  `foobar` becomes `foobar<cursor> baz` — a single space is inserted to separate the
  completed word from a preserved right-hand suffix, and the cursor lands immediately
  after the completed word, before that space. An exact-prefix spelling is only offered
  when accepting it would have this separating effect; at a plain word boundary with no
  suffix to separate, that exact match is suppressed as a no-op. While multiple
  candidates share a longer common prefix, `Ctrl+T` only narrows the typed prefix and
  keeps the menu open; it never inserts the separator until a candidate is actually
  committed. With the menu open, a second `Ctrl+T` accepts the highlighted row instead
  of re-dispatching. Candidates shorter than `ace.prompt_completion.word_min_length` are
  skipped before history fallback is considered; the default is `5`, and the threshold
  applies to the complete candidate rather than the typed prefix. This provider scans
  only the current prompt pane and takes precedence over history words when it has an
  eligible match. Candidates are ordered nearest-first: the word you just wrote is the
  one you are most likely repeating. When the next-word model is warm, `word_ranking` is
  `smart` (the default), and `next_word` is not `off`, candidates it predicts for the
  words before the cursor sort first instead, each marked with a violet `⇢ <context>`
  chip naming the evidence context; the border subtitle then carries the matching
  `⇢ context` legend entry. A cold model, a session-disabled model,
  `word_ranking: recent`, or `next_word: off` leaves nearest-first order untouched.
- **History-word completion**: When prompt-local words have no match, `Ctrl+T` filters
  recently used words derived from recorded prompt history using that same
  left-of-cursor prefix; any suffix under the cursor is never consulted to include or
  exclude candidates, only to decide whether accepting inserts the same separating space
  described above. Hyphenated identifier-like spellings are indexed, matched,
  length-filtered, and replaced as one word, with only the typed prefix replaced so a
  preserved suffix survives acceptance. Matching and insertion use the same case-variant
  collapse and typed-case policy as prompt-local completion. sase's TUI retains up to
  `ace.prompt_completion.history_word_count` unique words that meet the shared
  `ace.prompt_completion.word_min_length` (defaults: `10000` and `5`); set
  `history_word_count: 0` to disable only this final fallback. History is loaded
  off-thread, so a cold cache briefly shows `loading history words…` without blocking
  input. Pressing `Ctrl+T` while that placeholder row is highlighted re-dispatches
  (refreshing once the cache is warm) instead of accepting; with real candidates, a
  second `Ctrl+T` accepts the highlighted row. `Ctrl+D` deletes the highlighted word
  instantly, without rebuilding the index, and records it in
  `~/.sase/prompt_word_deletions.json`, so future history derivations continue to filter
  it out; remove that file to reset all history-word deletions. See
  [TUI migration notes](../upgrading/tui.md#keymap-moves) for the older
  `history_word_min_length` key.

  By default (`ace.prompt_completion.word_ranking: smart`) rows are ranked by a weighted
  composite of three signals rather than plain recency: how strongly a word relates to
  the words already in the prompt (weight `0.50`), how recently it was used (`0.30`),
  and how often it has been used (`0.20`). Each row shows a 5-cell stacked meter whose
  filled length is the composite score and whose cell colors show each signal's share,
  plus a dominant-reason chip — `⇄ <word>` for the context word it relates to, `◷ <age>`
  for recency, or `✦ <count>×` for frequency — and the panel's border subtitle carries a
  matching `⇄ related · ◷ recent · ✦ frequent` color legend. When the next-word model is
  warm and `word_ranking` is `smart`, rows it predicts for the words before the cursor
  sort first with a fourth, violet meter share and a `⇢ <context>` chip naming the
  sequence evidence, and the legend gains a matching `⇢ context` entry.
  `word_ranking: recent` and `next_word: off` leave that promotion off. The meter and
  chip are dropped (leaving the word alone) on panels too narrow to fit them, and the
  legend falls back to the plain `[^T] accept  [^D] delete` hint under the same width
  pressure. Set `word_ranking: recent` to restore the previous most-recent-use ordering
  with no signal column, or `word_ranking_signals: false` to keep smart ranking but hide
  the meter, chip, and legend.

- **Next-word prediction**: See [Next-word prediction](#next-word-prediction) below.

| Key               | Action                                                                                                                                                      |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Ctrl+T`          | Start completion, insert a shared prefix, accept the highlighted word-menu row, reveal a waiting peek, or take one word of a visible ghost or revealed peek |
| `Ctrl+N` / `Down` | Next candidate                                                                                                                                              |
| `Ctrl+P` / `Up`   | Previous candidate                                                                                                                                          |
| `Ctrl+F`          | Accept the highlighted completion-menu row; otherwise act like `Right`, including accepting an inline ghost when the rest of the line is blank              |
| `Ctrl+L`          | Accept the highlighted completion-menu row, or take the whole visible ghost or revealed peek                                                                |
| `Right`           | Move right; with only whitespace or nothing after the cursor on this line, take the whole inline ghost                                                      |
| `Alt+F`           | Move one word right; with only whitespace or nothing after the cursor on this line, take one inline ghost word                                              |
| `Enter`           | Submit the prompt as typed; a completion candidate stays unaccepted                                                                                         |
| `Ctrl+D`          | Delete a highlighted recent file, saved placeholder, history word, or predicted next word                                                                   |
| `Escape`          | Cancel completion                                                                                                                                           |

### Next-word prediction

Confident guesses from your own typed prompt history appear automatically as you type,
with no `Ctrl+T` needed to see them. They show as dim inline ghost text, or as a border
peek when the guess cannot sit in the line without shifting your prose (mid-sentence
guesses always use the peek, because inline text there would slide the rest of the
sentence right on every keystroke). The border hint is `[^T] word  [^L] all`.

`ace.prompt_completion.next_word` selects how guesses trigger. `auto` (the default)
predicts after each typed character: a typed word character completes the word being
typed, and any other typed character asks for the next words. `chain` shows nothing
while typing and arms only after a prompt-local or history-word commit, or on an
explicit `Ctrl+T` at the end of a prose word or at a whitespace boundary. `off` disables
predictions; with `off`, `Ctrl+T` at a whitespace boundary opens recent files directly.

With prediction enabled, accepting a prompt-local or history-word completion starts a
next-word chain: each accepted suggestion requests another. An explicit `Ctrl+T` also
starts a chain at a whitespace boundary with no token under the cursor. At the end of a
prose word, `Ctrl+T` first tries ordinary current-word completion; it requests next
words only when that completion has no candidate. Structured tokens, such as paths and
Jinja tags, keep their own completion behavior. This also holds in `auto`: a guess
requested while typing owns `Ctrl+T` only while its ghost or peek is showing or waiting
to be revealed; otherwise `Ctrl+T` completes structured tokens, paths, and prompt-local
and history words exactly as in `chain` mode.

Where a confident guess appears depends on the cursor:

- If the rest of the logical line is blank and the cursor is on its last wrapped row,
  the guess appears inline. Here, “blank” includes trailing whitespace.
- If only a short closing tail follows, the guess appears inline before that tail, again
  only on the last wrapped row. A tail has at most eight non-space characters, all from
  `)]}"'”’.,;:!?…*_`; spaces between them are allowed, and backticks are excluded.
- If other text follows, the cursor is on an earlier wrapped row, or even the first
  suggested word plus the closing tail will not fit, the guess appears as a border peek.
  The peek shows a violet `⇢`, its first word in bold, and later words dimmed.
- If a letter, digit, `_`, `'`, `’`, or `-` immediately follows the cursor, no ghost or
  peek appears. This keeps suggestions quiet when editing inside an existing word.

`ace.prompt_completion.next_word_max_words` caps suggestions (default `4`, clamped to
1–8). An inline ghost drops trailing words until it fits beside any closing tail. A
narrow border drops trailing preview words, then `[^L] all`, then `[^T] word`, without
cutting a word. If even `⇢` and the first word do not fit, the peek stays hidden.
**Border shortening affects only the display:** `Ctrl+L` can insert later words omitted
from a narrow peek. Use `Ctrl+T` to accept one word at a time.

A leading space is omitted at the start of the text, after whitespace, and after an
opening bracket or quote. A peek is cut before the first suggested word that matches,
ignoring case, the first word after the cursor; if its first word already follows the
cursor, no peek is shown. A guess based only on a word's overall frequency, without
contextual evidence, never reaches the ghost, peek, or next-word menu.

The first explicit request shows a confident guess as a ghost or peek. A weaker guess,
or a confident guess that fits neither surface, can open a `next word ⇢ "…"` menu naming
the evidence context. Each row shows a word, a violet confidence meter, and a dim
`⇢ continuation` preview. Accepting a row inserts its word with a separator and
continues the chain. With a ghost or a revealed peek already visible, the next `Ctrl+T`
accepts one word. `Ctrl+L` accepts the inline ghost or all words stored in the revealed
peek. Each accept requests another prediction immediately.

`Right` and `Ctrl+F` accept the whole inline ghost only when the rest of the line is
blank; `Alt+F` accepts one ghost word in that same position. Before a closing tail or
with a border peek, these keys move the cursor. An open completion menu takes priority:
`Ctrl+F` and `Ctrl+L` accept its highlighted row.

An automatic guess shows inline ghost text immediately. Its border hint waits until text
and cursor have stayed unchanged for 350 ms; an automatic peek stays hidden for that
same interval. An explicit `Ctrl+T` reveals immediately. While a peek is still waiting,
the first `Ctrl+T` reveals it and inserts nothing; the next accepts one word.

Typing characters that continue the ghost consumes them. A different character,
Backspace, a cursor move, undo, or redo clears the suggestion. The chain remains usable
only while its text and cursor match the position where it was started. An armed chain
with no candidates shows `no next-word guess`, or `warming next words…` while the model
loads. Structural syntax does not open a next-word menu. At a whitespace boundary, a
miss adds `[^G r] recent files`, pointing to the recent-files menu on `Ctrl+G r`. With
`next_word: off`, that whitespace-boundary `Ctrl+T` opens recent files directly.
`Ctrl+D` on a highlighted next-word row forgets it through the history-word deletions
store.

In `auto`, a typed non-word character that follows a word token asks for the next words
— clause punctuation between the word and the trigger is skipped, so a ghost may appear
after `, ` — and, while you type a word with only a boundary after the cursor, the
request completes that word. After a sentence-final `.`, `?`, `!`, or `…`, the model
starts a fresh empty context and stays silent. If the keystroke was consumed by a
visible ghost, the ghost is kept and no new request is made.

In `auto`, current-word completion inserts the untyped suffix plus any continuation. For
example, after typing `imple`, the ghost might be `ment it now`. If the word is already
complete, the ghost starts with a space (` it now`); an exact word with no continuation
stays silent. A current-word peek displays the completed word first. `Ctrl+T` inserts
its missing suffix, or the next continuation word if no suffix is missing. `Ctrl+L`
inserts the suffix and continuation. A current-word request that found a guess shows it
as a ghost or peek, and `Ctrl+T` takes it. When that request shows nothing (including
when the core supplies no current-word completion), `Ctrl+T` runs ordinary completion
instead of repeating the request. The completed word counts toward
`next_word_max_words`, leaving at most `next_word_max_words - 1` continuation words.

When the text **before the cursor** exceeds 4000 characters, a typing-triggered
current-word request runs off the keystroke path after
`ace.prompt_completion.debounce_ms` (default `90` ms). This cutoff does not apply to an
explicit `Ctrl+T` request or measure text after the cursor.

Ghosts and peeks stay off in NORMAL mode, during file completion, during a snippet
session, while text is selected, and for the whole of a Jinja `{{ }}` or `{% %}` tag.
The gate and plan feedback note editor hosts the same autosuggest — ghost, peek, hint,
`Ctrl+T`, and `Ctrl+L` — with no completion menu there, so `Ctrl+T` there still
re-requests a typing-armed guess and shows the hint.

Principles: `Ctrl+T` never inserts an unseen guess, always moves forward, and stays
silent when unsure.

Press `Ctrl+R` to open the recursive fuzzy file finder. With a token such as `src/alp`,
`src/` becomes the search root and `alp` pre-seeds the fuzzy query; with no token, the
finder starts at the prompt-selected base directory described above. If a `Ctrl+T` file,
recent-file, or path-argument candidate is highlighted, that highlighted path seeds the
recursive root instead. The finder uses
`git ls-files --cached --others --exclude-standard` from the search root when possible,
falls back to a bounded filesystem walk, and inserts the selected path into the prompt
position captured when the finder opened. Inside the finder, type to filter, use
`Ctrl+N` / `Ctrl+P` or arrows to move, `Ctrl+U` to clear the query, `Enter` to insert,
and `Esc` to cancel.

In prompt NORMAL mode, `K` previews the macro, slash skill, or file under the cursor.
Image files preview inline in the reader, while `Ctrl+]` still opens images directly in
the artifact viewer. Inside `#name: ` / `#name:: ` argument text, `K` and `Ctrl+]`
prefer a nested reference, file path, glossary term, or plain word under the cursor, and
fall back to the macro that owns the argument text only when nothing else matches. On
ordinary prompt text, sase's TUI checks the warm project glossary before falling back to
plain word lookup or spelling fixes. `Ctrl+]` jumps to a macro, skill, file, or glossary
definition, or opens an action picker when several jump targets are available. Glossary
terms come from the project selected by a leading VCS workflow reference, or from the
active workspace project when the prompt does not select one.

<a id="glossary-terms"></a>
Moved to [Prompt completion panels](prompt-completion-panels.md#glossary-terms).
<a id="memory-panel"></a>
Moved to [Prompt completion panels](prompt-completion-panels.md#memory-panel).
<a id="snippets-panel"></a>
Moved to [Prompt completion panels](prompt-completion-panels.md#snippets-panel).
<a id="repo-names"></a>
Moved to [Prompt completion panels](prompt-completion-panels.md#repo-names).
<a id="word-definitions-spellcheck"></a>
Moved to [Prompt completion panels](prompt-completion-panels.md#word-definitions-spellcheck).

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Prompt input](prompt-input.md) — insert mode, alt-brace, search, and macro editing.
- [Prompt completion panels](prompt-completion-panels.md) — glossary, memory, snippets, repos, and spellcheck.
