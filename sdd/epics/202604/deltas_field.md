---
create_time: 2026-04-28 20:29:35
status: done
bead_id: sase-13
prompt: sdd/prompts/202604/deltas_field.md
---
# Plan: DELTAS ChangeSpec Field

## Overview

Add a new `DELTAS` section to ChangeSpecs that lists every file the CL touches, tagged with whether the file was
**added**, **modified**, or **deleted**. The field is computed from the underlying VCS state and is kept in sync with
the real change as commits are added, rewinds happen, proposals are accepted, and parent-CL relationships shift.

DELTAS gives users a fast, at-a-glance view of a CL's footprint without having to crack open the diff, and serves as a
structured, machine-readable surface that other workflows (mentors, reviewers, hooks) can build on later.

## Design

### File Format (.gp)

DELTAS sits between `COMMITS` and `HOOKS` (alongside other commit-derived sections). Entries are alphabetical by path,
with a single-character status prefix that mirrors `git diff --name-status` conventions but is intentionally limited to
the three operations the user asked for:

```
DELTAS:
  + src/sase/ace/changespec/deltas.py
  + tests/test_deltas_parsing.py
  ~ src/sase/ace/changespec/models.py
  ~ src/sase/ace/changespec/parser.py
  - src/sase/legacy/old_deltas.py
```

Format choices:

- **Status prefix** (column 3, single char + space):
  - `+` — file added
  - `~` — file modified (chosen over `M` to read like a "diff" symbol and avoid being mistaken for path text)
  - `-` — file deleted
- **Indent**: 2 spaces (matches every other section's entry indent)
- **Path**: relative to repo root, unquoted (parser tolerates spaces by reading rest-of-line)
- **Sort**: alphabetical by path. Status grouping is conveyed by _color_ in the TUI, not by ordering — this keeps the
  list scannable when looking up a specific file.
- **Empty case**: when a CL has no file changes (e.g. status-only or pre-commit ChangeSpec), the section is omitted
  entirely rather than written as `DELTAS:` with no body.

Renames are deliberately **out of scope for v1** and are recorded as a `-` of the old path plus a `+` of the new path
(which is what a name-status diff produces with rename detection off). A future `R old -> new` form can be layered in
without breaking the parser.

### TUI Rendering

DELTAS is the first place a user sees the "shape" of a CL, so the visual treatment matters. Palette is chosen to be
cohesive with the existing ChangeSpec color scheme (gold entry numbers, cyan headers, tan note text):

| Element          | Color                   | Style  | Rationale                                              |
| ---------------- | ----------------------- | ------ | ------------------------------------------------------ |
| `DELTAS:` header | `#87D7FF`               | bold   | Matches every other section header                     |
| `+` (added)      | `#5FD787` (bright lime) | bold   | Universally reads as "new" / "good"                    |
| `~` (modified)   | `#FFD787` (warm amber)  | bold   | Distinct from both green and red, matches STATUS color |
| `-` (deleted)    | `#FF5F5F` (soft red)    | bold   | Universally reads as "removed"                         |
| File path        | `#87AFFF` (cyan-blue)   | normal | Matches existing CHAT/DIFF/PLAN drawer path color      |
| Path basename    | `#87AFFF`               | bold   | Subtle bold on basename so the file _name_ pops        |

The bold-basename treatment is the small flourish that makes the list feel polished: directory parts dim slightly while
the actual filename is what your eye lands on.

Ascii sketch of the rendered block (color cues in brackets):

```
DELTAS:                                                       [bold cyan]
  [+] src/sase/ace/changespec/[deltas.py]                     [+ green-bold]  [path cyan, basename cyan-bold]
  [+] tests/[test_deltas_parsing.py]
  [~] src/sase/ace/changespec/[models.py]                     [~ amber-bold]
  [~] src/sase/ace/changespec/[parser.py]
  [-] src/sase/legacy/[old_deltas.py]                         [- red-bold]
```

### Fold Behavior

DELTAS gets its own fold state (`deltas_collapsed`) that cycles through three levels, matching the pattern established
by TIMESTAMPS:

- **COLLAPSED**: section hidden entirely (zero visual footprint)
- **EXPANDED**: header + a one-line **summary** in the form `+3 ~2 -1 (6 files)` — color-coded counts with a dim total
- **FULLY_EXPANDED**: header + full list

EXPANDED is the new default for any CL with more than ~10 deltas (configurable later); below that, FULLY_EXPANDED reads
fine as a flat list. This protects the user from huge diff dumps while still surfacing the shape of the CL.

A keybinding will be added to toggle this fold level (specific key TBD in Phase 5; needs an unused key in the existing
fold-keymap config).

### Data Model

New dataclass `DeltaEntry` in `models.py`:

```python
@dataclass
class DeltaEntry:
    path: str           # relative to repo root
    change_type: str    # "A" (added), "M" (modified), "D" (deleted)
```

Internally we store the long form (`A`/`M`/`D`) and translate to/from the on-disk single-char glyph (`+`/`~`/`-`) at the
serializer/parser boundary. This keeps downstream code reading `entry.change_type == "A"` rather than poking at glyphs.

Add `deltas: list[DeltaEntry] | None = None` to the `ChangeSpec` dataclass. `None` means "never computed for this CL"
which is distinct from `[]` ("computed and there are zero file changes"); the on-disk format only writes the section
when the list is non-empty, but the in-memory distinction matters for sync logic.

### Computing Deltas From VCS

A new pure function `compute_deltas(changespec, vcs_provider) -> list[DeltaEntry]`:

1. Resolve the parent ref. For ChangeSpecs with a `PARENT:` field, use the parent CL's head commit; otherwise use the
   project's mainline ref (e.g. `origin/master`).
2. Resolve the head ref. For active CLs this is the local branch tip; for submitted CLs it's the merge commit recorded
   on the CL.
3. Ask the VCS provider for a name-status diff between the two refs. New abstract method on the VCS provider:
   `diff_name_status(parent_ref, head_ref) -> list[DeltaEntry]`.
4. Implementations land in each existing VCS provider (bare git, GitHub PR, Mercurial, etc.) using each tool's native
   command. Status mapping: `A`→`A`, `M`→`M`, `D`→`D`, `R`→emit both `D` of source and `A` of target, anything else
   (`C`, `T`, `U`) → coerce to `M` and log a warning.
5. Sort the result alphabetically by path.

This function is the single source of truth — every update path calls it and writes the result via the atomic-write
pipeline.

### Sync Lifecycle

DELTAS must be refreshed any time the underlying file change set could have moved. The integration points map onto
existing event hooks rather than introducing a new signaling mechanism:

| Trigger                     | Why                                              | Where to hook                                                                       |
| --------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------- |
| New `COMMITS` entry created | A real commit (or proposal) just added to the CL | `add_commit_entry_with_id`, `add_proposed_commit_entry` (`commit_utils/entries.py`) |
| Proposal accepted           | Renumbered commit history changes diff base      | Accept workflow                                                                     |
| Rewind                      | Commits removed → delta set shrinks              | `rewind/renumber.py`                                                                |
| Sync from upstream          | New parent ref → diff base shifts                | `_sync_task` (`ace/tui/actions/sync.py`)                                            |
| Parent CL changed (rebase)  | New parent → diff base shifts                    | Rebase / re-parent workflows                                                        |
| Manual refresh              | Escape hatch when something gets out of sync     | New `sase changespec sync-deltas -c <cl>` CLI                                       |

Every hook calls the same `update_changespec_deltas_field()` helper, which:

1. Acquires `changespec_lock`
2. Computes the new deltas via `compute_deltas`
3. Rewrites the DELTAS section in place (or removes it when the list is empty)
4. Writes atomically

A failed VCS query is logged and leaves the existing DELTAS untouched — never half-write a stale or empty section.

### TIMESTAMPS Integration

Skipping a `DELTAS_REFRESH` timestamp event in v1 — DELTAS changes are noisy (every commit triggers one) and would
clutter the audit trail. If users later want this, it's a one-line addition.

## Implementation Phases

Each phase is sized to be picked up by a fresh agent instance with only the plan file as context. Phases 1–2 are
sequential; 3–4 can run in parallel after 2 lands; 5 closes the loop.

### Phase 1: Data Model, Parsing, Serialization

**Goal**: A ChangeSpec read from a `.gp` file with a DELTAS section round-trips cleanly through parse → serialize.

**Files**:

- `src/sase/ace/changespec/models.py` — `DeltaEntry` dataclass; `deltas` field on `ChangeSpec`
- `src/sase/ace/changespec/section_parsers.py` — `parse_deltas_line()` (regex `^\s{2}([+~\-])\s+(.+)$`)
- `src/sase/ace/changespec/parser.py` — register `DELTAS:` header in section dispatch; backwards-compat for old files
  (no DELTAS section → `deltas=None`)
- `src/sase/ace/changespec/raw_text.py` — make sure raw extraction preserves DELTAS body
- New: `src/sase/ace/changespec/deltas_format.py` (or fold into existing format module) — `format_deltas_field()` that
  emits the section text from `list[DeltaEntry]`, including alphabetical sort and the `+`/`~`/`-` glyph mapping; emits
  nothing when the list is empty

**Tests**: `tests/test_deltas_parsing.py`

- Parse a fixture with all three change types
- Round-trip parse → format equals original text
- Backwards compat: parse a CS with no DELTAS section → `deltas is None`
- Empty list → no section emitted
- Path with spaces parses correctly

**Out of scope this phase**: VCS computation, display, atomic write helper.

### Phase 2: Atomic Update Helper

**Goal**: A single entry point that, given a CL name and a `list[DeltaEntry]`, safely writes the DELTAS section.

**Files**:

- New: `src/sase/ace/deltas/persistence.py` (mirroring `ace/hooks/persistence.py`)
  - `update_changespec_deltas_field(project_file, cl_name, deltas)` — locked read-modify-write
  - Replaces existing DELTAS section, inserts one if absent, removes it if `deltas == []`
- Section ordering rule: insert DELTAS between COMMITS and HOOKS (or between COMMITS and the next existing section if
  HOOKS is absent). Codify the canonical section order in one place to prevent drift.

**Tests**: `tests/test_deltas_persistence.py`

- Write into a CS with no prior DELTAS section
- Replace an existing DELTAS section
- Remove the section when given an empty list
- Concurrent writers don't clobber (use the same lock-stress harness as the HOOKS persistence tests)

### Phase 3: VCS Computation

**Goal**: `compute_deltas(changespec, vcs_provider)` returns the correct delta list for any supported VCS.

**Files**:

- New: `src/sase/ace/deltas/compute.py` — the parent/head ref resolution + VCS dispatch
- VCS provider interface: add abstract `diff_name_status(parent_ref, head_ref) -> list[DeltaEntry]` to the base class,
  implement for each existing provider (bare git, GitHub PR provider, Mercurial, etc.). Each implementation uses its own
  native command — no shelling out from the core layer.
- Status-letter mapping (with `R` → split into `D + A`) lives in one shared helper to keep behavior consistent.

**Tests**: `tests/ace/deltas/test_compute.py`

- Mock VCS provider returns canned name-status output → asserts mapping
- Parent ref selection: PARENT-aware vs mainline fallback
- Renames split correctly into delete+add
- Failed VCS query → raises a typed error that callers can catch (not `Exception`)

Real-VCS integration tests (one per provider) verify the `diff_name_status` implementations against fixture repos.

### Phase 4: TUI / CLI Rendering

**Goal**: DELTAS renders beautifully in both the CLI display and the TUI ChangeSpec detail widget, with fold support.

**Files**:

- `src/sase/ace/display.py` — render section with the palette above; bold-basename treatment; alphabetical entries
- `src/sase/ace/tui/widgets/changespec_detail.py` — Textual rendering matches CLI styling
- New: `src/sase/ace/tui/widgets/deltas_builder.py` — fold-aware builder (collapsed / expanded summary / fully expanded
  list)
- `src/sase/ace/tui/state/fold_state.py` — add `deltas_collapsed: FoldLevel`
- `src/sase/default_config.yml` — keybinding for cycling DELTAS fold (TBD: pick an unused key, document in keybinding
  footer)
- Vim/Treesitter syntax highlighting for `.gp` files (if the project ships one) — color the `+`/`~`/`-` prefix

**Tests**:

- Snapshot test of the rendered block at each fold level
- Summary line counts match input
- Empty DELTAS → section not rendered

### Phase 5: Sync Integration & CLI

**Goal**: DELTAS stays in sync automatically across every relevant lifecycle event, plus a manual escape hatch.

**Files**:

- `src/sase/workflows/commit_utils/entries.py` — call `update_changespec_deltas_field` after `add_commit_entry_with_id`
  and `add_proposed_commit_entry`
- `src/sase/workflows/rewind/renumber.py` — refresh after rewind completes
- `src/sase/ace/tui/actions/sync.py` — refresh after successful sync
- Accept-proposal workflow — refresh after proposal renumbering
- Re-parent / rebase workflow — refresh after PARENT change
- New CLI: `sase changespec sync-deltas -c <cl_name>` (with short opts per project convention) for manual recompute
- Wire into `sase commit` end-of-commit flow as a fail-safe (best-effort, don't block the commit on it)

**Tests**: end-to-end

- Create a CS, commit a file → DELTAS contains it as `A`
- Modify the file in a follow-up commit → DELTAS still shows it once, as `M` (cumulative against parent ref, not
  per-commit)
- Delete the file → DELTAS shows `D`
- Add then delete the same file in two commits → file disappears from DELTAS (net zero)
- Rewind a commit → DELTAS shrinks accordingly
- VCS query failure → existing DELTAS preserved, error logged
- Manual `sase changespec sync-deltas` recomputes correctly

### Phase 6 (optional, defer to follow-up CL)

- Rename detection (`R old -> new` form)
- Per-file line counts (`+10/-3`) appended to each entry
- DELTAS-driven hook scoping (run linters only on changed files)

## Edge Cases

- **No PARENT field**: fall back to project mainline ref (configurable per project; default `origin/master` or
  equivalent for non-git VCS)
- **Submitted/Archived CLs**: still show DELTAS based on the recorded merge commit; never recompute (the underlying
  branch may be gone)
- **Detached / pre-commit CLs**: no commits yet → `DELTAS` section is omitted (empty list)
- **Path encoding**: paths with non-ASCII characters are written as-is (the `.gp` file is UTF-8); parser must not strip
  trailing whitespace from paths
- **Very large CLs (1000+ files)**: rendering must not block the TUI; the FULLY_EXPANDED level is the user's call to
  load it. Fold default of EXPANDED with a summary line covers this.
- **Concurrent writers**: existing `changespec_lock` mechanism handles this; sync hooks must not deadlock by holding the
  lock across the VCS query. Pattern: query first (no lock held), then acquire lock to write.
- **VCS query fails / parent ref missing**: log a warning, do not modify the existing DELTAS section, do not crash the
  caller (commit, sync, etc. must succeed even if delta refresh fails)

## Open Questions for the User

1. **Section ordering**: I've placed DELTAS between COMMITS and HOOKS. Is that the right slot, or would you rather see
   it directly under DESCRIPTION as a "what does this CL touch?" header?
2. **Fold default for small CLs**: my proposal is FULLY_EXPANDED below ~10 deltas, EXPANDED above. Want a single default
   instead?
3. **Glyph choice**: I picked `+ ~ -` to read like a diff. Open to `A M D` if you prefer alphabetic codes — easier to
   grep, slightly less pretty.
