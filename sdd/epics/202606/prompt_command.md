---
create_time: 2026-06-13 14:24:39
status: wip
prompt: sdd/prompts/202606/prompt_command.md
bead_id: sase-4o
tier: epic
---
# `sase prompt` Command Plan

## Context

SASE already records submitted agent prompts in `~/.sase/prompt_history.json`, but the shell does not have a first-class
way to inspect, search, reuse, curate, or clean up that history. The only documented-ish CLI path today is the hidden
`sase run "."` picker, and that immediately enters a launch/editor flow.

This plan designs `sase prompt` as the command group for previously submitted agent prompts. It should feel like a
well-made shell history tool: fast to scan, exact when printing text, safe around destructive actions, scriptable
through stable JSON, and pleasant in an interactive terminal.

Inputs reviewed:

- `sdd/research/202606/sase_prompt_command_consolidated.md`
- `sdd/epics/202606/prompt_history_tui.md`
- `memory/long/cli_rules.md` via `sase memory read`
- Current parser/dispatch/history code under `src/sase/main/` and `src/sase/history/`

Important constraints:

- Keep `sase run "."` and `sase run "#vcs:ref ."` compatible.
- Follow CLI rules: excellent help, sorted subcommands/options, short aliases for public long options, and colored
  output where it improves readability.
- Treat prompt history as recency-only. Do not add branch/workspace/project ranking as public CLI behavior.
- Preserve prompt-history locking and atomic writes for mutations.
- Do not join transcript history by default. The prompt store is already large enough that default commands must stay
  bounded.
- Do not migrate to SQLite or Rust core until the command contract is stable or another frontend needs the same richer
  backend API. Keep the first implementation compatible with the existing JSON store.

## Product Shape

Final command inventory, sorted alphabetically:

```bash
sase prompt copy <id>
sase prompt delete <id> [-y|--yes]
sase prompt doctor [-j|--json]
sase prompt edit <id> [-d|--daemon] [-P|--prefix VCS_PREFIX]
sase prompt export <id> [-F|--force] [-m|--metadata] [-o|--out PATH] [-s|--sdd]
sase prompt list [-a|--all] [-c|--cancelled] [-j|--json] [-l|--limit LIMIT] [-q|--query QUERY]
sase prompt prune [-b|--before DATE] [-c|--cancelled] [-d|--dry-run] [-k|--keep LIMIT] [-y|--yes]
sase prompt run <id> [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX]
sase prompt save <id> [-D|--description TEXT] [-F|--force] [-g|--global] [-n|--name NAME] [-p|--project PROJECT] [-t|--tag TAG]
sase prompt select [-a|--all] [-c|--cancelled] [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX] [-q|--query QUERY]
sase prompt show <id> [-f|--format raw|markdown|json]
sase prompt stats [-j|--json]
```

Selector design:

- Compute a stable content ID from exact prompt text: `ph_<sha256(text)[:12]>`.
- Accept any unambiguous `ph_` prefix, a bare hash prefix printed by `list`, or `sha256:<full_hash>`.
- Never use recency indexes as primary selectors. Recency changes too often for indexes to be reliable.
- If a short prefix collides, print the matching IDs and ask for a longer selector.

Default pretty output:

- `list` uses a Rich table with restrained color: green/normal for launched prompts, magenta/dim for cancelled prompts,
  cyan for prompt IDs, yellow/green for directive/xprompt chips, and dim metadata.
- `list` never prints full prompt text. It shows ID, last-used time, status, character count, tags/project hints, and a
  one-line preview.
- `show`, `export`, and `copy` are the intentional full-text escape hatches.

Stable JSON fields for `list -j`:

```json
{
  "id": "ph_8f3a9c0d12ab",
  "timestamp": "260613_092331",
  "last_used": "260613_092331",
  "cancelled": false,
  "text_preview": "Can you help me...",
  "text_chars": 269,
  "text_sha256": "8f3a9c0d12ab..."
}
```

Optional legacy fields such as `workspace` and `branch_or_workspace` may appear in JSON when present, but they are not
core filters.

## Implementation Architecture

Add a small prompt-history catalog layer instead of stretching `get_prompts_for_fzf()`.

Recommended module boundaries:

- `src/sase/history/prompt.py`
  - Keep storage ownership here because the lock, atomic writer, legacy reader, and existing tests already live here.
  - Add `PromptHistoryRecord`, ID/hash helpers, list/filter/resolve/stats/doctor/delete/prune primitives.
  - Keep `get_prompts_for_fzf()` as a compatibility wrapper over the catalog.
- `src/sase/main/parser_prompt.py`
  - Register the new top-level `prompt` parser and subcommands.
  - Keep subcommands and option definitions alphabetized.
- `src/sase/main/prompt_handler.py`
  - Dispatch subcommands, mirroring the style of `chats_handler.py`.
- `src/sase/prompt/`
  - Put command presentation and workflow helpers here: `cli_list.py`, `cli_show.py`, `cli_run.py`,
    `cli_maintenance.py`, `cli_export.py`, and shared `render.py` if useful.
- `src/sase/main/query_handler/`
  - Factor the private `_dispatch_query()` behavior into a reusable function, or expose a thin local adapter, so
    `sase prompt run/edit/select` reuses the same foreground/daemon/multi-prompt routing as `sase run`.

Reliability rules:

- Mutations must acquire the prompt-history sidecar `flock`, load under the lock, write through a temp file, `fsync`,
  and `os.replace`.
- Read-only commands may tolerate corrupt JSON and report it clearly; write commands must not overwrite a corrupt or
  transiently unreadable store.
- `raw` output uses `sys.stdout.write(record.text)` without adding or stripping newlines.
- Destructive commands must confirm on a TTY unless `--yes` is supplied. In non-TTY contexts, require `--yes` or
  `--dry-run`.
- Error messages should identify prompt IDs, counts, and paths, but should not echo full prompt text unless the command
  is explicitly `show`, `export`, or `copy`.

## Phase 1: Catalog And Read-Only CLI

Owner: first implementation agent.

Goal: make prompt history observable and scriptable without launching anything.

Scope:

- Add `sase prompt` as a top-level command group with `list`, `show`, and `stats`.
- Add a catalog API in `sase.history.prompt`:
  - stable ID/hash generation,
  - recency-ordered listing,
  - launched/all/cancelled filtering,
  - case-insensitive substring query filtering over exact prompt text,
  - selector resolution with collision diagnostics,
  - stats computation.
- Implement `list`:
  - default to 20 non-cancelled prompts, sorted by `last_used` descending,
  - support `--all`, `--cancelled`, `--json`, `--limit`, and `--query`,
  - render a polished Rich table by default and stable JSON with `-j`.
- Implement `show`:
  - `raw` prints exact prompt text,
  - `markdown` prints a compact metadata header plus the full prompt body,
  - `json` prints metadata plus full text.
- Implement `stats`:
  - total entries, file size, launched/cancelled counts,
  - oldest/newest `last_used`,
  - prompt length percentiles,
  - largest prompts by ID and size with preview only,
  - top xprompt/workflow/directive chips parsed from prompt text.
- Keep `get_prompts_for_fzf()` behavior compatible by making it consume the catalog.

Acceptance:

- `sase prompt list` shows at most 20 recent non-cancelled prompts and never prints full long prompts.
- `sase prompt list -j` emits a stable JSON array.
- `sase prompt show <id> -f raw` prints exact text suitable for command substitution or piping.
- Selectors remain stable after adding newer prompts.
- Corrupt or missing history produces clear read-only output and does not crash.
- `sase run "."` continues to work.

Tests:

- New focused tests for ID generation, selector resolution, filtering, JSON shape, raw output exactness, stats, and
  corrupt JSON.
- Parser/help tests that assert every new public long option has a short alias.
- Suggested verification:

```bash
pytest tests/history tests/test_prompt_command.py tests/test_special_cases.py
```

## Phase 2: Replay, Selection, And Clipboard

Owner: second implementation agent.

Goal: let users reuse prior prompts without hiding the flow behind `sase run "."`.

Scope:

- Add `run`, `edit`, `select`, and `copy`.
- Factor or wrap existing run dispatch so prompt replay follows current `sase run` behavior for foreground, daemon,
  multi-prompt, multi-model, xprompt, workflow, and direct prompt routing.
- `run <id>` launches the exact prompt.
- `run <id> --edit` opens the selected prompt in the editor before launch.
- `edit <id>` is a memorable wrapper for edit-before-launch.
- `select` opens an fzf picker over the same catalog:
  - default is launched prompts only,
  - `--all`, `--cancelled`, and `--query` filter candidates before fzf,
  - no fzf installed: print a helpful message pointing to `sase prompt list` and `sase prompt run`.
- `--prefix` reuses existing VCS tag replacement behavior so a prompt from `#gh:sase` can be replayed under
  `#gh:bob-cli`, including multi-prompt segments.
- `copy <id>` copies exact prompt text with `sase.core.clipboard.copy_to_system_clipboard`.

Compatibility:

- Keep `sase run "."` as the old edit-before-launch picker path.
- Keep `sase run "#vcs:ref ."` behavior, but implement shared replacement logic so `sase prompt run/select -P` and the
  compatibility path cannot drift.

Acceptance:

- `sase prompt run <id>` dispatches through the same code path as an equivalent `sase run "<prompt>"`.
- `sase prompt edit <id>` uses the editor, aborts cleanly on empty content, and launches edited content otherwise.
- `sase prompt select -q auth -e -d` filters candidates, edits the selected prompt, and launches daemon mode.
- `sase prompt copy <id>` returns nonzero when no clipboard command is available and suggests
  `sase prompt show <id> -f raw`.
- Existing special-case tests for `sase run "."` and VCS-dot reuse still pass.

Tests:

- Mock launch dispatch rather than spawning agents.
- Mock editor and clipboard commands.
- Cover prefix replacement, fzf missing, fzf cancelled, selected prompt not found, and daemon routing.
- Suggested verification:

```bash
pytest tests/test_prompt_command.py tests/test_special_cases.py tests/history
```

## Phase 3: Safe Maintenance

Owner: third implementation agent.

Goal: make the live prompt-history file maintainable and safe to clean up.

Scope:

- Add `doctor`, `delete`, and `prune`.
- `doctor` is read-only and reports:
  - history file path, existence, size, and parseability,
  - entry count and cancelled count,
  - invalid/skipped raw entries,
  - duplicate computed IDs or ambiguous short selectors,
  - legacy context fields,
  - oversized prompts,
  - shortest prompts saved through explicit recovery paths,
  - fzf and clipboard availability.
- `delete <id>` removes exactly one prompt by resolved selector.
- `prune` supports objective cleanup:
  - `--keep LIMIT` keeps newest N entries,
  - `--before DATE` removes entries older than a parsed date,
  - `--cancelled` limits removal to cancelled prompts,
  - combined predicates print exactly why each count is removable.
- `prune --dry-run` never mutates.
- Without `--yes`, destructive commands confirm on a TTY. In non-TTY mode, fail with instructions unless `--yes` or
  `--dry-run` is supplied.

Date parsing:

- Support at least `YYYY-MM-DD`, `YYmmdd`, and SASE timestamp `YYmmdd_HHMMSS`.
- Reject ambiguous dates with examples in the error message.

Non-goals:

- Do not add broad substring delete.
- Do not auto-prune on normal prompt writes in this phase.

Acceptance:

- Mutations preserve locking and atomic replace behavior.
- Delete and prune never rewrite the store if selector/date parsing fails.
- A corrupt history file cannot be replaced by an empty file through maintenance commands.
- `doctor -j` is stable enough for editor integrations.

Tests:

- Mutation tests should verify sidecar lock use, atomic replace, confirmation behavior, and corrupt-store safety.
- Suggested verification:

```bash
pytest tests/history tests/test_prompt_command.py
```

## Phase 4: Export And XPrompt Curation

Owner: fourth implementation agent.

Goal: bridge useful one-off prompts into durable artifacts without inventing a second prompt-library format.

Scope:

- Add `export`:
  - stdout by default,
  - `--out PATH` writes to a chosen path,
  - `--metadata` wraps output in frontmatter with prompt ID, hash, timestamp, last_used, cancelled status, and source,
  - `--sdd` writes under `sdd/prompts/YYYYMM/` by default and implies metadata,
  - default SDD filenames use a clean prompt-preview slug plus the short prompt ID,
  - existing destination paths fail unless `--force` is supplied.
- Add `save`:
  - writes ordinary markdown xprompt files understood by the existing loader,
  - default destination is local `.xprompts/NAME.md`,
  - `--global` writes to `~/.xprompts/NAME.md`,
  - `--project PROJECT` writes to `~/.config/sase/xprompts/PROJECT/NAME.md`,
  - `--tag` may be repeated and is persisted as xprompt frontmatter,
  - `--description` overrides the generated description,
  - if `--name` is omitted, derive a deterministic slug from the cleaned preview and append the prompt ID if needed,
  - existing explicit names fail unless `--force` is supplied.
- Use existing xprompt loader conventions and validation where possible. Do not create a separate prompt-library store.

Acceptance:

- `sase prompt export <id> -s` creates a usable SDD prompt snapshot with source metadata.
- `sase prompt save <id> -n fix-auth-review -t review` creates an xprompt file that `sase run "#fix-auth-review"` can
  resolve through existing loader paths.
- Save/export never silently overwrite user files.
- Generated markdown is readable and formatted consistently.

Tests:

- Path selection, slug generation, frontmatter, overwrite guards, repeated tags, and loader visibility for saved
  xprompts.
- Suggested verification:

```bash
pytest tests/test_prompt_command.py tests/test_xprompt_loader_parsing.py tests/workflows/test_plan_paths.py
```

## Phase 5: Polish, Documentation, And Final Integration

Owner: fifth implementation agent.

Goal: make the full command feel native, discoverable, and robust enough to leave behind.

Scope:

- Add `prompt` to compact root help if the final command feels common enough after Phase 1-4 implementation.
- Audit `sase prompt --help`, every subcommand help page, and examples for:
  - sorted subcommands/options,
  - every public long option having a short alias,
  - no stale branch/workspace ranking language,
  - no undocumented destructive behavior.
- Add or update user-facing docs with focused examples:
  - find a recent prompt,
  - print raw prompt text,
  - rerun with edit,
  - replay under another VCS prefix,
  - recover cancelled prompts,
  - delete a secret,
  - prune cancelled/old prompts,
  - save as xprompt,
  - export to SDD.
- Add an integration-style test fixture with thousands of prompts and a few very large prompts to ensure `list`,
  `stats`, `doctor`, and JSON output stay bounded and do not accidentally print full text.
- Run the repository-required verification.

Acceptance:

- `sase prompt --help` is good enough to learn the command without reading docs.
- Pretty output is scannable in a real terminal and degrades cleanly under `NO_COLOR` or non-TTY output.
- No public command leaks full prompt text unless the command's purpose is explicit full-text output.
- Final `just check` passes after `just install`.

Suggested verification:

```bash
just install
just check
```

## Deferred Work

Defer these until usage data or another frontend requires them:

- SQLite storage migration.
- Rust-core prompt-history API.
- Transcript/provenance joins.
- Regex/fuzzy query languages beyond simple substring filtering.
- Bulk substring deletion.
- Automatic SDD tale/epic/plan creation from prompt text.
- Branch/workspace/project filters as core behavior.

## Handoff Notes

Each phase should start by rereading the CLI long-memory with:

```bash
sase memory read long/cli_rules.md --reason "Need CLI command conventions before changing sase prompt"
```

If a phase touches TUI prompt-history rendering or Textual event handlers, that agent must also read
`memory/long/tui_perf.md` through `sase memory read` before making changes.

After any implementation-file changes, run `just install` before repository checks in this ephemeral workspace.
