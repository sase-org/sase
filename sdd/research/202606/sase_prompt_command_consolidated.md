---
create_time: 2026-06-13
updated_time: 2026-06-13
status: research
---

# `sase prompt` Command Consolidated Research

## Research Request

What functionality should a new `sase prompt` command provide to manage previously used SASE agent prompts from the
command line? The recommendation should be ambitious but practical, and every feature should map to a real objective
use-case.

## Consolidation Notes

This note consolidates two independent research outputs:

- `sdd/research/202606/sase_prompt_command_research.md`
- `sdd/research/202606/sase_prompt_command.md`

I read both agent transcripts, both generated research files, the required CLI long-term memory, the TUI performance
guidance, and the relevant prompt-history, parser, picker, TUI modal, chats, file-history, and xprompt loader code.

Conflicts resolved here:

- Do not make branch/workspace/context filtering a core v1 feature. The active `sdd/epics/202606/prompt_history_tui.md`
  epic is explicitly moving prompt history to recency-only behavior and legacy-compatible storage.
- Keep both bridge ideas, but separate them: `save` creates a reusable xprompt; `export` preserves prompt text as an
  external artifact, including SDD prompt snapshots when requested.
- Include pruning, but not as an unguarded v1 delete-many command. Start with `doctor` and single-entry `delete`, then
  add `prune` with dry-run/confirmation defaults.

## Bottom Line

Yes. Add a top-level `sase prompt` command group focused on **previously submitted agent prompts**. SASE already records
prompt history, but the shell has no proper way to inspect, search, reuse, clean up, or curate it. The only current CLI
entry is the hidden `sase run "."` fzf/editor path, which immediately turns selection into a launch flow.

Recommended command shape:

```bash
sase prompt copy <id>
sase prompt delete <id> [-y|--yes]
sase prompt doctor [-j|--json]
sase prompt edit <id> [-d|--daemon] [-P|--prefix VCS_PREFIX]
sase prompt export <id> [-m|--metadata] [-o|--out PATH] [-s|--sdd]
sase prompt list [-a|--all] [-c|--cancelled] [-j|--json] [-l|--limit LIMIT] [-q|--query QUERY]
sase prompt prune [-b|--before DATE] [-c|--cancelled] [-d|--dry-run] [-k|--keep LIMIT] [-y|--yes]
sase prompt run <id> [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX]
sase prompt save <id> [-g|--global] [-n|--name NAME] [-p|--project PROJECT] [-t|--tag TAG]
sase prompt select [-a|--all] [-c|--cancelled] [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX] [-q|--query QUERY]
sase prompt show <id> [-f|--format raw|markdown|json]
sase prompt stats [-j|--json]
```

Keep `sase run "."` and `sase run "#gh:sase ."` working as compatibility shortcuts, but make `sase prompt select` and
`sase prompt run` the documented prompt-history interface.

## Verified Current State

### No `sase prompt` command exists

Top-level parsers are registered in `src/sase/main/parser.py`; dispatch lives in `src/sase/main/entry.py`. There is no
`prompt` top-level parser or `args.command == "prompt"` handler today. The word `prompt` in `parser_commands.py` is the
positional argument for `sase run`, whose help still says `.` opens prompt history.

### Prompt history is already captured

`src/sase/history/prompt.py` persists prompt history to `~/.sase/prompt_history.json`.

Current persisted fields:

- `text`
- `branch_or_workspace`
- `timestamp`
- `last_used`
- `workspace`
- `cancelled`

Important behavior:

- Deduplication is by exact prompt text.
- Existing entries keep their original `timestamp` and get `last_used` updated.
- A later cancelled write does not downgrade a launched prompt to cancelled.
- Normal writes skip prompts shorter than two words unless `allow_short=True`.
- Multi-prompt submissions currently save segment entries as well as the full prompt.
- Mutations take a sidecar `flock`, read the whole JSON file, rewrite it through a temp file, `fsync`, then
  `os.replace`.

### The live store is large enough to justify command support

Verified on 2026-06-13 without printing raw prompt text:

| Metric | Value |
| --- | ---: |
| File size | 33,311,910 bytes |
| Entries | 9,066 |
| Cancelled entries | 724 |
| Unique prompt texts | 9,066 |
| Median prompt length | 211 chars |
| 90th percentile prompt length | 14,192 chars |
| 95th percentile prompt length | 19,825 chars |
| 99th percentile prompt length | 36,715 chars |
| Max prompt length | 348,980 chars |

The transcript store is also large: about 41,979 markdown transcripts and 278M allocated under `~/.sase/chats`. Prompt
commands should therefore avoid transcript/provenance joins by default. Any future provenance lookup should be explicit
and bounded.

### Existing access is interactive and launch-oriented

Current CLI paths:

- `sase run "."` opens fzf history selection, opens the selected prompt in `$EDITOR`, then launches.
- `sase run "#gh:sase ."` opens the same picker and rewrites embedded VCS workflow tags to the requested prefix before
  launch.
- If fzf is missing, there is no fallback list/show surface.

Current TUI modal behavior:

- Enter submits a selected prompt.
- `Ctrl+G` edits before submit.
- `Ctrl+I` loads into the prompt input.
- `Ctrl+X` toggles cancelled prompts.
- `Ctrl+Y` copies prompt text.

The CLI should expose the same useful operations directly, but in scriptable form.

### The active prompt-history epic changes the target model

`sdd/epics/202606/prompt_history_tui.md` is already moving prompt history toward:

- recency-only ordering,
- no branch/workspace/project ranking,
- removal of typed `.` / `.x` prompt-input history commands in the TUI,
- backward-compatible reads for legacy entries with or without context fields,
- preferred new persisted fields of `text`, `timestamp`, `last_used`, and `cancelled`.

Build `sase prompt` against that target. Do not cement current `*`/`~` branch/workspace ranking into a new public CLI.

## Product Goals

`sase prompt` should make prompt history:

- **Observable:** answer "what did I ask agents to do recently?"
- **Searchable:** find a previous prompt without fzf or editor scraping.
- **Replayable:** rerun exact or edited prompts from stable selectors.
- **Recoverable:** inspect cancelled or failed-launch prompts.
- **Maintainable:** delete accidental secrets and bound unbounded growth.
- **Curatable:** promote repeated ad-hoc prompts into durable reusable artifacts.
- **Scriptable:** provide stable JSON and full-text stdout for editor integrations and shell pipelines.

It should not become a second xprompt manager, a transcript browser, or a new TUI.

## Use-Case To Feature Map

| Use-case | Feature |
| --- | --- |
| "Show me prompts I used lately." | `list` with bounded previews, recency order, default limit. |
| "Find the refactor prompt I used last week." | `list -q QUERY`, optional future `search` alias. |
| "Print the exact prompt so I can pipe it." | `show <id> -f raw`. |
| "Rerun the same prompt after a revert." | `run <id>`. |
| "Reuse it but change one target file." | `run <id> -e` or `edit <id>`. |
| "Run old `#gh:sase` work against `#gh:bob-cli`." | `run <id> -P '#gh:bob-cli'`. |
| "Recover the long prompt I cancelled." | `list -c`, `show <id>`, `run <id> -e`. |
| "I pasted a token by mistake." | `delete <id>` with confirmation. |
| "This file is 33 MB and rewritten on launch." | `doctor`, then guarded `prune`. |
| "I keep reusing this prompt." | `save <id> -n NAME` to file-backed xprompt. |
| "Attach this prompt to research or a plan." | `export <id> -s` to `sdd/prompts/YYYYMM/` with source metadata. |
| "Let an editor integration list candidates." | `list -j`, `show -f json`. |

## Command Design

### Selectors

Use computed content IDs:

```text
ph_<sha256(prompt_text)[:12]>
```

Why:

- The store already deduplicates by exact text.
- IDs remain stable when new prompts are added.
- No migration is required.
- Collision handling can ask for a longer prefix or accept `sha256:<full-hash>`.

For convenience, the CLI may also accept an unambiguous short hash prefix printed by `list`. Avoid positional indexes as
the primary selector because recency changes make them unstable.

### `list`

Purpose: bounded recency inventory.

```bash
sase prompt list [-a|--all] [-c|--cancelled] [-j|--json] [-l|--limit LIMIT] [-q|--query QUERY]
```

Default behavior:

- show launched prompts only,
- sort by `last_used` descending,
- limit to 20,
- print ID, last-used time, status, char count, and a single-line preview.

`--all` includes launched and cancelled prompts. `--cancelled` shows only cancelled prompts. Do not print full prompt
text in list output; very long prompts are common.

Suggested JSON fields:

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

Legacy `workspace` and `branch_or_workspace` can appear when available, but should be optional fields and not core
filters.

### `show`

Purpose: inspect one exact prompt.

```bash
sase prompt show <id> [-f|--format raw|markdown|json]
```

Formats:

- `raw`: exact text only, suitable for `sase run "$(sase prompt show <id>)"`.
- `markdown`: metadata header plus prompt body.
- `json`: metadata and full text.

`show` should not truncate. Truncation belongs only in `list` previews.

### `run`, `edit`, and `select`

Purpose: replay history without hiding it behind the `.` token.

```bash
sase prompt run <id> [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX]
sase prompt edit <id> [-d|--daemon] [-P|--prefix VCS_PREFIX]
sase prompt select [-a|--all] [-c|--cancelled] [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX] [-q|--query QUERY]
```

Rules:

- `run <id>` launches exact text.
- `run <id> -e` opens the editor before launch.
- `edit <id>` is a memorable wrapper for edit-before-launch.
- `select` is the documented fzf-style picker path; if fzf is missing, it should point users to `list` and `run`.
- `-P|--prefix` should reuse the existing VCS tag replacement behavior from `sase run "#vcs:ref ."`.
- Launch routing should reuse `sase run` behavior for foreground, daemon, multi-prompt, and workflow cases.

### `copy` and `export`

Purpose: move prompt text outside SASE without launching it.

```bash
sase prompt copy <id>
sase prompt export <id> [-m|--metadata] [-o|--out PATH] [-s|--sdd]
```

`copy` gives CLI parity with the TUI modal's `Ctrl+Y`.

`export` writes exact prompt text to stdout by default or to `--out`. With `--metadata`, include source metadata. With
`--sdd`, default the destination under `sdd/prompts/YYYYMM/` and include frontmatter such as:

```yaml
---
source: prompt_history
source_prompt_id: ph_8f3a9c0d12ab
source_last_used: 260613_092331
---
```

Do not infer tales, epics, or plans from the prompt in v1.

### `save`

Purpose: turn a repeated ad-hoc prompt into a reusable xprompt.

```bash
sase prompt save <id> [-g|--global] [-n|--name NAME] [-p|--project PROJECT] [-t|--tag TAG]
```

This should write a real `.md` xprompt file into an existing xprompt search location:

- local `.xprompts/NAME.md` by default when appropriate,
- `~/.xprompts/NAME.md` with `--global`,
- `~/.config/sase/xprompts/{project}/NAME.md` with `--project`.

The xprompt loader already understands markdown files, YAML frontmatter, tags, snippets, descriptions, and
project-specific namespacing. Use that system rather than inventing a new prompt-library format.

### `delete`, `doctor`, and `prune`

Purpose: maintenance and secret scrubbing.

```bash
sase prompt delete <id> [-y|--yes]
sase prompt doctor [-j|--json]
sase prompt prune [-b|--before DATE] [-c|--cancelled] [-d|--dry-run] [-k|--keep LIMIT] [-y|--yes]
```

`delete` removes one entry by ID. It should confirm on TTY unless `--yes` is supplied, and it must use the same sidecar
lock and atomic replace behavior as existing prompt-history writes.

`doctor` is read-only in v1. It should report:

- file exists / parseable JSON,
- entry count and file size,
- cancelled count,
- duplicate computed IDs,
- entries missing fields required by current readers,
- legacy entries with context fields,
- oversized prompts,
- shortest prompts saved through explicit recovery paths,
- fzf availability for compatibility paths.

`prune` should ship after `doctor`, default to dry-run or confirmation, and support exact objective cleanup:

- keep newest N entries,
- remove entries before a date,
- remove only cancelled entries,
- combine predicates only when the output clearly states what will be removed.

Do not add broad substring delete in v1; users can search, inspect IDs, then delete explicitly.

### `stats`

Purpose: make usage and cleanup decisions visible.

```bash
sase prompt stats [-j|--json]
```

Useful stats:

- total entries,
- file size,
- launched vs cancelled count,
- oldest/newest `last_used`,
- length percentiles,
- top referenced xprompts/workflow tags parsed from prompt text,
- largest prompts by ID and size, with previews only.

This is practical prior-art from shell-history tools: stats identifies what to prune and which repeated prompts deserve
`save`.

## Implementation Shape

### Add a prompt-history catalog layer

Do not keep extending `get_prompts_for_fzf()`. It is a display-oriented picker API. Add a presentation-neutral layer,
likely in `sase.history.prompt`, with records like:

```python
PromptHistoryRecord(
    id: str,
    text: str,
    timestamp: str,
    last_used: str,
    cancelled: bool,
    text_sha256: str,
    workspace: str | None = None,
    context: str | None = None,
)
```

Needed operations:

- `list_prompt_history(...)`
- `resolve_prompt_history_ref(ref)`
- `delete_prompt_history_ref(ref)`
- `write_prompt_history(...)`

Then make the fzf picker a compatibility consumer of the catalog instead of the other way around.

### Preserve compatibility and locking

Any mutation must:

- preserve the sidecar `flock`,
- write through temp file + `fsync` + `os.replace`,
- keep old entries readable,
- not drop entries just because legacy fields are missing,
- avoid synchronous disk I/O in Textual event handlers.

### Consider Rust core after the CLI contract stabilizes

Prompt history is shared backend behavior by the project boundary rule: CLI, TUI, editor integrations, and future
frontends need matching semantics. The practical sequence is:

1. Ship the Python CLI/catalog against the existing JSON store.
2. Add tests around selector, filtering, JSON, and mutation semantics.
3. Add a cap/prune to stop unbounded growth.
4. Move storage/search/stats into `sase-core` only when another frontend needs it or when measured JSON read/write costs
   justify a SQLite migration.

Do not block the first useful CLI on SQLite. The current 33 MB JSON file is a real maintenance issue, but still
manageable enough for a phased migration.

## Phasing

### Phase 1: Read, replay, and script

Ship:

- `copy`
- `edit`
- `list`
- `run`
- `select`
- `show`
- `stats`

Acceptance:

- `list` defaults to 20 recency-ordered non-cancelled prompts.
- `list -j` emits stable JSON.
- `show <id> -f raw` prints exact prompt text.
- `run <id>` and `edit <id>` reuse `sase run` launch routing.
- `select` becomes the documented fzf entry point.
- `sase run "."` remains compatible.

### Phase 2: Safe maintenance

Ship:

- `delete`
- `doctor`
- guarded `prune`

Acceptance:

- destructive operations confirm or require `--yes`;
- `prune` supports dry-run;
- mutations preserve locking and atomic writes;
- `doctor` is read-only and reports file health, size, counts, duplicate IDs, corrupt JSON, and oversized prompts.

### Phase 3: Curation bridges

Ship:

- `export --sdd` for SDD prompt snapshots,
- `save --name` for reusable xprompts.

Acceptance:

- SDD exports land under `sdd/prompts/YYYYMM/` by default and include source metadata.
- xprompt saves write ordinary `.md` files into existing loader search paths.
- no plan/tale/epic is auto-created.

### Phase 4: Storage hardening

If Phase 1-3 usage confirms value, add:

- soft cap in `add_or_update_prompt`,
- optional sharding or archive format,
- Rust-core/SQLite storage and migration if profiling shows JSON read/write costs are material.

## CLI Rules

Follow the project CLI rules:

- keep subcommands and options sorted in help;
- give every public long option a short alias;
- provide excellent `-h|--help` examples;
- use colored pretty output when it improves readability.

Suggested root help text:

```text
sase prompt - Manage previously submitted agent prompts

Examples:
  sase prompt list -q "prompt history"
  sase prompt show ph_8f3a9c0d12ab
  sase prompt run ph_8f3a9c0d12ab -d
  sase prompt run ph_8f3a9c0d12ab -e -P '#gh:bob-cli'
  sase prompt save ph_8f3a9c0d12ab -n prompt-history-review
  sase prompt export ph_8f3a9c0d12ab -s
```

## Options Considered

### Keep expanding `sase run`

Not recommended. `run` already owns launch, resume, xprompt/workflow execution, daemon mode, editor mode, and special
parsing. Deleting, exporting, saving, and diagnosing prompt history are not launch actions.

### Add `sase prompt-history`

Acceptable fallback, but less good. It is precise, but verbose, and it leaves no natural room for adjacent actions like
`save`, `export`, or `doctor`.

### Add `sase prompt`

Recommended. It is short, memorable, and a natural owner for prompt-history operations. Keep help text explicit:
"Manage previously submitted agent prompts." Do not position it as the xprompt-definition manager; that remains
`sase xprompt`.

### Migrate immediately to SQLite

Defer. SQLite is likely the right long-term storage if prompt history becomes a shared cross-frontend catalog, but an
immediate migration adds risk before the command contract is proven. Build the CLI against the current JSON store, then
migrate behind stable JSON/selector behavior later.

## Recommended Solution

Implement `sase prompt` as a new top-level command group in phases:

1. Start with a prompt-history catalog layer and the read/replay commands: `list`, `show`, `stats`, `run`, `edit`,
   `select`, and `copy`.
2. Add safe maintenance: `delete`, `doctor`, and guarded `prune`.
3. Add curation bridges: `save` to xprompt files and `export --sdd` to SDD prompt snapshots.
4. Keep `sase run "."` compatibility, but stop making the `.` token the primary documented interface.
5. Align with the active prompt-history TUI epic by treating history as recency-only and legacy-compatible.
6. Consider Rust-core/SQLite storage only after the CLI contract is stable or measured performance requires it.

This is ambitious enough to solve real workflows beyond "a nicer picker," but practical because the first phase can be
built on the existing JSON store, existing launch routing, existing clipboard behavior, existing SDD layout, and existing
xprompt loader.

## Code Pointers

- `src/sase/history/prompt.py` — prompt history schema, locking, dedupe, atomic writes, fzf formatting.
- `src/sase/main/parser.py` and `src/sase/main/entry.py` — top-level CLI registration and dispatch.
- `src/sase/main/parser_commands.py` — `sase run` and `file-history` parser precedents.
- `src/sase/main/query_handler/special_cases.py` — `sase run "."` and VCS-prefix history reuse.
- `src/sase/main/query_handler/_editor.py` — current fzf/editor picker.
- `src/sase/ace/tui/modals/prompt_history_modal.py` — TUI operations to mirror.
- `src/sase/main/parser_chats.py`, `src/sase/chats/cli_list.py`, `src/sase/history/chat_catalog.py` — catalog/list/show
  precedent with JSON output.
- `src/sase/xprompt/loader.py`, `src/sase/xprompt/loader_sources.py` — xprompt search paths and markdown loading.
- `sdd/epics/202606/prompt_history_tui.md` — active recency-only prompt-history target.
