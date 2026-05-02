---
create_time: 2026-04-29 14:47:39
status: done
prompt: sdd/prompts/202604/changespec_current.md
---
# Plan: `sase changespec current` and `/sase_changespecs` guidance

## Goal

Give agents a reliable, documented way to discover the ChangeSpec associated with the current VCS checkout, especially
when the current CL/PR name or URL is easier to infer than the ChangeSpec name. Add a `sase changespec current` command
and update the generated `/sase_changespecs` xprompt skill source so agents use that command first.

## Current Shape

- `sase changespec` is registered in `src/sase/main/parser_commands.py` and dispatched by
  `src/sase/main/changespec_handler.py`.
- ChangeSpec discovery data comes from `sase.ace.changespec.find_all_changespecs()`, with fields like `name`,
  `project_basename`, `cl`, `status`, `parent`, `file_path`, and `line_number`.
- Workspace inference already exists in `src/sase/workflows/utils.py`: `get_project_from_workspace()` and
  `get_cl_name_from_branch()`.
- VCS providers expose `get_branch_name()`, `get_workspace_name()`, and `get_change_url()`. GitHub-like providers can
  use `get_change_url()` to return a PR URL; bare git may return no URL.
- `/sase_changespecs` is generated from `src/sase/xprompts/skills/sase_changespecs.md`; live skill files should not be
  edited directly.

## Design

Add `sase changespec current` as an agent-friendly read-only command.

Resolution order:

1. Infer the current workspace project from the active VCS checkout.
2. Try to get the current change URL from the VCS provider. If present, match it against `CL:`/`PR:` fields exactly,
   limited to the current project when possible.
3. Try to get the current branch/bookmark name. Match it against ChangeSpec names in the current project, accepting:
   exact name, provider-derived branch names, and historical branch-name transforms used by `resolve_revision()`
   (`changespec_name_to_branch*`, project-prefix stripped names, suffix-aware and suffix-stripped forms).
4. If still ambiguous or missing, print a clear diagnostic with the observed project, branch, and change URL, then exit
   non-zero.

Output should default to the same markdown style agents already expect from `sase search -f markdown`, but focused on
one ChangeSpec. Add `-f/--format {markdown,plain,json}` so agents/scripts can choose:

- `markdown`: one concise result with name, project, status, parent, PR/CL, and file location.
- `plain`: stable key/value lines for terminal use.
- `json`: stable fields for automation and tests.

The command should be read-only and avoid mutating `.gp` files or VCS state.

## Implementation Steps

1. Add parser support in `src/sase/main/parser_commands.py`:
   - `sase changespec current`
   - `-f/--format` with `markdown`, `plain`, and `json`
   - optional `-p/--project-file` for tests/manual override if the workspace project cannot be inferred.
2. Add resolver logic in `src/sase/main/changespec_handler.py` or a small helper module if the handler becomes too
   large:
   - infer project file from `--project-file` or current workspace
   - load active and archived ChangeSpecs through `find_all_changespecs()`
   - collect current branch and change URL best-effort without failing early
   - match by URL first, then branch/name candidates
   - detect zero and multiple matches with useful errors
3. Reuse existing markdown rendering where practical, or add a small focused formatter if the existing search renderer
   is too broad/private for one-result output.
4. Add tests:
   - parser accepts `current` and its short `-f` flag
   - URL match chooses the ChangeSpec whose `cl` equals the provider URL
   - branch match works for exact ChangeSpec names
   - branch match works for derived git-style names and project-prefix stripped names
   - no match returns non-zero with actionable diagnostics
   - ambiguous matches return non-zero
5. Update `src/sase/xprompts/skills/sase_changespecs.md`:
   - add a "Current ChangeSpec" section near the top
   - tell agents to run `sase changespec current -f markdown` before manual search when the task concerns the current
     CL/PR
   - document `-f json` for structured automation
6. Regenerate deployed skills with `sase init-skills --force`, then `chezmoi apply`, per repo memory.
7. Verify:
   - targeted pytest for new tests
   - `just install` if needed, then `just check` before finishing because this repo requires it after edits.

## Risks and Tradeoffs

- Exact PR URL matching depends on provider normalization. To stay conservative, start with exact `cl`/`PR` field match
  plus branch-name fallback; avoid fuzzy PR-number parsing unless tests show an existing need.
- Branch-derived matching can be ambiguous across active and archived ChangeSpecs. Prefer the current project, then fail
  loudly on ambiguity instead of guessing.
- Existing `_display_markdown` helpers in `search_handler.py` are private. If importing them would couple unrelated
  handlers too tightly, a small local formatter is cleaner for this command.
