---
create_time: 2026-06-26 15:48:19
status: done
bead_id: sase-5b
tier: epic
prompt: sdd/prompts/202606/inline_short_term_memory.md
---
# Plan: Inline Short-Term Memory Into `AGENTS.md` (Drop `@` References)

## Goal

Some LLM providers do not support the `@<path>` "file import" syntax that SASE currently uses to compose
agent-instruction files. Make `sase memory init` produce **self-contained** instruction files instead:

1. **Inline short-term (Tier 1) memory** directly into `AGENTS.md` instead of listing `@memory/<file>.md` references.
2. **Make every provider instruction file identical to `AGENTS.md`.** Today `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and
   `OPENCODE.md` are one-line shims containing `@AGENTS.md`. After this work each provider file must contain the _exact
   same content_ as `AGENTS.md` (a full copy, no `@AGENTS.md` import).

The end state: no `@` import syntax anywhere in generated `AGENTS.md` or provider files. Long-term (Tier 2) memory
continues to be referenced by description only (it is read on demand via `sase memory read`), so the Tier 2 section is
unchanged.

## Background — How It Works Today

`sase memory init` regenerates each "memory root" (the project root and the user's home/chezmoi root). The relevant
pieces:

- **Memory files** live flat under `memory/*.md`, each with YAML frontmatter `type: short|long` and `parent`.
  - `type: short` files = Tier 1, always-loaded context.
  - `type: long` files = Tier 2, on-demand reference material.
  - `memory/sase.md` is itself **generated** (workspace + linked-repo boilerplate) and is a short note.
- **Managed `AGENTS.md`** is rendered by `src/sase/amd/_memory.py::_render_managed_agents`. It emits:
  - An H1 title, a "do not modify" notice.
  - `## Tier 1 (short-term) Memory` → a bullet list of `- @memory/<file>.md` (built by `_short_memory_references`).
  - `## Tier 2 (long-term) Memory` → a `**`memory/<file>.md`**` + description list.
- **Minimal `AGENTS.md`** (`src/sase/main/init_memory/roots.py::_minimal_agents_content`) is used when a root has no
  managed title; it is `# Agent Instructions\n\n@memory/sase.md\n` and is only written when `AGENTS.md` is missing.
- **Provider shims**: `src/sase/amd/_shared.py::provider_shim_specs` writes `CLAUDE.md`/`GEMINI.md`/`QWEN.md`/
  `OPENCODE.md` whose content is `@AGENTS.md` (project), `@~/AGENTS.md` / `@/abs/AGENTS.md` (live home), or
  `CLAUDE.md.tmpl` containing `@{{ .chezmoi.homeDir }}/AGENTS.md` (chezmoi home). Constants live in
  `src/sase/amd/constants.py`.
- **Reachability validation**: `src/sase/memory/inventory.py::unreferenced_memory_files_for_init` walks `@` and plain
  `memory/...` references from `AGENTS.md`; any `memory/*.md` file not reachable from `AGENTS.md` blocks init.
- **Display/inventory**: `sase memory list` (`build_memory_inventory`) and `sase memory agent-docs list`
  (`src/sase/amd/inventory.py`, `src/sase/amd/_agents_doc.py`) parse the short-section `- @memory/...` bullets to count
  loaded memory.

The recent commit `28de35737` ("migrate H3 memory headers to H2 in prep for inline short-term memories") already shifted
the in-repo short notes so they use H2 for top-level subsections — this plan is the follow-up that consumes that prep
work.

## Target Behavior

### Memory file structure contract

A memory markdown file (body, excluding frontmatter) must have:

- Exactly one **H1** as its first heading (the file's title).
- Zero or more **H2** sections; each H2 may have zero or more **H3** sections.
- **No H4, H5, or deeper headings.** (`#` characters inside fenced code blocks are content, not headings, and are
  exempt.)

`sase memory init` must reject (with a clear blocker, not a crash) any **short** note that violates this contract,
because such a file cannot be inlined correctly. (Long notes are not inlined; scope structural enforcement to short
notes to avoid disturbing existing long notes.)

### Inlined `## Tier 1` section

For each short note (alphabetical by path, `memory/sase.md` included), inline its content under an H3 header derived
from the note's H1 title, shifting every heading **down by two levels**:

- File H1 (`# Title`) → consumed into the section header `### memory/<file>.md (Title)` (not repeated in the body).
- File H2 (`##`) → H4 (`####`).
- File H3 (`###`) → H5 (`#####`).
- Fenced code blocks are copied verbatim (their `#` comment lines must never be treated as headings).

Example (managed `AGENTS.md`):

```markdown
## Tier 1 (short-term) Memory

The following memory contains core (always loaded) context:

### memory/build_and_run.md (Build & Run Commands)

​`bash just install       # Install in editable mode with dev deps ​`

#### IMPORTANT: You MUST Run `just check` if you Made File Changes

...body...

##### Exceptions

...body...

#### PNG Snapshot Tests

...body...

### memory/glossary.md (Glossary of Terms Specific to SASE)

...body...

### memory/sase.md (SASE = Structured Agentic Software Engineering)

#### Ephemeral `sase_<N>` Workspace Directories

...body...

## Tier 2 (long-term) Memory

...unchanged...
```

The `## Tier 1`/`## Tier 2` H2 headings still bound the sections correctly because all inlined headings are H3 or deeper
(the section parser scans for the next `##`).

### Provider files

`CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md` each contain a byte-for-byte copy of that root's final `AGENTS.md`
content. No `@AGENTS.md`. For chezmoi home, because the inlined content has no template variables, provider files become
**static** copies (plain `CLAUDE.md`, not `CLAUDE.md.tmpl`), matching how the home `AGENTS.md` source file is already
handled.

## Key Design Decisions & Gotchas (read before implementing any phase)

1. **Header shifting must be fence-aware.** `memory/build_and_run.md` contains a fenced `bash` block whose comments
   start with `#`. The existing `_increment_markdown_headings` in `src/sase/history/chat.py` is _not_ fence-aware and
   must not be reused as-is. Model the fence handling on
   `src/sase/main/init_memory/formatting.py::format_generated_memory_markdown`.

2. **Single-pass idempotency for the generated `memory/sase.md`.** `memory/sase.md` is regenerated every run, and its
   fresh body must be the one inlined into `AGENTS.md` in the **same** run. Today `_render_managed_agents` reads notes
   from disk via `discover_memory_notes`, which would inline a _stale_ `sase.md` and require a second `init` to
   converge. The inlining must use the freshly generated `sase.md` body (thread it in as an overlay, or reorder so
   generation precedes rendering). The existing idempotency test
   `tests/main/test_init_memory_handler.py::test_init_memory_plan_empty_after_prettier_formats_generated_files` (asserts
   `plan.actions == ()` after one run) is the guard — it must stay green.

3. **Reachability after inlining.** Once short notes are inlined rather than `@`-referenced, the reachability walk in
   `unreferenced_memory_files_for_init` would flag every short note as "unreferenced." Fix by treating `type: short`
   notes as inherently reachable (they are always inlined). Do **not** rely on the inlined `### memory/<file>.md` header
   text incidentally matching the plain-path regex — make short-note reachability explicit.

4. **Provider content is derived from the root's _final_ `AGENTS.md` content**, which is: the managed render when
   managed; the existing on-disk `AGENTS.md` when the minimal template is `create_if_missing` and the file already
   exists; otherwise the freshly rendered minimal template. Thread this content into provider planning rather than
   reading a possibly-stale file.

5. **Keep legacy-shim recognition for migration.** Existing provider files still contain `@AGENTS.md`, `@~/AGENTS.md`,
   `@{{ .chezmoi.homeDir }}/AGENTS.md`, or `@/abs/AGENTS.md`. The "is this a managed shim safe to overwrite/delete"
   logic (`_is_provider_shim_text` / `_PROVIDER_SHIM_TEXTS` / `_ABSOLUTE_AGENTS_IMPORT_RE` in `_shared.py`) must keep
   recognizing those legacy strings so they migrate cleanly to full copies. Custom (user-authored) provider content is
   already overwritten today; preserve that behavior.

6. **`sase memory list` / `agent-docs list` accuracy.** These commands parse the old `- @memory/...` bullets to count
   and mark "loaded" short memory. After inlining, update the short-section parser
   (`src/sase/amd/_agents_doc.py::_short_memory_paths`) to recognize inlined `### memory/<file>.md (Title)` headers, and
   ensure `build_memory_inventory` still reports inlined short notes as loaded (their bytes live in `AGENTS.md`).

7. **No automated repo-freshness gate.** Nothing in `just check`/CI runs `sase memory init --check` against the repo's
   own files, so phases that change the renderer do **not** need to regenerate the committed `AGENTS.md`/`CLAUDE.md`
   mid-stream; the old committed files remain valid markdown. Regeneration happens once at the end (final phase). All
   in-repo tests are hermetic (`tmp_path`).

8. **Prettier stability.** Generated `AGENTS.md` and the provider copies are committed and pass repo-wide prettier
   (`--prose-wrap=always --print-width=120`) via pre-commit/`just check`. The inlined output must be prettier-stable
   (memory bodies are already prettier-formatted; only heading levels and surrounding blank lines change). Verify by
   running prettier on the regenerated files.

9. **Both target repos use the managed path.** The sase repo and `~/projects/github/bobs-org/bob-cli/` both render a
   managed `AGENTS.md` (they have a title via config/onboarding). The minimal-template path is an edge case for
   completeness; get it right but it is not on the critical path.

10. **Every phase must run `just install` then `just check`** (lint + mypy + the full test suite, including visual
    snapshots) and leave them green before handing off. `just install` is required first because workspace virtualenvs
    may be stale.

## Phase Breakdown

Four sequential phases. Each is implemented by a distinct agent; each must leave the tree green (`just check` passing).

---

### Phase 1 — Inlining + structure-validation helpers (pure functions)

**Goal:** Add well-tested, dependency-free helpers that later phases wire into `sase memory init`. No behavior change to
the command yet.

**Add** a new module (e.g. `src/sase/amd/inline_memory.py`) exposing:

- `_extract_memory_title(body: str) -> str | None` — the text of the first H1 (`# `) heading, fence-aware.
- `validate_short_memory_structure(body: str) -> str | None` — returns an error message (or `None` if valid) enforcing:
  exactly one H1 as the first heading, headings only at H1/H2/H3, no H4+; `#` inside fenced blocks ignored.
- `inline_memory_section(relative_path: str, body: str) -> str` — produces the inlined block
  `### {relative_path} ({title})` followed by a blank line and the body with its H1 stripped and remaining headings
  shifted +2 (H2→H4, H3→H5), code fences copied verbatim. Output should be prettier-stable (single trailing newline
  semantics consistent with how `_render_managed_agents` joins lines).

**Tests:** New unit test module covering — fence-protected `#` comment lines are untouched; H2→H4 and H3→H5 shifting; H1
extraction and stripping; validation passes for H1-only files and for H1+H2+H3 files; validation fails for missing H1,
multiple H1s, and any H4+ heading; a realistic fixture resembling `build_and_run.md` (fenced bash block + H2 + H3).

**Acceptance:** New module + tests added; `just check` green; nothing else changed.

---

### Phase 2 — Inline short-term memory into `AGENTS.md`

**Goal:** `sase memory init` inlines short notes into the managed (and minimal) `AGENTS.md`; reachability, structure
validation, and the inventory/agent-docs parsers are updated; the command stays idempotent in one pass.

**Changes:**

- `src/sase/amd/_memory.py::_render_managed_agents` — replace the `- @memory/...` bullet list (currently from
  `_short_memory_references`) with inlined sections built via the Phase 1 helpers, preserving the
  `## Tier 1 (short-term) Memory` heading and an intro sentence. Keep alphabetical ordering (incl. `memory/sase.md`).
  Inline the **fresh** generated `sase.md` body (see Gotcha #2). Tier 2 rendering is unchanged.
- `src/sase/main/init_memory/roots.py::_minimal_agents_content` — inline the fresh `sase.md` body instead of
  `@memory/sase.md` (eliminate the `@`). Coordinate the freshness threading with the managed path.
- **Idempotency threading** (Gotcha #2): restructure so the generated short-note body(ies) are computed before
  `AGENTS.md` is rendered and supplied to the renderer (overlay or explicit argument), in both `plan_memory_root` and
  `initialize_memory_root`.
- **Reachability** (Gotcha #3): `src/sase/memory/inventory.py` — treat `type: short` notes as reachable in
  `_reachable_memory_files_for_init` (or its helpers) so inlined short notes are not flagged unreferenced.
- **Structure validation** (target contract): validate short notes during init; surface a clear blocker (consistent with
  the existing unreferenced-files error path) when a short note is missing an H1 or contains H4+.
- **Parsers/inventory** (Gotcha #6): update `src/sase/amd/_agents_doc.py::_short_memory_paths` to recognize inlined
  `### memory/<file>.md (Title)` headers so `sase memory agent-docs list` counts short memory correctly; ensure
  `build_memory_inventory` reports inlined short notes as loaded for `sase memory list`.
- Optionally remove/repurpose the now-unused `_short_memory_references` helper and the stale duplicate
  `MINIMAL_AGENTS_CONTENT` constant in `src/sase/main/init_memory/constants.py`.

**Tests to update/add** (provider shims remain `@AGENTS.md` this phase):

- `tests/main/test_init_memory_handler.py` — `test_init_memory_syncs_amd_agents_and_long_memory_descriptions` (replace
  `- @memory/extra.md` / `- @memory/sase.md` assertions with inlined-section assertions); keep the prettier idempotency
  tests green; add a prettier `--check` assertion over the generated **managed `AGENTS.md`** to lock formatting
  stability.
- `tests/main/test_init_memory_agent_docs.py` — `_MINIMAL_AGENTS` and `- @memory/sase.md` assertions for the
  live-home/chezmoi managed `AGENTS.md`.
- `tests/main/test_memory_agent_docs_list.py` — `short_memory_refs` counts now come from inlined headers (the
  `- @memory/...` fixtures that represent managed docs).
- Add tests for: a malformed short note (H4 present / missing H1) blocking init; short notes no longer flagged
  unreferenced; single-pass idempotency with a generated `sase.md`.

**Acceptance:** `AGENTS.md` is fully inlined for short memory with no `@memory/...`; `sase memory init` is idempotent in
one pass; reachability/validation/inventory correct; provider shims untouched; `just check` green.

---

### Phase 3 — Provider files become full, identical copies of `AGENTS.md`

**Goal:** Every provider instruction file is a byte-for-byte copy of its root's final `AGENTS.md`; no `@AGENTS.md`
imports; legacy shims migrate cleanly.

**Changes:**

- `src/sase/amd/_shared.py` — `provider_shim_specs` / `provider_shim_plan` produce provider files whose content is the
  root's final `AGENTS.md` content (threaded in from the caller — Gotcha #4), for project, live-home, and chezmoi roots.
  - **Chezmoi:** switch the preferred path to a **static** `CLAUDE.md` (no `.tmpl`); add the old `CLAUDE.md.tmpl` (and
    any legacy plain shim) to `legacy_paths` for cleanup.
  - Keep legacy `@`-shim recognition (`_is_provider_shim_text`, `_PROVIDER_SHIM_TEXTS`, `_ABSOLUTE_AGENTS_IMPORT_RE`) so
    existing `@AGENTS.md`/`@~/...`/`@{{...}}` files are detected and replaced/deleted; treat "equals the final
    `AGENTS.md` content" as a managed (safe-to-overwrite, no-op-if-equal) state.
- `src/sase/main/init_memory/roots.py` — compute the final `AGENTS.md` content (managed render, existing-on-disk for
  `create_if_missing`, or rendered minimal) and pass it to `provider_shim_plan` in both `plan_memory_root` and
  `initialize_memory_root`.
- `src/sase/amd/constants.py` — retire/repurpose `PROVIDER_SHIM_CONTENT` / `HOME_PROVIDER_SHIM_CONTENT` /
  `CHEZMOI_PROVIDER_SHIM_TEMPLATE_CONTENT` as appropriate (keep what is still needed for legacy recognition; remove what
  is dead).
- Verify `sase memory agent-docs list` provider-status logic (`src/sase/amd/inventory.py::_provider_shims` /
  `provider_status_for_spec`) still classifies the new full-copy files correctly.

**Tests to update:**

- `tests/main/test_init_memory_handler.py::test_init_memory_overwrites_provider_shims` — assert provider files equal the
  root's `AGENTS.md` content.
- `tests/main/test_init_memory_agent_docs.py` — live-home and chezmoi shim assertions (full copy; chezmoi now writes
  plain `CLAUDE.md`, deletes `.tmpl`).
- `tests/main/test_init_memory_chezmoi.py` — `.tmpl` vs static-copy migration assertions, including the plain-shim and
  deferred-deploy cases.
- `tests/main/test_init_memory_agent_docs_list.py` / `tests/main/test_memory_agent_docs_list.py` — provider shim
  content/status helpers.
- `tests/main/test_init_memory_agent_docs.py::test_init_memory_does_not_migrate_single_custom_provider_file` /
  `..._overwrites_multiple_custom_provider_files` — provider files now equal the minimal `AGENTS.md` content.

**Acceptance:** All provider files equal `AGENTS.md` for every root type; legacy `@` shims migrate; chezmoi switches to
static copies with `.tmpl` cleanup; `just check` green.

---

### Phase 4 — Regenerate generated artifacts, update prose, and run `sase memory init` in both repos

**Goal:** Ship the new format into the actual repos and align human-facing prose with the new mechanism.

**Changes:**

- Update generated/prose text that still describes the `@memory/...` loading mechanism so it matches inlining, e.g.
  `src/sase/main/init_memory/roots.py::_render_memory_readme` (the `memory/README.md` text) and any comments/help in
  `src/sase/memory/inventory.py` / `src/sase/amd/inventory.py` that describe "loaded via `@`". Update the long-term
  memory wording only if it is now inaccurate. (Do **not** rewrite the canonical `memory/*.md` short notes' bodies —
  only generated output and code comments.)
- Run `just install`, then **`sase memory init`** in the sase repo to regenerate `AGENTS.md` (inlined),
  `CLAUDE.md`/`GEMINI.md`/`QWEN.md`/`OPENCODE.md` (full identical copies), and `memory/README.md`.
- Run `sase memory init` in `~/projects/github/bobs-org/bob-cli/` to regenerate its `AGENTS.md` and provider files (its
  only short note is the generated `memory/sase.md`).
- **Verify:** regenerated `AGENTS.md` contains no `@memory/...` and no `@AGENTS.md`; each provider file equals
  `AGENTS.md` byte-for-byte; `sase memory init --check` reports no drift (idempotent); prettier is stable over the
  regenerated files; `just check` green in the sase repo.

**Acceptance:** Both repos regenerated to the new self-contained format; idempotent re-run is a no-op; provider files
identical to `AGENTS.md`; documentation prose aligned; `just check` green.

## Out of Scope

- Rewriting the canonical short-note bodies under `memory/` (their structure already conforms after `28de35737`).
- Long-term (Tier 2) memory loading semantics — unchanged.
- Adding new `sase memory` subcommands or options (no CLI surface change → no `cli_rules.md` / generated-skill
  regeneration needed).
- The `@`-import usage in unrelated areas (xprompts, `src/sase/ace/*.md`) — those are a different feature.

## Verification Checklist (final state)

- [ ] Generated `AGENTS.md` inlines every short note as `### memory/<file>.md (Title)` with H2→H4 / H3→H5 shifting and
      verbatim code fences; no `@memory/...`.
- [ ] `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md` are byte-for-byte equal to `AGENTS.md`; no `@AGENTS.md`.
- [ ] `sase memory init` is idempotent in a single pass (`--check` clean after one run) in both the sase repo and
      bob-cli.
- [ ] Malformed short notes (missing H1 / H4+) produce a clear blocker, not a crash.
- [ ] `sase memory list` and `sase memory agent-docs list` report inlined short memory correctly.
- [ ] `just check` is green; regenerated markdown is prettier-stable.
