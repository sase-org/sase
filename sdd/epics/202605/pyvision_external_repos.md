---
create_time: 2026-05-09 18:17:02
status: done
bead_id: sase-2j
tier: epic
prompt: sdd/prompts/202605/pyvision_external_repos.md
---
# Pyvision External Repository References

## Goal

Teach `pyvision` to validate public-symbol pragmas against real references in external git repositories, then remove
SASE's legacy public API whitelist entirely. After the migration, no pragma in this repository should point at the old
whitelist; remaining external-consumer pragmas should use repository URIs such as:

```python
# pyvision: https://github.com/sase-org/sase-telegram.git
```

The source of truth for `pyvision` is the chezmoi repo:

- Source script: `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision`
- Source tests: `/home/bryan/.local/share/chezmoi/tests/bash/pyvision_test.sh`
- Vendored SASE copy: `tools/pyvision-260608` or its next date-stamped replacement
- SASE invocation: `BD_COMMAND=tools/sase_bead .venv/bin/python tools/pyvision-260608 src/sase`

## Current State

`pyvision` already supports file-path pragmas, rejects test-file pragmas, scans tracked Python usage outside the target
tree, and uses AST-backed import and module-alias detection. The current pragma validator treats every pragma target as
a path relative to the current repository root.

The SASE repo currently has seven pragmas that point at the legacy public API whitelist:

- `src/sase/core/agent_scan_facade.py`: `upsert_agent_artifact_index_row`, `delete_agent_artifact_index_row`
- `src/sase/notifications/pending_actions.py`: `PrefixResolution`
- `src/sase/integrations/changespec_tags.py`: `ChangeSpecTagEntry`, `ChangeSpecTagListing`
- `src/sase/integrations/agent_status_groups.py`: `AgentStatusGroup`, `agent_status_bucket_glyph`,
  `status_bucket_header`

The old whitelist file contains many more names than those seven. Removing it should not require proving every name in
that file is currently used; only live pragmas and any pyvision failures after migration matter.

Initial external-reference reconnaissance found direct external imports/usages for some current API roots:

- `sase-telegram` and `retired chat plugin` import `sase.integrations.agent_status_groups.status_bucket_header`.
- `sase-telegram` and `retired chat plugin` import `sase.integrations.changespec_tags.list_changespec_xprompt_tags`.
- Direct textual references to record types such as `ChangeSpecTagEntry`, `ChangeSpecTagListing`, and `AgentStatusGroup`
  may be absent because they are returned indirectly through public helper functions. Do not paper over that with an
  unvalidated repo pragma; either improve pyvision's model for these indirect API surfaces or remove stale/public-only
  names during migration.

## Design Requirements

1. Preserve existing path-pragma behavior for in-repo non-Python/non-test references.
2. Recognize external repository URI pragmas separately from relative file-path pragmas.
3. Validate URI pragmas by scanning the referenced repository, not by trusting the URI string.
4. Normalize equivalent git remotes, at least `https://github.com/org/repo(.git)`,
   `ssh://git@github.com/org/repo(.git)`, and `git@github.com:org/repo(.git)`.
5. Prefer an existing local checkout whose `origin` remote matches the pragma URI. Fall back to a cache/clone only when
   no matching checkout is found.
6. Keep CI behavior deterministic. If clone fallback is implemented, use HTTPS URIs in SASE pragmas and clear errors for
   inaccessible/private repositories. If clone fallback is not implemented in a phase, the same phase must add an
   explicit, documented way to provide local external repo paths.
7. Scan external repositories through `git ls-files` so untracked local noise does not satisfy a pragma.
8. Validate that the external repository actually references the symbol. For Python files, reuse the existing AST-backed
   import/alias machinery where possible. For non-Python tracked files, a word-boundary text search is acceptable.
9. Keep stale-pragma detection: if pyvision can already prove the symbol is used by in-repo Python files, the pragma
   should still fail as unnecessary.
10. Keep private-symbol and test-file pragma restrictions intact.

## Phase 1: Implement External-Repo URI Support in Chezmoi Pyvision

Owner: one agent instance focused only on the chezmoi repo.

Files likely touched:

- `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision`
- `/home/bryan/.local/share/chezmoi/tests/bash/pyvision_test.sh`

Work:

1. Add pragma-target classification:
   - Existing relative paths remain path pragmas.
   - URI targets include `https://...`, `ssh://...`, `file://...`, and scp-style git remotes such as
     `git@github.com:sase-org/sase-telegram.git`.
2. Add git remote normalization and matching helpers.
3. Add external repository resolution:
   - First search nearby/local checkouts, especially siblings of the current repo and any paths supplied through a
     documented CLI flag or environment variable.
   - If clone/cache fallback is chosen, keep it shallow and deterministic, and fail with a concise message when the repo
     cannot be fetched.
4. Add a scanner for tracked files in the external repo:
   - Python files should use the AST collector so import aliases and `module.Symbol` usage are detected.
   - Other tracked text files may use the existing word-boundary symbol search.
   - Skip external test files unless the implementation deliberately documents why test-only external usage should
     preserve a public API. The safer default is non-test source/docs/config only.
5. Integrate URI validation into `_validate_pragmas` without weakening existing relative-path validation.
6. Add bashunit tests with temporary git repos:
   - URI pragma passes when an external repo imports or references the symbol.
   - URI pragma fails when the external repo exists but does not reference the symbol.
   - URI pragma fails clearly when the repo cannot be resolved/fetched.
   - Relative path pragmas still work.
   - Test-file pragmas are still rejected.
7. Run focused chezmoi tests:
   - `cd /home/bryan/.local/share/chezmoi && bashunit ./tests/bash/pyvision_test.sh`
   - `cd /home/bryan/.local/share/chezmoi && just check`

Acceptance:

- `pyvision` can validate a symbol against a real external git repo URI.
- All existing pyvision behavior covered by current tests still passes.
- Chezmoi `just check` passes.

## Phase 2: Harden Public API Surface Modeling

Owner: one agent instance, starting after Phase 1 lands.

Purpose:

The SASE migration includes symbols that may be externally consumed indirectly, for example dataclasses returned by an
externally imported helper. This phase should make pyvision strict enough to avoid fake whitelists while practical
enough to model real Python API surfaces.

Work:

1. Build a small local public-symbol dependency model inside the analyzed target tree:
   - For each public function/class, collect public symbols referenced in return annotations, parameter annotations,
     dataclass fields, class bases, and constructor calls inside the public function body.
   - If an external repo directly proves usage of public symbol `A`, allow `A`'s public API dependencies to count as
     used when they are reachable through these explicit type/value relationships.
2. Keep this conservative:
   - Do not mark arbitrary same-file public references as externally used.
   - Do not follow dynamic string references.
   - Do not allow this propagation to satisfy private-symbol checks.
3. Add bashunit fixtures for:
   - External repo imports `list_items`; `list_items() -> ItemListing`; `ItemListing.entries: list[ItemEntry]`.
     `ItemListing` and `ItemEntry` should not require fake text references if the API graph proves they are part of the
     externally used surface.
   - A public class that is only mentioned by another unused public class should still fail as unused.
4. Run the same focused chezmoi test suite and full `just check`.

Acceptance:

- Direct external references are required at the API root.
- Public return/record types reachable from externally referenced API roots are accepted.
- Stale/unreachable public symbols are still reported.

## Phase 3: Vendor Pyvision Into SASE and Replace Pragmas

Owner: one SASE repo agent instance, starting after Phases 1 and 2 are committed/applied in chezmoi.

Files likely touched:

- `tools/pyvision-260608` or its date-stamped successor
- `Justfile`
- `tools/AGENTS.md`
- Legacy public API whitelist file
- Current pragma-bearing files under `src/sase/`
- `docs/integrations.md`

Work:

1. Re-vendor pyvision from chezmoi:
   ```bash
   pyvendor /home/bryan/.local/share/chezmoi/home/bin/executable_pyvision /home/bryan/projects/github/sase-org/sase_100
   ```
   Let `pyvendor` remove the old dated copy and update references.
2. Replace all legacy whitelist pyvision pragmas:
   - Use canonical external repo URIs for directly or indirectly proven external consumers.
   - Prefer HTTPS GitHub URIs in pragmas unless Phase 1 explicitly proves SSH URIs work in local and CI contexts.
   - Add multiple URI pragmas only when multiple external repos independently preserve the symbol.
3. Run pyvision after each cluster of changes and classify failures:
   - If a symbol is directly externally used, keep a URI pragma.
   - If a symbol is only part of an externally used return/type surface, rely on Phase 2's conservative dependency
     model.
   - If a symbol has no real external or in-repo use, remove the pragma and either make it private or delete it,
     depending on the surrounding code.
4. Delete the legacy public API whitelist file.
5. Update `docs/integrations.md` to remove the whitelist-file reference and describe repo-URI pragmas as the maintenance
   mechanism for externally consumed Python APIs.
6. Update `tools/AGENTS.md` to document:
   - External repo URI pragma syntax.
   - How pyvision resolves external repos.
   - When such pragmas are allowed.
   - That the legacy public API whitelist is obsolete and must not be recreated.
7. Verification in SASE:
   ```bash
   rg "public[_]api[_]methods[.]txt|# pyvision: public[_]api[_]methods[.]txt"
   just install
   just pyvision
   just check
   ```

Acceptance:

- The legacy public API whitelist file is gone.
- No pragma points at the legacy public API whitelist.
- All remaining pyvision pragmas either point at real relative files or external repo URIs.
- `just pyvision` and `just check` pass in SASE.

## Phase 4: External Repo Contract Sweep

Owner: one agent instance focused on consumer repos and final cross-repo validation.

Candidate external repos discovered locally:

- `/home/bryan/projects/github/sase-org/sase-telegram`
- `/home/bryan/projects/github/sase-org/retired chat plugin`
- `/home/bryan/projects/github/sase-org/sase-nvim`
- `/home/bryan/projects/github/sase-org/sase-github`
- `/home/bryan/projects/github/sase-org/retired Mercurial plugin`
- `/home/bryan/projects/github/sase-org/sase-android`

Work:

1. For every URI pragma added in Phase 3, confirm the external repo checkout resolves to the expected remote.
2. Confirm the referenced symbol is present in real source usage or is reachable through the Phase 2 public API surface
   model.
3. If an external repo needs a small source cleanup to make its public API use explicit, do that in the external repo
   and run that repo's `just check` if it has one. Avoid adding artificial references solely to satisfy pyvision.
4. Run final SASE checks:
   ```bash
   rg "public[_]api[_]methods[.]txt|# pyvision: public[_]api[_]methods[.]txt"
   just pyvision
   just check
   ```
5. Check git status in SASE, chezmoi, and any touched external repo.

Acceptance:

- The migration is backed by actual external references, not by a new broad whitelist.
- All touched repos have their required checks run.
- The final report lists changed repos and verification commands.

## Suggested Phase-Agent Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_pyvision_external_repos.md`: add external repository URI pragma support to
> `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision`, add bashunit coverage in the chezmoi repo, and run
> focused pyvision tests plus `just check` in `/home/bryan/.local/share/chezmoi`. Do not modify the SASE repo yet.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_pyvision_external_repos.md`: harden pyvision's model for public API surface
> dependencies so externally referenced API roots can prove their explicit return/record types without fake text
> references. Add regression tests and run the chezmoi pyvision tests plus `just check`.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_pyvision_external_repos.md`: vendor the updated pyvision into this SASE repo,
> replace every legacy whitelist pyvision pragma with real external repo URI pragmas or remove stale symbols,
> delete the legacy public API whitelist file, update docs/tooling instructions, and run `just install`, `just pyvision`, and
> `just check`.

Phase 4 prompt:

> Implement Phase 4 from `sase_plan_pyvision_external_repos.md`: validate every new external repo URI pragma against the
> actual consumer repos, make any necessary consumer cleanup without artificial references, run required checks in
> touched external repos, then run final SASE `rg`, `just pyvision`, and `just check` checks.

## Risks

- External repos may be private or unavailable in CI. Phase 1 must either implement clone/cache behavior that works in
  CI with the chosen URIs or document and wire an explicit local-repo mapping mechanism.
- URI normalization can be surprisingly subtle. Keep supported forms narrow and tested instead of accepting every string
  that looks vaguely URL-like.
- Broad text search can produce false positives on generic names. Prefer AST-backed Python reference detection when
  possible, and be cautious with short/common symbols.
- Public API dependency propagation can become too permissive. Keep it limited to explicit annotations, dataclass
  fields, bases, and constructor/value relationships from externally proven API roots.
