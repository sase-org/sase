---
create_time: 2026-04-27 14:26:50
status: done
bead_id: sase-y
prompt: sdd/prompts/202604/changespec_skill_1.md
---
# Plan: ChangeSpec Agent Skill

## Goal

Create a new SASE skill that helps agents reliably analyze and work with ChangeSpecs. The skill should be as practical
as `/sase_agents_status`: short enough to be used in the moment, but precise about the commands, formats, lifecycle
rules, and safety boundaries that matter when an agent is inspecting or modifying ChangeSpec-backed work.

The work should land in phases because the useful end state is larger than a single markdown template:

- A deployable skill source.
- Agent-friendly command recipes for discovery, exact lookup, artifact inspection, dependency analysis, and safe
  updates.
- Optional small CLI improvements if the existing `sase search -f markdown` surface proves insufficient.
- Generated provider skill files and verification.

## Existing Context

Skill files are generated, not hand-edited. The source of truth is:

- `src/sase/xprompts/skills/*.md`

After changing a skill source, regenerate with:

```bash
sase init-skills --force
chezmoi apply
```

The existing `/sase_agents_status` skill is a good template: it is a single markdown source with front matter, a primary
command, summarization rules, other useful command forms, and implementation notes.

ChangeSpecs are stored under `~/.sase/projects/<project>/`:

- Active specs: `<project>.gp`
- Terminal specs: `<project>-archive.gp`
- Core sections: `NAME`, `DESCRIPTION`, `PARENT`, `CL` / `PR`, `BUG`, `TEST TARGETS`, `STATUS`, `COMMITS`, `TIMESTAMPS`,
  `HOOKS`, `COMMENTS`, `MENTORS`
- Lifecycle: `WIP -> Draft -> Ready -> Mailed -> Submitted`; `Submitted`, `Archived`, and `Reverted` are terminal.

Current useful command surfaces:

- `sase search '<query>' -f markdown` for agent-friendly ChangeSpec search output.
- `sase search '<query>' -f plain` for full plain text with file paths, line numbers, drawers, hooks, comments, and
  mentors.
- `sase ace` for interactive browsing and operations.
- `sase commit` for commits/proposals/PR creation and automatic `COMMITS` / ChangeSpec tracking.
- `sase revert <name>` and `sase restore <name>` for lifecycle-level destructive/recovery operations.
- `sase config mentor-match <changespec_name>` for mentor-profile diagnostics.

The query language already supports exact and structural lookup:

- `&name` / `name:name` for exact ChangeSpec lookup.
- `+project` / `project:project` for project filtering.
- `^parent` / `ancestor:parent` for parent-chain filtering.
- `~name` / `sibling:name` for sibling/reverted-family filtering.
- `%w`, `%d`, `%y`, `%m`, `%s`, `%r` for status filters.
- `!!!`, `@@@`, `$$$`, `*` for errors, running agents, running processes, or any special state.

## Proposed Skill Name

Use `sase_changespecs`.

Suggested front matter:

```yaml
---
name: sase_changespecs
description:
  Analyze and work with SASE ChangeSpecs. Use when inspecting CL/PR status, dependencies, commits, hooks, comments,
  mentors, or `.gp` project files.
skill: true
---
```

This name matches the domain and avoids colliding with existing `sase ace`, `sase search`, or commit workflow names.

## Phase 1: Skill MVP Using Existing Commands

Owner: one implementation agent.

Files:

- `src/sase/xprompts/skills/sase_changespecs.md`
- Add or update focused tests only if the existing init-skills/catalog tests do not already cover new skill discovery.

Deliverables:

1. Add the new skill source with front matter and concise guidance modeled after `sase_agents_status`.
2. Define the primary command as:

   ```bash
   sase search '<query>' -f markdown
   ```

3. Include the exact-name lookup pattern:

   ```bash
   sase search '&<changespec_name>' -f markdown
   ```

4. Include a "when you need raw detail" fallback:

   ```bash
   sase search '&<changespec_name>' -f plain
   ```

5. Document how agents should summarize results:
   - Start with name, project, status, parent, PR/CL, and file location when available.
   - Call out blockers: non-terminal parent, failed hooks, unresolved comments, running agents/processes, rejected or
     new proposals.
   - For multi-result queries, group by project and status, then mention the most relevant ChangeSpecs first.
6. Document safety rules:
   - Do not manually edit `COMMITS` or `TIMESTAMPS`; they are managed by `sase commit` and lifecycle operations.
   - Do not set `PARENT` to VCS refs like `origin/main`, `origin/master`, or `p4head`; it must be another ChangeSpec
     name or omitted.
   - Prefer `sase commit`, `sase revert`, and `sase restore` over direct `.gp` surgery for tracked workflow changes.
   - If directly editing `.gp` files is unavoidable, preserve two blank lines between ChangeSpecs and 2-space
     indentation for multiline fields.

Verification:

```bash
sase init-skills --force --no-commit --no-push --no-apply
just check
```

If this phase reveals that `sase init-skills` writes generated files into the user config/chezmoi tree, inspect the diff
but do not commit or push unless explicitly requested.

## Phase 2: Validate Existing Search Output Against Real Agent Use

Owner: distinct analysis/implementation agent.

Files:

- Prefer no source changes unless concrete gaps are found.
- Potential files if tests are added:
  - `tests/test_search_handler.py` or the nearest existing search/query test file.
  - `docs/query_language.md` only if command behavior needs clarification.

Deliverables:

1. Exercise representative agent workflows against local or fixture ChangeSpecs:
   - Exact lookup by name.
   - Project/status query.
   - Ancestor/dependency query.
   - Error/running-state query.
   - Submitted/archived lookup from archive files.
2. Confirm `sase search -f markdown` exposes enough information for a useful first-pass answer.
3. Confirm `sase search -f plain` exposes enough detail for artifact and drawer inspection.
4. Add regression tests only for behavior the new skill relies on but is not already covered. Good candidates:
   - Markdown output includes status/project/parent/PR and commit drawer paths.
   - Search includes archive files through `find_all_changespecs()`.
   - Exact-name lookup with `&name` avoids accidental substring matches.

Decision gate:

If the existing search output is good enough, Phase 3 should only refine the skill text. If it is not good enough, Phase
3 should add a small machine-readable CLI surface.

Verification:

```bash
just test tests/test_changespec_queries.py tests/test_query_property_filters.py
just check
```

Adjust the targeted test list to match the files touched.

## Phase 3: Optional Agent-Friendly CLI Improvements

Owner: distinct implementation agent. Skip this phase if Phase 2 concludes the existing command surface is sufficient.

Files, if needed:

- `src/sase/main/parser.py` / parser registration module selected by existing conventions.
- `src/sase/main/parser_commands.py` or a new parser module if a namespace is cleaner.
- A new handler module such as `src/sase/main/changespec_handler.py`.
- Focused tests under `tests/`.

Potential command design:

```bash
sase changespec show <name> -j
sase changespec show <name> --raw
sase changespec list -q '<query>' -j
```

Keep this small. The goal is not to replace ACE or `sase search`; it is to give skills a stable JSON/raw-text path when
markdown/plain search output is too presentation-oriented.

Contract:

- `show -j` should return one exact ChangeSpec object or a clear not-found / ambiguous error.
- JSON should include stable keys such as `name`, `project`, `file_path`, `line_number`, `status`, `parent`, `cl`,
  `bug`, `description`, `test_targets`, and compact summaries of commits/hooks/comments/mentors.
- `--raw` should print the exact raw ChangeSpec block from the `.gp` file, using the existing raw-text helper if
  possible.
- Every CLI argument must have a short option where applicable, per repo convention.

Verification:

```bash
just test <new_or_changed_tests>
just check
```

## Phase 4: Skill Refinement Against Final Command Surface

Owner: distinct implementation agent.

Files:

- `src/sase/xprompts/skills/sase_changespecs.md`
- Tests only if Phase 3 added command contracts that should be reflected in examples.

Deliverables:

1. Update the skill so its "Primary command" matches the final surface:
   - Existing-command path: `sase search '<query>' -f markdown`.
   - New-CLI path, if Phase 3 landed: exact lookups use `sase changespec show <name> -j`; broad searches use
     `sase changespec list -q '<query>' -j` or `sase search -f markdown`, depending on the final contract.
2. Add practical recipes:
   - "What is blocking this ChangeSpec?"
   - "What changed in the latest commit/proposal?"
   - "Find children/descendants of this ChangeSpec."
   - "Check whether it is ready to mail/submit."
   - "Inspect failed hooks, review comments, and mentor state."
3. Keep the skill terse. It should be a field guide, not a copy of `docs/change_spec.md`.

Verification:

```bash
sase init-skills --force --no-commit --no-push --no-apply
just check
```

## Phase 5: Regeneration, Provider Deployment Check, and Docs Hygiene

Owner: final distinct integration agent.

Files:

- Generated provider skill files, if the workflow writes them and the user wants them committed/deployed.
- `README.md` or docs only if the skill list/catalog is manually documented somewhere; do not add docs churn otherwise.

Deliverables:

1. Regenerate skills:

   ```bash
   sase init-skills --force
   ```

2. Apply generated files if the local workflow requires it:

   ```bash
   chezmoi apply
   ```

3. Confirm the generated skill exists for all normal providers that receive `skill: true`.
4. Run the repo verification required by memory:

   ```bash
   just install
   just check
   ```

5. If generated chezmoi files changed, inspect that diff separately from the SASE repo diff. Do not commit unless the
   user explicitly asks.

## Suggested Final Skill Shape

The final skill should be organized like this:

1. Primary command.
2. Exact lookup.
3. Query shortcuts.
4. How to summarize.
5. Common workflows.
6. Safe modification rules.
7. Implementation notes.

It should not include the full ChangeSpec format reference. It should point agents to the commands and invariants they
need during real work.

## Risks

- Overbuilding CLI support when `sase search -f markdown/plain` already works. Phase 2 is intended to prevent that.
- Teaching agents to edit `.gp` files directly. The skill should explicitly bias toward CLI workflows and treat direct
  edits as exceptional.
- Generated skill files can live outside this repo through chezmoi. Keep source and generated diffs separate and avoid
  accidental commits/pushes.

## Out of Scope

- Replacing `sase ace`.
- Redesigning the ChangeSpec format.
- Changing status transition semantics.
- Changing `sase commit` tracking behavior.
- Adding runtime-specific skill behavior. All providers should be treated uniformly.
