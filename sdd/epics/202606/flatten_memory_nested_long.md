---
create_time: 2026-06-17 17:51:32
status: done
prompt: sdd/prompts/202606/flatten_memory_nested_long.md
bead_id: sase-4u
tier: epic
---
# Plan: Flatten `memory/` + Nested Long-Term Memory (hub notes)

## Summary

Two coupled changes to the SASE memory system:

1. **Flatten `memory/`** — collapse `memory/short/` and `memory/long/` into a single flat `memory/` directory. Tier is
   no longer encoded by directory; it moves into a required `type:` frontmatter field (`short` | `long`).
2. **Nested long-term memory ("hub notes")** — a required `parent:` frontmatter field lets a long-term note declare
   another long-term note as its parent. Reading a note with `sase memory read` then prints a `## Children` section
   linking every long-term note whose `parent` is that note. AGENTS.md keeps listing only top-level notes (parent = the
   AGENTS.md file); nested notes are discovered by navigating from their parent.

Migrate this repo's `memory/` and the chezmoi repo's `~/.local/share/chezmoi/home/memory/` to the new format, run
`chezmoi apply --force`, and prove the work is complete with `sase init` reporting no recommended changes.

## Goals

- Every non-README markdown file under `memory/` carries required frontmatter:
  - `type:` — enum, `short` or `long` (the source of truth for tier after flattening).
  - `parent:` — `AGENTS.md` for top-level notes, or `memory/<file>.md` for a note nested under another long-term note.
  - `description:` — required for `long` notes (rendered in AGENTS.md Tier 2 and in `## Children`); omitted for `short`
    notes (always-loaded; never rendered with a description).
- `sase amd init` / `sase memory init` keep generating AGENTS.md in its current shape (Tier 1 short list, Tier 2 long
  list), now reading tier/description from frontmatter and listing only top-level long notes.
- `sase memory read <note>` appends a `## Children` section, formatted exactly like AGENTS.md's Tier 2 entries, listing
  the long-term children of the note (omitted when there are none).
- Both the project repo and the chezmoi repo are migrated; `chezmoi apply --force` is run.
- Acceptance: `sase init` (which checks both the project root and the chezmoi home root) reports nothing to do, and
  `just check` is green.

## Non-Goals

- We do **not** restructure existing notes into hubs. Existing long notes stay top-level (`parent: AGENTS.md`). The
  nesting _capability_ is delivered and tested with fixtures; reorganizing real notes into hubs is left for the user to
  do later.
- No move of memory logic into the Rust core. The entire memory subsystem (inventory, AMD rendering, frontmatter, read
  auditing, proposals) is Python in this repo and is consumed only by Python CLI/TUI code; it is a file-format + CLI
  concern, not cross-frontend backend behavior. We keep it in Python, consistent with where it lives today.

## Key Design Decisions

### Frontmatter shape (canonical, deterministic)

```markdown
---
type: long
parent: AGENTS.md
description: Read anytime new CLI subcommands or options are added.
---

# CLI Rules

...
```

- Key order is fixed: `type`, then `parent`, then `description`. Values are emitted one-per-line with no wrapping (so
  long descriptions stay on a single line). A **single canonical serializer** is the only way frontmatter is written,
  used by BOTH the migration and the generator, so `sase init --check` is byte-stable.
- `README.md` is exempt (no frontmatter).

### Parent / children model

- `parent` is a path relative to the note's root, in the same coordinate space AGENTS.md already uses: `AGENTS.md`
  (top-level) or `memory/<file>.md` (nested). This is uniform across the project root and the chezmoi home root.
- Only `long` notes may have a non-`AGENTS.md` parent; `short` notes are always `parent: AGENTS.md`.
- "Children of X" = every `long` note whose `parent` resolves to X. A top-level hub note (listed in Tier 2) can itself
  have children, giving an AGENTS.md → hub → child navigation path.
- The same renderer produces both AGENTS.md Tier 2 entries and the `## Children` block: ``**`memory/<file>.md`**``
  followed (markdown hard break = two trailing spaces) by the description on the next line; entries separated by a blank
  line; children sorted by path. `## Children` is omitted entirely when a note has no children.

### `sase memory read` after flattening

- Accepts a flat note name relative to `memory/` (`sase memory read cli_rules.md`), tolerating an optional leading
  `memory/`. Short notes remain unreadable by this command (they are always-loaded); the rejection is now driven by the
  note's `type`, not by a directory name.
- Still resolves project `memory/` first, then `~/memory/`. Still strips leading frontmatter from the body. After the
  body, appends the `## Children` section computed from the note's root.

### Generation reflects reality (layout-aware, transitional)

- AGENTS.md is rendered from the _actually discovered_ notes (their real relative paths + frontmatter), not from a
  hardcoded `short`/`long` directory assumption. Tier 1 = `@`-references to all `short` notes; Tier 2 = top-level `long`
  notes (`parent: AGENTS.md`) with descriptions.
- During the migration window the discovery/generation layer understands **both** the legacy nested layout and the new
  flat layout (tier inferred from directory when frontmatter is absent), so each root can be migrated independently
  while `sase init --check` stays clean. This dual-layout support is explicitly removed in the final cleanup phase once
  every root is flat.

### Hard invariant for every phase

`just check` runs `sase validate`, which runs `sase init --check` against the real repo. `amd_init_roots` includes the
chezmoi home root when chezmoi is active, so **both** the project root and the chezmoi home root must report "nothing to
do" at the end of every phase. This is why generation is made layout-aware (so an un-migrated root keeps matching its
own on-disk files) and why the cleanup of dual-layout support is the last phase.

## Surface Area (for reference)

- Foundation/new: `src/sase/memory/notes.py` (proposed).
- Discovery/inventory: `src/sase/memory/inventory.py` (`_iter_memory_files`, `_is_memory_path`, `_MEMORY_PATH_RE`,
  `_MEMORY_RELATIVE_TIERS`, `_candidate_paths`).
- Read command: `src/sase/memory/cli_read.py`, `src/sase/memory/read_log.py` (`ALLOWED_READ_SUBDIRS`,
  `validate_memory_read_path`), `src/sase/main/parser_memory.py` (help text).
- AGENTS.md generation: `src/sase/amd/_memory.py`, `src/sase/amd/_agents_doc.py`.
- Memory init: `src/sase/main/init_memory/constants.py` (`MINIMAL_AGENTS_CONTENT`), `src/sase/main/init_memory/roots.py`
  (`_render_memory_readme`, generated `sase.md` path, `_is_memory_markdown_path`),
  `src/sase/main/init_memory/formatting.py`.
- Proposals: `src/sase/memory/proposals/validation.py` (`long/<slug>.md`), `src/sase/memory/proposals/write.py`.
- Skill source: `src/sase/xprompts/skills/sase_memory_read.md` (generated; regenerate via `sase init-skills --force` +
  `chezmoi apply`).
- Repo data: `memory/short/*.md`, `memory/long/*.md`, `memory/README.md`, `AGENTS.md`.
- chezmoi data: `~/.local/share/chezmoi/home/memory/{short,long}/*.md`, `.../memory/README.md`,
  `~/.local/share/chezmoi/home/AGENTS.md`.
- Tests: ~15 files reference `memory/short`, `memory/long`, `long/<...>` canonical paths, or `ALLOWED_READ_SUBDIRS`
  (init/amd/inventory/read-log/proposals/TUI display fixtures).

---

## Phases

Each phase is completed by a distinct agent, is independently shippable, ends with `just check` green (hence
`sase init --check` clean for both roots), and depends only on the phases before it.

### Phase 1 — Memory-note foundation (additive, no wiring)

Goal: a single, well-tested module that owns the new format. Nothing else is rewired yet, so behavior and `sase init`
output are unchanged.

- Add `src/sase/memory/notes.py` providing:
  - A `MemoryNote` model: root-relative path, `type`, `parent`, `description`, body.
  - Frontmatter parsing with transitional fallback (tier from `short`/`long` directory when `type` is absent; `parent`
    defaults to `AGENTS.md`).
  - The canonical frontmatter serializer + an "apply frontmatter to existing text" helper (generalizing
    `amd/_memory.py`'s current `_with_description_frontmatter`).
  - `discover_memory_notes(root)` understanding both flat (`memory/*.md`, excluding `README.md`) and legacy nested
    (`memory/short|long/**.md`) layouts.
  - `children_of(...)`, the shared reference-list renderer, and `validate_notes(...)` (missing/invalid `type` or
    `parent`, parent not found, parent not a long note / AGENTS.md, duplicate flat names, cycles, a long note parented
    under a short note).
- Comprehensive unit tests for the module.

Verification: `just check` green; `sase init --check` output unchanged.

### Phase 2 — `sase memory read`: flat paths + `## Children` (additive)

Goal: the read command speaks the new flat path scheme and renders children, without changing any generated files.

- Rework read-path validation to accept a flat note name (optionally `memory/`-prefixed), keep accepting legacy
  `long/<name>.md` for now, and reject `short`-typed notes based on frontmatter `type`.
- After printing the (frontmatter-stripped) body, append `## Children` (built from the foundation) when the note has
  long-term children; omit it otherwise.
- Update `parser_memory.py` read/help examples to show the flat form (keep legacy examples working).
- Tests: flat resolution, legacy resolution, short-note rejection, children rendering, empty-children omission.

Verification: `just check` green. For the current (un-migrated) repo there are no `parent` fields, so children are empty
and output is unchanged; `sase init --check` stays clean.

### Phase 3 — Flip generation to be format-driven + migrate the PROJECT repo + proposals

Goal: the generator renders from discovered notes/frontmatter (layout-aware), the project repo is migrated to flat +
frontmatter, and `sase memory write` proposes flat notes. The chezmoi home root is untouched and stays clean because
generation matches each root's actual layout.

- Generation: rewire `amd/_memory.py` (and `_agents_doc.py` parsing) to use the foundation — Tier 1 from `short` notes,
  Tier 2 from top-level `long` notes, descriptions from frontmatter, paths taken from the notes' real locations. Update
  Tier 2 boilerplate wording that hardcodes `memory/long/*.md`.
- Memory init: make the generated `sase.md` and `README.md` targets and content layout-aware (flat once the root has no
  `short`/`long` dirs), include canonical frontmatter on the generated `sase.md` (`type: short`, `parent: AGENTS.md`),
  update the README body to describe the flat + frontmatter model, and generalize the existing "inject description
  frontmatter" step into an idempotent canonical-frontmatter sync that preserves an author-specified `parent`. Update
  `_is_memory_markdown_path`.
- Migrate the project's `memory/`:
  - `git mv` each `memory/short/X.md` → `memory/X.md` and `memory/long/Y.md` → `memory/Y.md`.
  - Write canonical frontmatter into each migrated file using the foundation serializer: `type` from the source
    directory; `parent: AGENTS.md`; for long notes, `description` captured from the **current** AGENTS.md Tier 2 entry
    (by old path) so descriptions are not lost when paths change.
  - `git rm` the old generated `memory/short/sase.md`; remove the now-empty `short/`,`long/` dirs.
  - Run `sase init` (write) to regenerate the flat `memory/sase.md`, `memory/README.md`, and AGENTS.md, then confirm
    `git status` shows only the intended changes.
- Proposals: change `validate_memory_proposal_target` to a flat one-level `<slug>.md` target, and have proposal
  application write canonical frontmatter (`type: long`, `parent: AGENTS.md`, `description` from the proposal title) for
  the created note.
- Update affected tests/fixtures (amd, init-memory, inventory, proposals, and TUI/notification display fixtures that
  hardcode `long/<...>` canonical paths).

Verification: `just check` green; `sase init --check` clean for both the flat project root and the still- nested chezmoi
root; `sase memory read cli_rules.md` works with flat paths.

### Phase 4 — Migrate the chezmoi repo + skill/docs + `chezmoi apply --force`

Goal: bring the chezmoi home root onto the new format and refresh the generated skill/doc text.

- Migrate `~/.local/share/chezmoi/home/memory/`: flatten `short/obsidian`?/`long/obsidian.md` and `short/sase.md` into
  flat files with canonical frontmatter (obsidian → `type: long`, `parent: AGENTS.md`, preserve its existing
  `description`; sase → `type: short`, `parent: AGENTS.md`), update its `README.md`, and regenerate the chezmoi home
  `AGENTS.md` (run `sase init` for the home root) so Tier 1/Tier 2 use flat paths.
- Update the skill source `src/sase/xprompts/skills/sase_memory_read.md` to the flat path scheme and to mention the
  `## Children` output; refresh its description text that references `memory/long/...`. Regenerate skills with
  `sase init-skills --force`.
- Update any remaining human-facing docs/README/wording referencing the `short/`,`long/` tiers.
- Run `chezmoi apply --force` to deploy regenerated skill files and migrated home memory/AGENTS.md.

Verification: `just check` green; `sase init --check` clean for both roots (both now flat); skill check clean
(regenerated files match sources).

### Phase 5 — Remove transitional dual-layout support + final acceptance

Goal: delete the scaffolding now that every root is flat, leaving a clean flat-only system.

- Remove nested-layout handling from discovery/inventory (`memory/short|long` scanning, the directory→tier fallback, the
  legacy `long/<name>.md` read prefix, nested regexes/candidate-path special cases) and from `_agents_doc.py` (legacy
  headings/paths). Drop the layout-aware branches in generation; generation is now flat-only.
- Tighten validation so missing/invalid `type`/`parent` is a real blocker (all real notes now comply).
- Update/trim any tests still exercising the nested layout.
- Final acceptance: run `sase init` and confirm "nothing to do" for both roots; `just check` green; spot-check
  `sase memory read` (including a fixture-backed hub note with children) and `sase memory list`.

Verification: `just check` green; `sase init` reports no recommended changes — the user's acceptance test.

---

## Acceptance Criteria

- `memory/` is flat in both repos; every non-README note has valid `type`/`parent` (and `description` for long notes)
  frontmatter.
- AGENTS.md (both roots) lists Tier 1 short notes and Tier 2 top-level long notes with descriptions, using flat paths.
- `sase memory read <long-note>` prints the body followed by a `## Children` section (when children exist), formatted
  identically to AGENTS.md Tier 2.
- Nested long notes are reachable by navigating parent → children; they are not listed directly in AGENTS.md.
- `chezmoi apply --force` has been run; `sase init` reports nothing to do for the project and chezmoi home roots;
  `just check` is green.

## Risks & Mitigations

- **Breaking `sase init --check` mid-migration** (the central risk): mitigated by layout-aware generation (each root
  matches its own on-disk layout) and by migrating one root per phase, with cleanup last.
- **Description loss when paths change** (Tier 2 descriptions are keyed by path): mitigated by capturing descriptions
  from the current AGENTS.md into frontmatter during the project migration, before regenerating.
- **Frontmatter byte-drift** between migration and generator (would make `sase init` perpetually dirty): mitigated by a
  single canonical serializer used by both, plus an idempotent frontmatter sync.
- **Generated-file formatter mangling frontmatter**: the markdown formatter must run on the body only; frontmatter is
  applied after formatting.
- **Wide test fan-out**: ~15 test files hardcode the old tiers/paths; each touching phase updates the tests it affects
  so `just check` stays green per phase.
