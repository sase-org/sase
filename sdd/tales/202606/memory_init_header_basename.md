---
create_time: 2026-06-27 16:23:26
status: done
prompt: sdd/prompts/202606/memory_init_header_basename.md
---
# Plan: Include memory file basename in generated H3 headers

## Goal

Change the H3 section headers that `sase memory init` generates when it inlines short-term ("Tier 1") memory notes into
agent-provider files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`, …). Today the header puts the
note's source path first and the parsed title in parentheses:

```
### memory/build_and_run.md (Build & Run Commands)
```

We want the parsed title first (no longer parenthesized) and the **file basename only** (no `memory/` directory, no
`.md` extension) in parentheses, so users get transparent provenance about which file a section was generated from:

```
### Build & Run Commands (build_and_run)
```

## Product context

- Short notes are always-loaded context inlined verbatim into every provider instruction file by `sase memory init`. The
  H3 header is the human- and agent-visible "section title" for each inlined note.
- Leading with the human-readable title reads better; the trailing `(basename)` keeps the generated-from-a-file
  provenance the old format provided, just more concisely.

## Key constraint: the header is a round-trip token, not just display text

The generated header is **parsed back** by two regexes to recover the note's path. Both must be updated in lockstep with
the generator, or `sase memory list` status and AMD management-state counts will silently break:

1. `src/sase/memory/inventory.py` — `_INLINED_SHORT_MEMORY_RE`. Drives `_inlined_short_memory_files()`, which marks
   inlined short notes as **loaded** in `build_memory_inventory()` (what `sase memory list` reports).
2. `src/sase/amd/_agents_doc.py` — `_SHORT_MEMORY_HEADER_RE`. Drives `_short_memory_paths()` →
   `parse_amd_agents_document()`, used by `src/sase/amd/inventory.py` to count short-memory refs and classify a doc as
   "managed".

Both regexes currently capture the full `memory/<file>.md` path straight out of the header. After the change the header
carries only the basename, so each parser must capture the basename and **reconstruct** `memory/<basename>.md` before
resolving/counting.

Safe to reconstruct because short memory notes are always flat files directly under `memory/` (enforced by
`_is_memory_path` in `memory/inventory.py`, which requires `len(relative.parts) == 1`). The basename character class
(`[A-Za-z0-9_.-]+`) round-trips dotted stems (e.g. `foo.bar.md` → `foo.bar` → `memory/foo.bar.md`).

No Rust core involvement: this is presentation-only formatting that lives entirely in Python (verified — no parser for
these headers exists in `sase-core`). It stays on the Python side of the core/backend boundary.

## Design

### 1. Generator — `src/sase/amd/inline_memory.py`

`inline_memory_section(relative_path, body)` builds the header at line 152. Keep the signature (both callers pass a
`memory/<file>.md` relative path); derive the basename internally with `Path(relative_path).stem`.

New header construction:

- Title present (the normal case — short notes are validated to have exactly one H1, so this always holds in practice):
  `### {title} ({basename})`
- Title absent (defensive fallback; cannot occur for a valid inlined note): `### {basename}` — just the basename as the
  header text.

Update the module docstring and the `inline_memory_section` docstring, which both describe the old
`### memory/<file>.md (Title)` shape.

### 2. Parser A — `src/sase/memory/inventory.py`

- Replace `_INLINED_SHORT_MEMORY_RE` so it matches an H3 line ending in `(basename)` and captures the basename, e.g.
  `^###[ \t]+(?:.* )?\(([A-Za-z0-9_.-]+)\)[ \t]*$` (MULTILINE). Greedy title-matching ensures the **last** parenthetical
  (the basename) is captured even if the title itself contains parentheses; the basename character class excludes
  spaces/parens so it cannot bleed into the title.
- In `_inlined_short_memory_files()`, reconstruct the token `f"memory/{match.group(1)}.md"` before calling
  `_resolve_reference(...)`. The existing `resolved.exists` + `_is_short_memory_note` guards still filter out any
  false-positive header match, so resolution behavior is identical to today.
- Update the `### memory/<file>.md` references in the docstring (line ~392) and the explanatory comment (line ~613).

### 3. Parser B — `src/sase/amd/_agents_doc.py`

- Replace `_SHORT_MEMORY_HEADER_RE` to capture the trailing-parenthetical basename, e.g.
  `^### (?:.* )?\((?P<name>[A-Za-z0-9_.-]+)\)$` (input is already whitespace-normalized by `_normalized_line`). The
  legacy `_SHORT_MEMORY_BULLET_RE` (`- @memory/<file>.md`) stays unchanged for backward-compatible parsing of
  pre-inlining docs.
- In `_short_memory_paths()`, when the bullet regex matches use its full `path` group as today; when the header regex
  matches reconstruct `f"memory/{name}.md"`. This keeps `short_memory_paths` populated with full `memory/<file>.md`
  strings so downstream `len(set(...))` counts are unchanged.
- Update the explanatory comment above the regex.

### 4. Tests to update (assert the new shape)

- `tests/main/test_inline_memory.py` — generator output: `### {Title} (x)`, `### {Title} (build_and_run)`, code-fence
  cases, and the no-title fallback (`### x`).
- `tests/test_memory_inventory.py` — `test_inlined_short_note_is_loaded_in_inventory` must use the new header
  (`### Note (note)`) and still assert the note resolves to `loaded` (verifies Parser A round-trips).
- `tests/main/test_init_memory_agent_docs.py`, `tests/main/test_init_memory_managed_agents.py`,
  `tests/main/test_init_memory_handler.py` — update expected headers to `### {Title} ({basename})`.
- `tests/main/test_memory_agent_docs_list.py` — update expected headers and keep the `short_memory_refs == 2` assertion
  (verifies Parser B round-trips and that inlined `####` body headings are still not miscounted).

Add a regression test asserting a title containing parentheses (e.g. `# Foo (bar)` → `### Foo (bar) (build_and_run)`)
parses back to `memory/build_and_run.md`, covering the greedy-match edge case.

### 5. Regenerate provider files

Run `sase memory init` so every generated provider file is rewritten with the new header shape. In this repo that
updates `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md`; it will also refresh provider files in
other context roots the command manages.

### 6. Out of scope / left unchanged

- Historical design docs under `sdd/` (`sdd/epics/202606/…`, `sdd/prompts/202606/…`) that quote the old header are
  records of the original feature and are intentionally **not** rewritten. (Flag for the user if they'd prefer them
  updated.)
- The legacy `- @memory/<file>.md` bullet form remains supported for older docs.

## Verification

1. `just install` (ephemeral workspace may have stale deps).
2. `just check` (ruff + mypy + tests) — all green.
3. `sase memory init`, then confirm a regenerated file (e.g. `CLAUDE.md`) shows
   `### Build & Run Commands (build_and_run)` and no remaining `### memory/*.md (…)` headers.
4. `sase memory list` still reports the inlined short notes as **loaded** (end-to-end round-trip check).
