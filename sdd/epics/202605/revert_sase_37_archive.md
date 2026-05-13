---
create_time: 2026-05-12 21:46:46
status: done
prompt: sdd/prompts/202605/revert_sase_37_archive.md
bead_id: sase-3b
tier: epic
---
# Revert `sase-37` Archive and Query Work

## Goal

Remove the `sase-37` dismissed-agent archive/query epic and the follow-on repair hacks that were added to stabilize it,
while preserving unrelated work from the same time window. The target end state is the pre-`sase-37` dismissed-agent
archive behavior: persisted dismissed bundles remain available for revive, but there is no archive query planner, no
archive search/show/stats/revive/purge/scrub/export CLI surface, no v2/FTS archive index lifecycle, no Rust archive
facade, and no query-aware revive modal.

This must not be implemented as a blind chronological revert. The May 12 commit window contains unrelated SASE-38, Qwen,
pyvision, workspace, command-hook, documentation, and TUI status work that must remain intact.

## Initial Evidence

`sase bead show sase-37` reports a closed epic with phases `sase-37.1` through `sase-37.9` and plan file
`sdd/epics/202605/agent_archive_query.md`. The epic notes reference `COMMIT: bb5f3b46`, but that hash is absent in the
current clone, so commit notes cannot be treated as the sole source of truth.

Definite `sase-37` implementation commits found by commit message:

- `7fcb5706d` - `feat: add v2 dismissed bundle archive index (sase-37.2)`
- `bea1750ad` - `feat: add searchable archive bundle projections (sase-37.3)`
- `085e86d92` - `feat: add archive query planner (sase-37.4)`
- `08b9111ae` - `feat: add dismissed agent archive CLI (sase-37.5)`
- `0ef1b84cd` - `feat: add archive-backed revive search (sase-37.6)`
- `ce8cb9e37` - `feat: harden dismissed agent archive storage (sase-37.7)`
- `ac5487d67` - `feat: add archive lifecycle commands (sase-37.8)`
- `b9954bb0a` - `feat: route archive operations through Rust facade (sase-37.9)`
- `4f216979a` - `chore: Add SDD prompt and plan for sase_37_completion (sase-37)`

Probable follow-on repair/hack commits to audit and selectively unwind:

- `3edabc3be` - preserve bundles on revive completion fix for `sase-37`
- `fa970b1d6` - split dismissed bundle index module
- `ab1b897e7` - split revive agent modal modules
- `a1228da5f` - drop O(N) bundle scan introduced by archive revisions
- `4173b39e0` - split dismissed agent tests
- `d8d28113f` - make query-backed revive modal responsive
- `f1d4f3513` - split dismissed agents module
- `4d4fce3b6` - avoid query pagination/navigation key conflict
- Archive portions of `c307d265c` and `bbdc04b29`
- `179cf50b9` only if the audit shows it is compensating for the query-aware revive path rather than preserving an
  independent pre-existing revive correctness fix

Nearby work that should be excluded unless a concrete dependency proves otherwise:

- SASE-38 / starting-agent status commits
- Qwen/opencode runtime, color, hook, and config commits
- pyvision and `fix_just` work
- workspace environment leak fixes
- agent commit enforcement research and hook changes
- generic TUI display-panel/status refactors not required by archive rollback

## Phase 1 - Rollback Manifest and Safety Baseline

Owner: one audit agent. No production code edits.

1. Create a rollback manifest that maps every definite and probable commit above to:
   - files touched
   - symbols and CLI options added
   - tests added or materially changed
   - whether the change is `remove`, `restore previous behavior`, `keep`, or `split manually`
2. Capture pre-`sase-37` reference versions for the core files from `7fcb5706d^`, especially:
   - `src/sase/ace/dismissed_agents.py`
   - `src/sase/ace/dismissed_bundle_index.py`
   - `src/sase/ace/tui/actions/agents/_revive.py`
   - `src/sase/ace/tui/modals/revive_agent_modal.py`
   - `src/sase/ace/tui/models/agent_bundle.py`
   - `src/sase/agents/cli_archive.py`
   - `src/sase/main/parser_agents.py`
   - `src/sase/ace/agent_query/*`
3. Record the exact unrelated commits/files that must be preserved.
4. Run `git status --short --branch` and save the starting tree state in the manifest.
5. Acceptance: the manifest is specific enough that later phase agents can edit by file/symbol rather than by date range
   or blind revert.

## Phase 2 - Restore Dismissed Bundle Storage and Index Semantics

Owner: one implementation agent.

1. Restore the dismissed bundle index to the pre-`sase-37` summary-index behavior:
   - remove v2 schema fields, archive revisions, FTS table maintenance, payload hashes, lifecycle audit helpers, and
     query-specific summary projections
   - collapse `src/sase/ace/dismissed_bundle_index/` back to the legacy module shape if no unrelated post-`sase-37`
     imports require the package facade
2. Remove searchable projection support:
   - delete `src/sase/ace/archive_search_text.py`
   - remove `archive_search_text`, scrubber versioning, bundle schema versioning, and revision fields from bundle save
     and rebuild paths
3. Remove immutable revision directory behavior and return to the legacy bundle path/read/write contract, while keeping
   any independent atomic-write improvement only if the manifest proves it is not coupled to archive revisions.
4. Keep legacy sharded and top-level bundle compatibility.
5. Acceptance: dismissed bundles can still be saved, loaded, verified, and revived using the pre-query archive model.

## Phase 3 - Remove Archive Query Planner and Query-Language Extensions

Owner: one implementation agent.

1. Delete `src/sase/ace/agent_query/archive_planner.py`.
2. Remove archive-only query keys and numeric comparator additions from tokenizer/parser/types/evaluator unless they are
   used by live-agent query behavior outside `sase-37`.
3. Restore `src/sase/ace/agent_query/__init__.py` exports to live-agent query exports only.
4. Remove tests that only cover archive planner behavior, and trim archive-only expectations from shared parser,
   tokenizer, evaluator, and canonicalization tests.
5. Acceptance: existing live agent query tests still pass, and importing `sase.ace.agent_query` no longer exposes
   archive planner APIs.

## Phase 4 - Remove Archive CLI and Rust Archive Facade

Owner: one implementation agent.

1. Restore `sase agents archive` to maintenance commands that existed before `sase-37`:
   - keep `rebuild-index` and `verify` if they existed pre-epic
   - remove `search`, `show`, `stats`, `revive`, `purge`, `scrub`, and `export`
2. Delete Python Rust-facade archive files:
   - `src/sase/core/agent_archive_facade.py`
   - `src/sase/core/agent_archive_wire.py`
3. Remove call sites that route dismissed-agent archive operations through the facade.
4. Preserve unrelated Rust cleanup execution work outside the archive facade.
5. Acceptance: CLI parser/help no longer advertises archive query/lifecycle commands, and no code imports the deleted
   archive facade modules.

## Phase 5 - Restore Revive Modal and TUI Revive Flow

Owner: one implementation agent.

1. Remove the query-aware revive provider and archive-backed search path from:
   - `src/sase/ace/tui/actions/agents/_revive.py`
   - `src/sase/ace/tui/modals/revive_agent_modal.py`
2. Remove helper modules introduced solely for the query-aware modal split if they are no longer useful:
   - `revive_agent_filter_input.py`
   - `revive_agent_formatting.py`
   - `revive_agent_preview.py`
   - `revive_agent_types.py`
3. Preserve baseline revive behavior that predates `sase-37`: dismissed-agent selection, preview, bulk revive, workflow
   child restoration, artifact restoration, alias cleanup, and refreshed selection.
4. Audit `179cf50b9` carefully. Keep the `full_history` fallback only if it fixes revive visibility independent of the
   query-aware archive model; otherwise remove it as part of the post-`sase-37` stabilization work.
5. Acceptance: pressing `R` shows the legacy dismissed-agent modal without archive-query pagination, debouncing, or FTS
   search, and revive still restores agents correctly.

## Phase 6 - Tests, SDD Records, and Bead Metadata Cleanup

Owner: one implementation agent.

1. Remove tests that only validate removed archive/query features:
   - archive planner tests
   - archive CLI search/show/stats/revive/purge/scrub/export tests
   - FTS, projection, payload hash, archive revision, and lifecycle audit tests
2. Restore or rewrite dismissed-agent tests around the legacy storage/index/revive contract.
3. Update SDD files only as needed to document the rollback:
   - do not edit memory files
   - leave unrelated prompts/tales from the same date untouched
   - update or add rollback plan records rather than deleting historical SDD records unless the user explicitly wants
     historical records removed
4. Decide bead treatment before editing `sdd/beads/issues.jsonl`:
   - preferred: create/close new rollback phase beads rather than rewriting historical `sase-37` closure records
   - only reopen/alter `sase-37` if the user explicitly requests bead history mutation
5. Acceptance: test files describe the retained behavior, not removed archive features, and SDD/bead changes are scoped
   to the rollback.

### Phase 6 Rollback Record - 2026-05-13

- Removed the leftover archive query planner module and live-agent query package exports so
  `sase.ace.agent_query` exposes live-agent query APIs only.
- Rewrote dismissed-bundle tests to pin the legacy sharded bundle/index/revive contract without validating deleted
  archive-query metadata fields.
- Kept `sase agents archive` coverage scoped to maintenance commands: `rebuild-index`, `verify`, and unknown-command
  usage.
- Left historical `sase-37` bead records untouched; only the rollback phase bead `sase-3b.6` should be closed for this
  phase.

## Phase 7 - Integration Validation and Final Audit

Owner: one validation agent.

1. Run `just install` in this workspace before validation commands.
2. Run focused tests first:
   - dismissed bundle/index tests
   - revive tests
   - live agent query tests
   - archive maintenance CLI tests
3. Run `just check` before finishing because this repo had file changes.
4. Run `rg` checks proving removed surfaces are gone:
   - `archive_planner`
   - `archive_search_text`
   - `agent_archive_facade`
   - removed CLI subcommands under `sase agents archive`
   - `archive_revision` and `bundle_schema_version` outside historical SDD text, if those fields are fully removed
5. Compare `git diff --name-status` against the Phase 1 manifest and confirm unrelated same-window files were not
   touched.
6. Acceptance: validation passes or failures are clearly tied to retained unrelated work, and the final diff matches the
   rollback manifest.

## Implementation Guidance

- Prefer manual, symbol-level edits guided by the manifest over `git revert` because unrelated commits are interleaved
  and later refactors changed module boundaries.
- Use pre-`sase-37` file versions as references, but merge them with current unrelated code instead of overwriting whole
  files blindly.
- Keep compatibility imports temporarily only when needed to avoid breaking unrelated callers, then remove dead wrappers
  once `rg` and tests prove they are unused.
- Do not modify memory files without explicit user approval.
- Do not run destructive git commands.
