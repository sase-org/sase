---
create_time: 2026-06-13
updated_time: 2026-06-13
status: research
---

# `sase prompt` Command Research

## Question

What functionality should a new `sase prompt` command provide to manage previously used SASE agent prompts from the
command line?

## Short Answer

Add `sase prompt` as a top-level prompt-history command group that makes prompt history observable, scriptable, and
replayable. The first version should focus on the existing prompt history store, not a new prompt database:

```bash
sase prompt copy <id>
sase prompt delete <id> [-y|--yes]
sase prompt doctor [-j]
sase prompt edit <id> [-d|--daemon]
sase prompt export <id> [-o PATH]
sase prompt list [-a] [-x] [-c CONTEXT] [-j] [-l LIMIT] [-p PROJECT] [-q QUERY]
sase prompt promote <id> [-k|--kind prompt|tale|epic] [-o PATH]
sase prompt run <id> [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX]
sase prompt select [-x] [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX] [-q QUERY]
sase prompt show <id> [-f raw|markdown|json]
```

Keep `sase run "."` / `sase run "#gh:sase ."` working as compatibility shortcuts, but stop treating them as the main
documented interface once `sase prompt select` and `sase prompt run` exist.

The highest-value behavior is not "a nicer fzf picker." It is a durable command surface with stable IDs, bounded
preview, JSON output, single-entry deletion, direct replay, editor-before-run, and promotion into SDD prompt files.

## Current State

### Prompt History Storage

Prompt history lives in `~/.sase/prompt_history.json`, through `src/sase/history/prompt.py`.

Current entry fields are:

- `text`
- `branch_or_workspace`
- `timestamp`
- `last_used`
- `workspace`
- `cancelled`

The writer deduplicates by exact `text`, preserves the original `timestamp`, updates `last_used`, and does not downgrade
a launched prompt back to cancelled when a later cancelled save uses the same text. Writes are protected with a sidecar
file lock and an atomic temp-file + `os.replace()` path.

Important constraints from the code:

- Short prompts are normally skipped unless `allow_short=True`; this intentionally filters many bare xprompt triggers.
- Multi-prompt text is currently split into segment mutations as well as the full prompt, though the June
  `prompt_history_tui` plan intends to simplify this.
- `get_prompts_for_fzf()` is a display-oriented API. It currently sorts by branch/workspace relevance and returns
  formatted strings plus entries; the active plan is to make this recency-only and remove context ranking.
- Existing readers still assume legacy context fields are present. The active plan calls for backward-compatible reads
  where those fields can be missing.

### Current CLI Behavior

`sase run` owns prompt-history reuse today:

- `sase run "."` opens the fzf prompt-history picker.
- `sase run "#gh:sase ."` opens the picker with a VCS prefix, then rewrites embedded VCS workflow tags to that prefix.
- `sase run --help` still documents `PROMPT` as a prompt, xprompt reference, workflow reference, or `.` for prompt
  history.

The picker itself is editor-oriented:

- `show_prompt_history_picker()` lists entries through fzf.
- The selected prompt is opened in `$EDITOR`, then the edited content is returned for launch.
- It requires fzf and has no non-interactive list/show/delete/export surface.

The TUI has a richer prompt-history modal:

- Enter submits the selected prompt.
- `Ctrl+G` edits first.
- `Ctrl+I` loads into the prompt input bar.
- `Ctrl+X` toggles cancelled prompts.
- `Ctrl+Y` copies the selected prompt.

The command-line surface does not expose those same operations directly.

### Existing Analog Commands

Useful local patterns:

- `sase chats list/show` has a proper inspectable catalog: pretty list by default, `-j|--json` for stable JSON,
  `-l|--limit`, `-q|--query`, and selector-based `show`.
- `sase file-history list/delete` is a minimal history-management command, but it is too small for prompts because
  prompts need replay/edit/export/promotion, not only list/delete.
- `sase xprompt list/expand/explain/graph/catalog` separates reusable prompt definitions from historical submitted
  prompts. `sase prompt` should not become an xprompt-definition manager.

### SDD Prompt Files

`sdd/prompts/YYYYMM/*.md` already stores durable original user prompts or prompt snapshots that led to plans, epics,
tales, legends, or research. A practical `sase prompt` command should make it easy to promote a useful historical prompt
into that durable SDD layer without copying from fzf/editor manually.

This is especially useful for prompts that become recurring task seeds, postmortem material, or plan/research inputs.

### Live Store Scale

I inspected aggregate metadata from the live prompt-history file without using raw prompt text in this recommendation.
As of 2026-06-13:

| Metric | Value |
| --- | ---: |
| File size | 32 MB |
| Entries | 9,064 |
| Cancelled entries | 723 |
| Entries last used in June 2026 | 734 |
| June cancelled entries | 51 |
| Unique prompt texts | 9,064 |
| Median prompt length | 211 chars |
| 90th percentile prompt length | 14,192 chars |
| 95th percentile prompt length | 19,825 chars |
| 99th percentile prompt length | 36,715 chars |
| Max prompt length | 348,980 chars |

Top workspaces by count:

| Workspace | Count |
| --- | ---: |
| `home` | 4,628 |
| `sase` | 3,865 |
| `bob-cli` | 259 |
| `zorg` | 153 |
| `.sase` | 126 |

The chat store is much larger: 41,954 markdown transcripts and about 277 MB under `~/.sase/chats`. That means prompt
history commands should remain fast and bounded by default. Transcript/provenance joins are useful but should be
optional, not part of every list.

## User Jobs

The command should cover real workflows that currently require brittle fzf/editor/manual copying.

### 1. Find A Prompt I Used Recently

Use case: "I launched a good agent yesterday; show me the exact prompt so I can rerun or adapt it."

Required command support:

```bash
sase prompt list
sase prompt list -q "prompt history" -l 20
sase prompt show ph_8f3a9c0d12ab
```

Why objective: the live store has thousands of entries and very long prompts; browsing through fzf alone is not enough.

### 2. Rerun A Prompt Exactly

Use case: "Run the same prompt again after I reverted a bad change."

Required command support:

```bash
sase prompt run ph_8f3a9c0d12ab
sase prompt run ph_8f3a9c0d12ab -d
```

Why objective: the TUI already supports direct submit from history. CLI parity should not require opening an editor.

### 3. Edit Before Rerun

Use case: "Reuse that prompt, but change the target file or ask for a plan first."

Required command support:

```bash
sase prompt edit ph_8f3a9c0d12ab
sase prompt run ph_8f3a9c0d12ab -e -d
```

Why objective: this is the current `sase run "."` behavior, but hidden behind a special prompt token and fzf.

### 4. Reuse A Prompt Against A New VCS Prefix

Use case: "Take an old `#gh:sase` prompt and run it against `#gh:bob-cli`."

Required command support:

```bash
sase prompt run ph_8f3a9c0d12ab -P '#gh:bob-cli'
```

Why objective: `sase run "#gh:sase ."` already implements VCS-tag replacement, so the need is proven. The new command
should make it explicit and testable.

### 5. Recover A Failed Or Cancelled Prompt

Use case: "I typed a long prompt, launch failed, and I want it back."

Required command support:

```bash
sase prompt list -x -q foobar
sase prompt show ph_cancelled123
sase prompt run ph_cancelled123 -e
```

Why objective: prompt history already records cancelled entries and the June prompt-history plan strengthens failed
launch persistence. The CLI needs a discoverable cancelled view.

### 6. Clean Up Bad History Entries

Use case: "Delete test prompts like `foobar` or accidental huge pasted blobs."

Required command support:

```bash
sase prompt delete ph_8f3a9c0d12ab
sase prompt doctor
```

Why objective: the live store contains short entries and very large entries. A 32 MB JSON file is still fine, but users
need safe maintenance tools before it becomes slow or noisy.

### 7. Promote A Prompt To A Durable SDD Artifact

Use case: "This successful prompt should become a durable SDD prompt for a tale, epic, or research item."

Required command support:

```bash
sase prompt promote ph_8f3a9c0d12ab -k prompt
sase prompt promote ph_8f3a9c0d12ab -o sdd/prompts/202606/prompt_command.md
```

Why objective: SDD already treats prompt files as durable planning context; history is volatile operational state. The
command should bridge them.

### 8. Use Prompt History From Scripts Or Editor Integrations

Use case: Neovim, mobile, or another frontend wants prompt-history candidates without scraping human output.

Required command support:

```bash
sase prompt list -q history -j
sase prompt show ph_8f3a9c0d12ab -f json
```

Why objective: `sase chats list -j` and other list commands already expose stable JSON because frontends need it.

## Command Design

### Stable Selectors

Prompt history currently has no explicit ID. Add a display/selector ID derived from content:

```text
ph_<sha256(prompt_text)[:12]>
```

Rationale:

- The store already deduplicates by exact text, so a content hash is stable and unique enough for human selectors.
- `last_used` and `timestamp` can change or collide; they are useful metadata, not good primary selectors.
- No migration is required. IDs can be computed at read time and later persisted if needed.

If a hash collision ever occurs, the CLI can ask for the longer hash or accept full `sha256:<hex>`.

### `sase prompt list`

Purpose: recency-ordered prompt inventory.

Recommended flags:

```bash
sase prompt list [-a] [-x] [-c CONTEXT] [-j] [-l LIMIT] [-p PROJECT] [-q QUERY]
```

Options:

- `-a|--all`: no default limit.
- `-x|--cancelled`: include cancelled prompts.
- `-c|--context`: filter legacy `branch_or_workspace` / VCS context.
- `-j|--json`: stable machine-readable array.
- `-l|--limit`: max rows, default 20.
- `-p|--project`: filter `workspace`.
- `-q|--query`: case-insensitive substring search over prompt text and selected metadata.

Pretty columns:

```text
ID              LAST USED       STATUS     PROJECT     CONTEXT       PROMPT
ph_8f3a9c0d12ab 2026-06-13 09:23 launched   sase        sase          Can you help me...
```

Do not print full prompt text in `list`; very long prompts are common.

JSON fields:

```json
{
  "id": "ph_8f3a9c0d12ab",
  "timestamp": "260613_092331",
  "last_used": "260613_092331",
  "cancelled": false,
  "workspace": "sase",
  "context": "sase",
  "text_preview": "Can you help me...",
  "text_chars": 269,
  "text_sha256": "8f3a9c0d12ab..."
}
```

### `sase prompt show`

Purpose: inspect one exact historical prompt.

```bash
sase prompt show <id> [-f raw|markdown|json]
```

Formats:

- `raw`: exact text only, suitable for piping.
- `markdown`: metadata header plus fenced or literal prompt body.
- `json`: stable object including full text.

This command should never truncate unless an explicit future `-p|--preview` flag is used.

### `sase prompt run`

Purpose: launch a selected prompt.

```bash
sase prompt run <id> [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX]
```

Behavior:

- Without `--edit`, run exact text.
- With `--edit`, open editor before launch.
- With `-P|--prefix`, call the same VCS tag replacement helper currently used by `sase run "#vcs:ref ."`.
- Preserve existing launch routing: direct single prompt can run foreground; multi-prompt/alt/multi-model routes to
  daemon exactly as `sase run` does today.

Use `-P|--prefix`; avoid `-p` because `-p|--project` belongs to `list`.

### `sase prompt edit`

Purpose: convenience wrapper for `run --edit`, but useful enough to keep explicit.

```bash
sase prompt edit <id> [-d|--daemon] [-P|--prefix VCS_PREFIX]
```

This mirrors the old `sase run "."` workflow directly: select historical prompt, edit, submit.

### `sase prompt select`

Purpose: interactive selector.

```bash
sase prompt select [-x|--cancelled] [-d|--daemon] [-e|--edit] [-P|--prefix VCS_PREFIX] [-q QUERY]
```

Behavior:

- If fzf is installed and stdout is a TTY, show fzf.
- If fzf is missing, print a clear error that suggests `sase prompt list` and `sase prompt run <id>`.
- Support `-I|--print-id` later if editor integrations want an interactive selector that returns the ID only.

This command replaces the discoverability role of `sase run "."`.

### `sase prompt copy`

Purpose: copy prompt text to the clipboard.

```bash
sase prompt copy <id>
```

This matches the TUI modal's `Ctrl+Y` behavior. It is useful for pasting into web UIs, issue comments, or docs.

Implementation can reuse the same clipboard helper used by the TUI if it works outside Textual; otherwise use a small
platform helper with clear failure messages.

### `sase prompt delete`

Purpose: remove one bad or obsolete history entry.

```bash
sase prompt delete <id> [-y|--yes]
```

Rules:

- Default should ask for confirmation on a TTY.
- `-y|--yes` should be available for scripts.
- Delete by computed ID, not by text pasted on the command line.
- Use the same prompt-history lock and atomic replace path as existing writes.

Do not add bulk deletion in v1. Bulk delete/prune is easy to misuse with prompt history.

### `sase prompt export`

Purpose: write exact prompt text to a file.

```bash
sase prompt export <id> [-o PATH]
```

Default output path can be a temp file or stdout; explicit `-o|--out` is more useful.

Use cases:

- feed a long prompt into another command,
- attach a prompt to a bug report,
- prepare an SDD prompt manually.

### `sase prompt promote`

Purpose: create an SDD prompt artifact from history.

```bash
sase prompt promote <id> [-k|--kind prompt|tale|epic] [-o PATH]
```

Recommended v1:

- Write only under `sdd/prompts/YYYYMM/` by default.
- Generate a slug from the prompt's first line or require `-o` when slug inference is ambiguous.
- Include frontmatter with at least source metadata:

```yaml
---
source: prompt_history
source_prompt_id: ph_8f3a9c0d12ab
source_last_used: 260613_092331
---
```

Do not auto-create tales/epics in v1. Promotion should preserve a prompt, not infer a plan structure.

The `-k|--kind` flag can be deferred unless an implementation phase also wires SDD link repair.

### `sase prompt doctor`

Purpose: inspect history health, not repair by default.

```bash
sase prompt doctor [-j|--json]
```

Checks:

- missing or corrupt JSON,
- missing required fields,
- entries missing legacy fields when old readers still require them,
- duplicate content IDs,
- unusually large prompts,
- many cancelled prompts,
- prompts that are too short to be useful unless they were saved with explicit failed-launch logic,
- file size and entry count,
- whether `sase run "."` compatibility can resolve fzf.

Potential future `-F|--fix` actions:

- compact/normalize missing optional fields,
- delete entries by explicit IDs listed in a file,
- archive old entries into sharded month files.

Do not make `doctor` modify history in v1.

## Storage And API Changes

### Add A Prompt History Catalog Layer

Do not keep extending `get_prompts_for_fzf()` for CLI management. It is a display picker API.

Add a small reusable catalog layer, likely in `sase.history.prompt`, with presentation-neutral models:

```python
PromptHistoryRecord(
    id: str,
    text: str,
    timestamp: str,
    last_used: str,
    workspace: str | None,
    context: str | None,
    cancelled: bool,
    text_sha256: str,
)

list_prompt_history(
    query: str | None = None,
    include_cancelled: bool = False,
    workspace: str | None = None,
    context: str | None = None,
    limit: int | None = 20,
) -> list[PromptHistoryRecord]

resolve_prompt_history_ref(ref: str) -> PromptHistoryRecord
delete_prompt_history_ref(ref: str) -> bool
```

`get_prompts_for_fzf()` can become a thin compatibility wrapper over this catalog.

### Rust Core Boundary

Prompt history is currently Python-only, but the behavior is shared domain behavior:

- TUI needs it.
- CLI needs it.
- Editor/mobile integrations may need it.
- Future web or mobile frontends will need the same list/show/delete/run selectors.

Per the project boundary rule, long-term catalog/filter/delete behavior belongs in `sase-core` once it stabilizes. A
practical path is:

1. Implement the v1 CLI as a thin Python catalog around the existing Python store.
2. Keep the API presentation-neutral and tested.
3. Move the model/filter/delete semantics to Rust core when another frontend needs it or when prompt-history storage is
   reshaped.

Do not block v1 on a Rust migration. The existing prompt-history writer is already Python and has needed locking
behavior.

## Options Considered

### Option A: Keep `sase run "."` And Add Only Flags

Example:

```bash
sase run --history --history-json --history-delete ...
```

Pros:

- Fewer top-level commands.
- Minimal disruption.

Cons:

- `run` already mixes launch, resume, editor, xprompt, workflow, daemon, and special-case parsing.
- History management is not always a launch action.
- Delete/export/promote/doctor do not belong under `run`.
- The special `"."` token is obscure and already being removed from the TUI input widget.

Verdict: not recommended.

### Option B: Add `sase prompt-history`

Pros:

- Precise name.
- Avoids confusion with xprompts.

Cons:

- Verbose.
- Does not leave room for prompt-adjacent subcommands such as `promote`, `doctor`, or future `template`.
- SASE already has `file-history`; another `*-history` command would be coherent but less pleasant for frequent use.

Verdict: acceptable fallback, but less good than `sase prompt`.

### Option C: Add Top-Level `sase prompt`

Pros:

- Short and memorable.
- Can own prompt-history operations without overloading `run`.
- Leaves `xprompt` as the command for reusable prompt definitions.
- Natural home for future prompt linting, expansion previews, or SDD promotion.

Cons:

- Name may be confused with `xprompt`.
- Needs clear help text: "Manage previously submitted agent prompts," not "manage xprompt definitions."

Verdict: recommended.

### Option D: Build A New SQLite Prompt Database

Pros:

- Better query performance and indexing.
- Easier future provenance joins.

Cons:

- Overkill for v1.
- Requires migration/backfill.
- Adds a second source of truth or an immediate storage migration.
- The 32 MB JSON store is large but still manageable with bounded reads.

Verdict: defer. Consider only after list/search/delete behavior proves useful and performance becomes a measured issue.

## Recommended Solution

Implement `sase prompt` in three phases.

### Phase 1: Read-Only Catalog And Replay

Add:

```bash
sase prompt edit
sase prompt list
sase prompt run
sase prompt select
sase prompt show
```

Acceptance:

- `list` defaults to 20 recency-ordered non-cancelled prompts.
- `list -x` includes cancelled prompts.
- `list -j` emits stable JSON.
- `show <id> -f raw` prints exact prompt text.
- `run <id>` and `edit <id>` route through the same launch dispatch as `sase run`.
- `select` replaces `sase run "."` as the documented fzf entry point.
- `sase run "."` remains backward compatible.

### Phase 2: Safe Mutation And Maintenance

Add:

```bash
sase prompt delete
sase prompt doctor
```

Acceptance:

- Delete uses prompt-history locking and atomic replace.
- Delete is single-entry only in v1.
- Doctor reports file size, entry count, cancelled count, duplicate computed IDs, corrupt JSON, and oversized entries.
- Doctor is read-only unless a future explicit `-F|--fix` is added.

### Phase 3: SDD And Integration Workflows

Add:

```bash
sase prompt copy
sase prompt export
sase prompt promote
```

Acceptance:

- `copy` matches the TUI's copy use case.
- `export` writes exact prompt text.
- `promote` writes a new `sdd/prompts/YYYYMM/*.md` file with source metadata.
- No plan/tale/epic is auto-created unless a later SDD-specific phase designs that link.

### Help And CLI Rules

Follow the repo CLI rules:

- Keep subcommands sorted alphabetically in help.
- Give every public long option a short alias.
- Make `-h|--help` examples excellent.
- Prefer colored pretty output where it improves readability.

Suggested root help:

```text
sase prompt - Manage previously submitted agent prompts

Examples:
  sase prompt list -q "prompt history"
  sase prompt show ph_8f3a9c0d12ab
  sase prompt run ph_8f3a9c0d12ab -d
  sase prompt run ph_8f3a9c0d12ab -e -P '#gh:bob-cli'
  sase prompt promote ph_8f3a9c0d12ab -o sdd/prompts/202606/prompt_command.md
```

## Code Pointers

- `src/sase/history/prompt.py` — prompt history schema, locking, atomic writes, cancelled semantics, fzf display.
- `src/sase/main/query_handler/special_cases.py` — `sase run "."` and `#vcs .` special cases.
- `src/sase/main/query_handler/_editor.py` — current fzf/editor picker.
- `src/sase/main/parser_commands.py` — `sase run` parser and `file-history` parser precedent.
- `src/sase/main/file_history_handler.py` — minimal list/delete history handler precedent.
- `src/sase/main/parser_chats.py`, `src/sase/chats/cli_list.py`, `src/sase/chats/cli_show.py`,
  `src/sase/history/chat_catalog.py` — richer list/show/catalog precedent with JSON and selectors.
- `src/sase/ace/tui/modals/prompt_history_modal.py` — TUI prompt-history operations worth mirroring in CLI.
- `sdd/epics/202606/prompt_history_tui.md` — active plan to simplify prompt history to recency-only behavior and
  improve cancelled failed-launch persistence.
