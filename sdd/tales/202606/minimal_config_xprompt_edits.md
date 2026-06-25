---
create_time: 2026-06-25 10:06:14
status: done
prompt: sdd/prompts/202606/minimal_config_xprompt_edits.md
---
# Plan: Minimal, comment-preserving xprompt edits in YAML config files

## 1. Goal

When we add a new xprompt (or overwrite an existing one) into a YAML config file such as `sase.yml` /
`default_config.yml`, the edit must be **minimal and respectful of the existing file**:

- **No spurious blank lines** inserted between existing xprompt definitions.
- **No lost or misplaced comments** (e.g. `# keep-sorted start` / `# keep-sorted end`, or any user note).
- **Untouched entries stay byte-for-byte identical** — only the one entry we add or replace changes.
- **Ordering rule**: if the existing entries are already sorted, insert the new entry in sorted position; if they are
  **not** sorted, append the new entry at the **end** of the list.

This is a focused fix to the config-insertion logic that the "save draft as xprompt" feature (and the XPrompt Browser's
"add xprompt") both rely on. No new user-facing surface is added.

## 2. The problem (root cause)

All config xprompt writes funnel through `insert_xprompt_into_config` in `src/sase/xprompt/config_yaml.py` (re-exported
via `src/sase/ace/tui/modals/xprompt_config_yaml.py` and wrapped by `save_config_xprompt` in
`src/sase/xprompt/save.py`). Today that function **parses the whole `xprompts:` section into named entry blocks, then
rebuilds the entire section from scratch, sorted, with a forced blank line between every entry**. That rebuild causes
four distinct regressions, all observable against the real `src/sase/default_config.yml` (its `xprompts:` section is
wrapped in `# keep-sorted start` / `# keep-sorted end` and packs entries with **zero** blank lines between them):

1. **Forced blank separators.** The rebuild inserts a blank line between every pair of entries. Files that pack entries
   (like `default_config.yml`) get a blank line added between _all_ ~30 entries on a single insert — a huge, noisy diff.
2. **Dropped leading comments.** Lines that appear _before the first entry_ in the section (the `# keep-sorted start`
   marker and the blank line after it) are silently discarded, because the block parser only starts capturing once it
   has seen the first entry anchor.
3. **Misattributed trailing comments.** A section-level trailing comment like `# keep-sorted end` is absorbed into the
   _last_ entry's block, so it travels with that entry when the section is re-sorted instead of staying at the bottom of
   the section.
4. **Whole-section churn + wrong sort key.** Every entry is re-emitted in `sorted()` order even when unchanged. Worse,
   the sort uses the _bare entry name_, which disagrees with the `keep-sorted` convention the file actually uses
   (whole-line / name-with-colon comparison). Example from `default_config.yml`: `research/image`, `research/more`,
   `research/prompt` correctly sort **before** `research` because `/` (0x2F) sorts before `:` (0x3A) when the trailing
   colon is included — but bare-name sorting would reorder `research` ahead of them, making the function both _think the
   file is unsorted_ and _reorder it incorrectly_.

Additionally, the current contract is "always sort" (the docstring even says it sorts unsorted sections). The desired
contract is "preserve sortedness if present, otherwise append at the end" — a behavior change that also makes edits to
hand-organized config files predictable.

## 3. Design: surgical, single-entry edits

Replace the "parse-all-then-rebuild" strategy with **targeted text surgery** that changes only the bytes that must
change. The mental model: the `xprompts:` section is a sequence of three things we treat differently —

- **Head scaffolding**: everything from the line after `xprompts:` up to (but not including) the first entry anchor
  (e.g. `# keep-sorted start` + a blank line). **Preserved verbatim.**
- **Entry definition blocks**: each entry is its anchor line (`  <name>:` at 2-space indent) plus all following lines
  more-indented than the anchor (its `input:` / `content: |` body, including interior blank lines). An entry block ends
  at the first following **non-blank line indented ≤ 2 spaces** (the next anchor, a section comment, or the next
  top-level key / EOF). **Comments and blank lines are never part of an entry block** — they are immovable scaffolding.
- **Tail scaffolding**: everything from the first post-last-entry boundary onward (e.g. `# keep-sorted end`, trailing
  blank lines, the next top-level key). **Preserved verbatim.**

We only ever do one of two edits:

- **Insert a brand-new entry**: splice the generated entry lines in at exactly one position, mirroring the file's
  existing inter-entry spacing. Nothing else moves.
- **Overwrite an existing entry**: replace only that entry's definition-block lines in place. Its position, the comments
  and blanks around it, and every other entry stay exactly as they were.

### 3.1 Sort key

Compare entries by the key `f"{name}:"` (the entry name with its trailing colon), which matches how `keep-sorted` orders
the section (whole-line lexicographic) and fixes the `research` / `research/...` tiebreak described above. This single
key is used for both "is the section already sorted?" detection and "where does the new entry go?" placement.

### 3.2 Placement rules

Let `entries` be the existing entry blocks in document order, keyed as above.

- **Overwrite** (the new name already exists): replace that entry's block lines in place. Never reorder, never touch
  spacing or comments. (This is the path used when the save flow targets an existing xprompt, and it is the minimal-diff
  case.)
- **Insert new name, section already sorted**: find the first existing entry whose key is greater than the new key;
  splice the new block immediately before that entry's anchor. If no entry is greater (the new entry sorts last), splice
  it in after the last entry's block but **before** the tail scaffolding (so it lands above `# keep-sorted end`, not
  below it).
- **Insert new name, section not sorted**: append the new block after the last entry's block (again before the tail
  scaffolding). This satisfies the "otherwise add at the end" rule and avoids gratuitously reordering a file the user
  has chosen to organize differently.

### 3.3 Spacing (no invented blank lines)

Determine a single **canonical inter-entry gap** by sampling the blank-line count between a genuine adjacent entry pair
(e.g. the gap preceding the last entry's anchor; use the most common gap if they vary; default to **0** when there is
only one entry or none). When splicing a new block, emit exactly that many blank lines as its separator and leave all
existing blank lines where they are. For `default_config.yml` the canonical gap is `0`, so an insert adds **no** blank
lines. For a file that uses one blank line between entries, the new entry gets one blank line on each side to match. The
head blank line (between `# keep-sorted start` and the first entry) is head scaffolding and is preserved as-is, so
inserting a new _first_ entry does not produce a spurious extra blank.

### 3.4 Untouched fallbacks

The existing special cases stay, just made spacing-clean:

- **No `xprompts:` key**: append a new `xprompts:` section at the end of the file with the single entry (current
  behavior, preserved).
- **`xprompts: {}`**: convert to a bare `xprompts:` and insert the single entry as the first (and only) block.
- **Empty section** (key present, no entries): insert the entry directly after the key, preserving any head/tail
  scaffolding.

## 4. What changes

### 4.1 Core logic — `src/sase/xprompt/config_yaml.py`

Rewrite the body of `insert_xprompt_into_config` around the surgical model above, factored into small, unit-testable
helpers (names illustrative):

- `_find_xprompts_section(lines)` → locate the key and the section's `[start, end)` line range (next top-level key or
  EOF), normalizing `xprompts: {}` → `xprompts:`.
- `_parse_entry_blocks(lines, start, end)` → ordered list of `(name, block_start, block_end)` spans using the
  indentation boundary rule (anchor at indent 2; block extends over lines indented > 2 and interior blanks; ends at the
  first non-blank line indented ≤ 2). Trailing blank lines are excluded from each block.
- `_entry_sort_key(name)` → `f"{name}:"`.
- `_canonical_gap(blocks, lines)` → the representative inter-entry blank-line count (default 0).
- `_compute_insert_index(...)` / overwrite-span resolution → the single splice or replace operation.

`generate_xprompt_yaml` / `_generate_frontmatter_xprompt_yaml` (entry-body serialization) are unchanged — they already
emit a clean block with no trailing blank line, which is exactly what the splicer needs. **Public signatures of
`generate_xprompt_yaml`, `insert_xprompt_into_config`, and `save_config_xprompt` are unchanged**, so existing callers
(`xprompt_browser_actions.py`, `_prompt_bar_save_xprompt.py`) need no edits. Update the function/module docstring to
describe the new "preserve sortedness, else append; never reflow other entries or comments" contract.

### 4.2 No Rust changes

Verified in the linked `sase-core` repo: there is **no** Rust writer that inserts or serializes xprompts into config
files — the Rust side only _reads_/parses/catalogs them (`xprompt_catalog.rs`, editor hover/diagnostics/definition,
LSP). Per `memory/rust_core_backend_boundary.md`, the cross-frontend invariant is that **what Python writes must parse
identically on the Rust side**. Our change is purely textual (comments/blank lines, which YAML parsers ignore) and does
not alter the YAML data model, so Rust-catalog parity is preserved and re-asserted by round-trip tests. No `sase-core`
edits are needed.

### 4.3 No `default_config.yml` change

The shipped config is not modified by this plan; it is, however, the canonical real-world fixture this fix must respect
(keep-sorted markers, packed entries, colon-tiebreak names), and a test mirrors its shape.

## 5. Testing

Existing tests encode the _old_ contract and must be updated alongside new coverage.

### 5.1 Updated existing tests

- `tests/ace/tui/test_xprompt_config_insert.py::test_sorts_unsorted_entries` — old expectation was "unsorted gets
  sorted". Under the new contract, inserting into an unsorted section **appends at the end**; update the assertion to
  expect the new entry last (existing entries keep their original order).
- `tests/xprompt/test_save.py::test_config_save_round_trips_full_frontmatter_and_orders_entries` — its fixture is
  unsorted (`zulu`, then `alpha`). Change the fixture to be **sorted** (`alpha`, `zulu`) so the test still exercises
  sorted-position insertion of `bravo` (→ `alpha`, `bravo`, `zulu`), and keep the round-trip assertions.

### 5.2 New tests (the regressions this plan fixes)

Add focused cases (in the same two test modules, or a new `tests/xprompt/test_config_yaml_minimal_edits.py`):

- **No blank lines introduced (packed style).** Fixture: a `default_config.yml`-style section — `# keep-sorted start`, a
  blank line, several packed entries (no blanks between), `# keep-sorted end`. Insert a new entry and assert: the number
  of blank lines between entries is unchanged (zero new blanks), both keep-sorted comments are still present and in
  place, and **only** the new entry's lines were added (diff the before/after line multisets).
- **Comment preservation.** Assert `# keep-sorted start` and `# keep-sorted end` survive an insert and an overwrite, and
  that the end marker stays at the bottom of the section (not glued to an entry).
- **Sorted-position insert with colon tiebreak.** Insert e.g. `research/zzz` and a name like `researchz` into the packed
  sorted fixture and assert correct keep-sorted placement (`research/...` group before `research`), and that the section
  is still detected as sorted (the new entry is _not_ appended at the end).
- **Unsorted → append at end.** Fixture with entries out of order; assert the new entry lands last and existing entries
  are not reordered.
- **Overwrite is minimal and in place.** Overwrite an existing entry; assert its position is unchanged, surrounding
  comments/blank lines are untouched, other entries are byte-identical, and only that entry's block changed.
- **Spacing-style mirroring.** A fixture that uses exactly one blank line between entries keeps one-blank spacing for
  the inserted entry; the packed fixture stays packed. Cover first-entry, middle, and last-entry insert positions.
- **Fallbacks.** `xprompts: {}`, missing section, and empty section each insert cleanly with no stray blanks (extend the
  existing fallback tests to also assert no spurious blank lines).

### 5.3 Validation

Per the workspace rules, run `just install` first (ephemeral workspace), then `just check` (ruff + mypy + tests) before
completion. Note the pre-existing `llm_provider`/`default_effort` failures recorded in memory are unrelated to this
change.

## 6. Out of scope (called out, not built)

- **Markdown `.md` xprompt writes.** `save_markdown_xprompt` rewrites a whole single-entry file, which is already
  effectively minimal; markdown frontmatter has no inter-entry blanks/comments to preserve. If the team later wants
  comment-preserving `.md` overwrites, that is a separate follow-up.
- **Adopting a round-trip YAML library (e.g. `ruamel.yaml`).** Considered and rejected for now: it adds a dependency and
  tends to reflow block scalars / quoting, producing non-minimal diffs. The existing line-surgery approach, fixed as
  above, gives tighter control over exactly which bytes change.
- **Moving config xprompt writing into `sase-core`.** No Rust writer exists today and no second frontend writes
  xprompts; the pure Python module remains the future seam if that changes.
- **Re-sorting an already-unsorted file.** By design we do not reorder a section the user has chosen not to keep sorted;
  we only append.

## 7. Decisions already made (so implementation is unambiguous)

- Edits are surgical: exactly one splice (insert) or one in-place block replace (overwrite); everything else is
  byte-preserved.
- Comments and blank lines are scaffolding and are never moved, dropped, or absorbed into entry blocks.
- Sort/placement key is `name + ":"` (matches `keep-sorted` whole-line order; fixes the `/` vs `:` tiebreak).
- Sorted section → sorted-position insert; unsorted section → append at end; existing name → overwrite in place.
- Inter-entry spacing for a newly inserted entry mirrors the file's existing canonical gap (default 0); no blank lines
  are invented.
- Public function signatures are unchanged; no caller or Rust changes; `default_config.yml` is not modified.
