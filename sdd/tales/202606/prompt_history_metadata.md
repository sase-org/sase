---
create_time: 2026-06-13 13:00:46
status: done
prompt: sdd/prompts/202606/prompt_history_metadata.md
---
# Plan: Show project + directives/xprompts in the prompt history panel

## Goal / product context

The `sase ace` **prompt history modal** (`Ctrl+P` → `PromptHistoryModal`) shows a left pane listing past prompts and a
right pane previewing the highlighted prompt. Today each left-pane row is just:

```
  06-13 14:30  #gh:sase Fix the parser bug so it handles edge cases when th…
```

The project tag (`#gh:sase`), directives (`%plan`, …), and embedded xprompt workflows (`#fork`, …) are buried _inside_
the raw preview text — noisy, hard to scan, and they eat the width that should show the actual instruction.

We want each row to surface, at a glance and beautifully:

1. **The project used** — i.e. the VCS xprompt workflow the prompt ran under (`#gh:sase`, `#git:home`, …).
2. **Which directives / embedded xprompt workflows** were used (e.g. `#fork`, `%plan`).

…without making rows too long. The key insight that makes this _free_ on width: those tokens are **already in the
preview text**. We lift them out into compact, color-coded columns and strip them from the preview, so the preview gets
_cleaner and shorter_ while gaining structured metadata. Net line length is neutral-to-better.

Ground truth from the real history file (`~/.sase/prompt_history.json`, 9,101 prompts): 88% carry a leading VCS tag, 98%
contain some `#ref`, 51% contain a `%directive` — so this metadata is genuinely present and worth surfacing. Refs can be
long (`#gh:steveyegge/beads`), which the design accounts for.

## Current behavior (files)

- `src/sase/ace/tui/modals/prompt_history_modal.py`
  - `_create_prompt_history_label()` builds each row's `rich.text.Text`: `marker + timestamp + preview`.
  - `_create_options()` builds an `Option` per filtered item; **rebuilt on every keystroke** in `on_input_changed()` and
    on `Ctrl+X` toggle.
  - `_update_preview()` renders the right pane: full prompt text + a `--- Metadata ---` block (Status / Created / Last
    Used).
  - `__init__ → _load_items()` synchronously loads **all** entries via `get_prompts_for_fzf(include_cancelled=True)`.
- `src/sase/history/prompt.py` — `PromptEntry(text, timestamp, last_used, cancelled, …)`. **No** project/directive
  fields; everything must be parsed from `text`. (Intentionally — we do not change the persisted schema.)
- `src/sase/ace/tui/styles.tcss` (≈1275–1350) — modal CSS; list pane and preview pane are each `width: 1fr`.

## Reused extraction primitives (no new parsing grammar — respects the Rust-core boundary)

All VCS-tag / directive / xprompt grammar already lives in Python under `sase.xprompt`. We **compose** these; we do
**not** reimplement parsing, and there is **no Rust change** — the behavior is presentation-support that sits on top of
existing parsers, and the rendering itself is presentation-only Textual code.

- `sase.xprompt.extract_vcs_workflow_tag(text)` → leading `#gh:sase ` (skips leading `%directives`).
- `sase.xprompt.extract_project_from_vcs_tag(tag)` → ref (`sase`, `steveyegge/beads`, …).
- `sase.xprompt._parsing_references.iter_xprompt_references(text)` → all `#name` / `#!name` refs.
- `sase.xprompt.directives.extract_prompt_directives(text)` → full `PromptDirectives` (values too) — preview only.
- `sase.xprompt._directive_types._DIRECTIVE_PATTERN`, `_KNOWN_DIRECTIVES`, `_DIRECTIVE_ALIASES` — for a lightweight
  directive-name scan (list rows).
- `sase.xprompt._fenced_blocks.protect_fenced_blocks` — protect code fences before scanning (matches the existing
  `_sanitize_resume_prompt` approach in `history/chat.py`).
- `sase.workspace_provider.get_workflow_names()` → set of VCS workflow names (`gh`, `git`, `hg`, …), used to separate
  "project" refs from genuine embedded xprompt workflows.

## Visual design (the important part — must look beautiful)

### Left-pane row layout

```
 marker  timestamp      project        tags         clean preview (ellipsized, fills rest)
 ───────────────────────────────────────────────────────────────────────────────────────
   06-13 14:30   gh:sase      #fork %pa   Fix the parser bug so it handles edge…
   06-13 09:15   git:home                 Refactor the workspace loader for clar…
   06-13 08:02   gh:beads     #research   Investigate the failing CI on the bea…
   06-13 07:40   —                        Quick note without any project tag here
 x 06-12 22:10   gh:sase      %m          try the experimental model on this one…
```

Columns, left to right:

1. **marker** (2 cols) — unchanged: `x ` (magenta) for cancelled, else two spaces.
2. **timestamp** (11 cols) — unchanged `MM-DD HH:MM`, `dim`.
3. **project** (fixed ~12 cols, left-justified for vertical rhythm) — `<wf>:<ref>`:
   - workflow prefix (`gh:`, `git:`) rendered `dim`; ref (`sase`) rendered in an accent (`cyan`).
   - ref is shown as its **basename** (`steveyegge/beads` → `beads`) and ellipsized to fit; the full ref lives in the
     preview pane.
   - no explicit tag → a single `dim` `—` placeholder (we do **not** invent the launch-time default, which isn't
     recorded).
4. **tags** (variable, capped) — the "which directives/xprompts" indicator, omitted entirely when empty:
   - **embedded xprompt workflows** first, as `#name` chips in `green` (deduped; VCS-workflow-named refs excluded; args
     dropped here, shown in preview). Cap at 3 chips, overflow as `+N`.
   - **directives** collapsed into a single `yellow` token: `%` + sorted short-alias letters (plan+approve+model →
     `%amp`). Directives without an alias (`epic`) appended as a full `%epic` token. Presence-only here (values shown in
     preview).
5. **clean preview** (fills remaining width, `no_wrap`, `overflow="ellipsis"`) — first line of the prompt with the
   leading VCS tag, all directives, and all xprompt refs **stripped** and whitespace collapsed (same spirit as
   `_sanitize_resume_prompt`). This is what reclaims the width spent on columns 3–4.

Why this ordering: everything fixed/structured sits left of the variable-length preview, so only the preview is ever
ellipsized — the project and tags never get cut off. The fixed project column gives clean vertical alignment; tags flow
(rarely more than 1–2) so they cost ~0 width when absent (the common case).

**Palette** (literal Rich style names, consistent with the file's existing `dim`/`magenta`; tunable): timestamp `dim` ·
project prefix `dim` · project ref `cyan` · xprompt chips `green` · directive token `yellow`. When the entry is
**cancelled**, the established behavior wins: everything renders `dim italic` (and the `x` marker stays `magenta`) so
cancelled rows recede.

### Right-pane preview metadata (complementary, verbose)

Extend `_update_preview()`'s `--- Metadata ---` block (the full prompt text above it stays raw/unmodified so it can be
copied verbatim). Rows are omitted when empty:

```
--- Metadata ---
Status:     Cancelled                  (only when cancelled)
Project:    #gh:steveyegge/beads       (full tag, or — when none)
Workflows:  #fork, #research           (embedded xprompts, with args)
Directives: %plan, %model:opus, %r:3   (full names + values)
Created:    260501_140000
Last Used:  260501_142530
```

This is where the detail the list omits (full ref, directive values, xprompt args) lives — single item, on highlight, so
we can afford full `extract_prompt_directives`.

## Technical design

### New pure module: `src/sase/history/prompt_metadata.py`

Keeps extraction/summarization (testable, no Textual) separate from rendering. Two tiers so the list path stays cheap
and the preview path stays rich:

- `@dataclass(frozen=True) PromptListSummary` — `project_prefix`, `project_ref_display`, `xprompts: tuple[str,…]`,
  `directive_token: str`, `clean_preview: str`.
- `summarize_prompt_for_list(text) -> PromptListSummary` — **lightweight**: one `protect_fenced_blocks` pass shared by a
  `_DIRECTIVE_PATTERN` directive-name scan and an `iter_xprompt_references` scan, plus the cheap anchored
  `extract_vcs_workflow_tag`. No model resolution, no full directive extraction.
- `@dataclass(frozen=True) PromptPreviewSummary` — `vcs_tag`, `xprompts` (with args), `directives` (names+values).
- `summarize_prompt_for_preview(text) -> PromptPreviewSummary` — **full**: `extract_prompt_directives` +
  `iter_xprompt_references` + vcs extraction. Single-item use only.
- `clean_prompt_preview(text) -> str` — strip leading VCS tag + directives + xprompt refs (fence-protected), return
  collapsed first line.
- Small helpers: basename of a ref, directive-name → short-alias, canonical ordering, chip-capping with `+N`.

### Modal changes (`prompt_history_modal.py`)

- Add a cached `summary: PromptListSummary | None = None` field to `_PromptDisplayItem`.
- `_create_prompt_history_label()` rewritten to render the 5 columns above; computes `item.summary` lazily on first
  build and stores it on the item. Because `_filtered_items` references the same `_all_items` objects, a given prompt is
  parsed **once** for the modal's lifetime and is **not** re-parsed on keystroke re-filters — this is the key compliance
  point with TUI-perf Rule 7 ("memoize per-keystroke structures").
- `_update_preview()` extended with the Project / Workflows / Directives rows via `summarize_prompt_for_preview()`.
- Keep `_PROMPT_PREVIEW_WIDTH` budget logic; introduce `_PROJECT_COL_WIDTH`, `_MAX_TAG_CHIPS`, etc. as module constants.

### Performance (TUI-perf memory reviewed)

The modal already does synchronous disk load + JSON parse of all entries in `__init__` and rebuilds labels per
keystroke. The incremental cost is the per-row scan; the lazy-once cache removes it from the keystroke path. Per
"Measure, don't guess":

- Add a `tests/perf`/bench-style micro-measurement (or a one-off during implementation) running
  `summarize_prompt_for_list` over the real ~9k-entry corpus to confirm the lightweight scan is well under a noticeable
  budget, and measure modal open before/after.
- **Fallback if open latency regresses materially**: move the bulk summary build off the event loop using the
  established worker pattern (`asyncio.to_thread` / `run_worker(thread=True)` with `call_after_refresh`), showing rows
  immediately and filling summaries in — rather than parsing all items synchronously in `_load_items`. (Expected
  unnecessary, but called out so the implementation has a sanctioned path.)

## Files to change / add

- **add** `src/sase/history/prompt_metadata.py` — extraction + summarization helpers.
- **edit** `src/sase/ace/tui/modals/prompt_history_modal.py` — row rendering + preview metadata + cached summary.
- **edit** `src/sase/ace/tui/styles.tcss` — only if minor tweaks help (e.g. preview metadata spacing). Layout is driven
  by the `Text` columns, so likely minimal/none.
- **add** `tests/history/test_prompt_metadata.py` — unit tests for the pure helpers.
- **edit** `tests/ace/tui/modals/test_prompt_history_modal.py` — row-rendering assertions (project chip, tag chips,
  cleaned preview, cancelled dimming, alignment/ellipsis) + preview metadata.

## Edge cases

- No VCS tag → `—` placeholder; no `Project:` value confusion.
- `owner/repo` refs → basename in list, full in preview.
- The leading VCS tag also matches `iter_xprompt_references` (name `gh`) — excluded from xprompts via
  `get_workflow_names()`.
- Tokens inside code fences → protected before scanning (consistent with `_sanitize_resume_prompt`).
- Prompt that is _only_ control tokens (e.g. `#gh:sase #fork`) → empty clean preview; chips still convey it.
- Multi-prompt (`---`) entries: each segment is already stored as its own history entry, so per-row summarization is
  correct; the combined entry summarizes off its leading tag + all refs.
- Cancelled rows keep the existing `dim italic` + magenta `x` treatment, applied over the new columns.

## Verification

- `just install` then `just check` (lint + mypy + tests) — required by repo rules after file changes.
- New unit tests for `prompt_metadata` (project/xprompt/directive extraction, basename, token collapsing, fence
  protection, clean preview) and updated modal-render tests.
- Manual `sase ace` smoke against the real history: open `Ctrl+P`, confirm project column, tag chips, cleaned previews,
  alignment, cancelled dimming, narrow-terminal ellipsis, and the enriched preview pane; eyeball the palette for beauty
  and tune colors if needed.
- Quick open-latency sanity check on the ~9k-entry corpus.

## Out of scope

- The persisted `PromptEntry` schema (no new stored fields — parse on read).
- The non-TUI fzf prompt path (`get_prompts_for_fzf` / `_format_prompt_for_display`) and the command history modal.
- Any Rust `sase-core` change (none needed; we reuse existing Python `sase.xprompt` parsers).
