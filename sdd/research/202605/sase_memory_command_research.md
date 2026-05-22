---
create_time: 2026-05-22
status: research
---

# `sase memory` Command Research

## Question

What `sase memory` subcommands would be most impactful for users, given the current memory architecture?

## Summary

The most valuable first `sase memory` release should make memory **visible, explainable, and diagnosable** before it
adds new authoring workflows.

Recommended MVP:

```bash
sase memory list [--json] [--tier short|long|dynamic|all]
sase memory match [--project PROJECT] [--json] [PROMPT...]
sase memory doctor [--json] [--fix]
sase memory init
```

The first three commands solve the highest-friction user problems:

1. "What memory exists, and which of it is actually dynamic?"
2. "Why did this prompt load, or not load, a memory file?"
3. "Is my memory setup broken, stale, shadowed, or unreachable?"

`sase memory init` should start as an alias/front door to the existing `sase init memory` behavior. That moves users
toward the new command group without forcing a migration immediately.

Defer write-heavy commands like `new`, `edit`, `promote`, and `prune` until the read-only surfaces are stable. Memory is
persistent agent instruction material, and this repo's `AGENTS.md` explicitly warns agents not to modify memory files
without user approval.

## Current State

### There is no top-level `memory` command today

The CLI parser currently registers top-level commands in `src/sase/main/parser.py`. The help output from the installed
venv lists commands such as `agents`, `config`, `init`, `xprompt`, and `workspace`, but no `memory`.

The only user-facing memory command is currently:

```bash
sase init memory
```

It is registered in `src/sase/main/parser_init.py` and handled by `src/sase/main/init_memory_handler.py`.

### `sase init memory` is setup-focused

`src/sase/main/init_memory_handler.py` initializes:

- `memory/short/sase.md`
- `memory/README.md`
- `memory/long/`
- `AGENTS.md` if missing
- provider shims: `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`

It also validates that memory files are reachable from `AGENTS.md` through direct or transitive references. That
reachability logic is already useful for a future `sase memory doctor`.

### Dynamic memory is implemented, but mostly invisible

Dynamic memory lives in `src/sase/memory/dynamic.py`.

Important behavior:

- Loads all prompts via `get_all_prompts(project=project)`.
- Filters to xprompt/workflow entries tagged `memory` with non-empty `keywords`.
- Splits positive and negative keywords; `!`-prefixed keywords mask matching spans rather than globally vetoing.
- Masks `$(...)` command substitution payloads before keyword matching.
- Writes matched memory files under `.sase/memory/`.
- Formats a prompt section:

```markdown
### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `commit skill`)
```

`src/sase/axe/run_agent_runner_setup.py` writes a `dynamic_memory.json` artifact and prints a launch-time summary, but
there is no standalone command to preview the match result before launching an agent.

### Long-term memory discovery is frontmatter-driven

`src/sase/xprompt/loader_memory.py` auto-discovers `memory/long/*.md` files as memory xprompts only when they have a
`keywords` field in YAML frontmatter. It scans project-local and provider-specific locations:

1. `<cwd>/memory/long/`
2. `<cwd>/.claude/memory/long/`
3. `<cwd>/.gemini/memory/long/`
4. `<cwd>/.codex/memory/long/`
5. `~/.claude/memory/long/`
6. `~/.gemini/memory/long/`
7. `~/.codex/memory/long/`

In this checkout, a direct loader probe found only one dynamic memory xprompt:

```text
memory/long/generated_skills
```

`AGENTS.md` lists three tier-3 files:

- `memory/long/generated_skills.md`
- `memory/long/llm_provider_hooks.md`
- `memory/long/tui_jk_baseline.md`

Only `generated_skills.md` has `keywords` frontmatter today, so only it is dynamic-eligible. That distinction is exactly
the kind of thing users need `sase memory list` and `sase memory doctor` to make obvious.

### Rust core already mirrors part of memory catalog loading

The sibling core repo has memory-aware catalog loading in
`../sase-core/crates/sase_core/src/xprompt_catalog.rs`. It also treats `memory/long/*.md` files with `keywords`
frontmatter as catalog entries tagged `memory`.

The editor diagnostics in `../sase-core/crates/sase_core/src/editor/frontmatter.rs` validate `keywords` and warn when
ordinary xprompt frontmatter has keywords without a `memory` tag. This is useful for editor feedback, but users still
need a CLI command that explains memory from the runtime point of view.

## Recommended Subcommands

### 1. `sase memory list`

Impact: highest. Users need one command that answers "what memory does SASE know about?"

Suggested output columns:

| Field | Why it matters |
| --- | --- |
| `name` | Stable reference, e.g. `memory/long/generated_skills` |
| `tier` | `short`, `long`, or generated dynamic cache |
| `source_path` | Where the content comes from |
| `dynamic` | Whether it can be auto-loaded by keyword matching |
| `keywords` | Why it can match |
| `reachable` | Whether `AGENTS.md` can lead an agent to it manually |
| `shadowed_by` | Whether another search-dir entry wins on name collision |

Useful flags:

```bash
sase memory list
sase memory list --tier long
sase memory list --dynamic
sase memory list --json
sase memory list --all-dirs
```

This should not be a thin wrapper over generic xprompt catalog listing. Memory users care about tiers, reachability,
dynamic eligibility, and stale generated files, not only xprompt catalog entries.

Implementation notes:

- Reuse `load_memory_long_xprompts()` for dynamic long memory.
- Reuse or extract `_memory_files()`, `_reachable_memory_files()`, and `_unreferenced_memory_files()` from
  `init_memory_handler.py`.
- Include `.sase/memory/long-*.md` generated cache entries separately, because those are runtime artifacts, not
  canonical memory.

### 2. `sase memory match`

Impact: very high. This is the missing dry-run for dynamic memory.

Suggested behavior:

```bash
sase memory match "change the commit skill"
echo "change the commit skill" | sase memory match
sase memory match --project sase --json "change the commit skill"
```

Default output should show:

- matched memory name;
- source path;
- matched positive keywords;
- masked negative keywords if relevant;
- generated `.sase/memory/` path;
- the exact `### DYNAMIC MEMORY` section that would be appended.

The command should default to **preview mode** and avoid writing `.sase/memory/` unless passed `--write`. Today
`generate_dynamic_memory()` writes as part of matching, so implementation should split the pure match phase from the
write phase or add a `write=False` option.

This command would have caught several historical debugging classes:

- false positives from command-substitution payloads;
- negative keyword masking surprises;
- stale dynamic memory sections in copied prompts;
- keyword word-boundary mismatches.

### 3. `sase memory doctor`

Impact: high. This command should turn setup and drift issues into actionable checks.

Initial checks:

- `AGENTS.md` exists and references expected tier-1 memory files.
- Provider shims point at `@AGENTS.md`.
- `memory/short/*.md` and `memory/long/*.md` are reachable from `AGENTS.md` or explicitly classified as dynamic-only.
- `memory/long/*.md` files that appear intended for dynamic matching have valid `keywords`.
- Keyword entries are non-empty strings.
- Generated `.sase/memory/long-*.md` cache files map to current `memory/long/*.md` sources.
- Generated dynamic cache files do not contain unresolved `$(cat ...)` payloads.
- Name collisions across the memory search dirs are reported with the winner.
- Python and Rust memory catalog counts agree for the paths they both understand.

Suggested flags:

```bash
sase memory doctor
sase memory doctor --json
sase memory doctor --fix
```

`--fix` should start conservatively:

- remove stale `.sase/memory/long-*.md` files;
- regenerate provider shims only after showing the target paths;
- maybe add missing `memory/README.md`.

It should not auto-edit canonical `memory/short` or `memory/long` content in the first version.

### 4. `sase memory init`

Impact: medium, but important for command ergonomics.

This should call the existing `handle_init_memory_command()` path and print the same output as `sase init memory`.

Why include it:

- Users looking for memory commands will naturally try `sase memory ...`.
- It gives the new command group a complete lifecycle: initialize, list, match, diagnose.
- It lets `sase init memory` remain backward-compatible while docs move to `sase memory init`.

### 5. `sase memory show`

Impact: medium. Useful, but less urgent than list/match/doctor.

Suggested behavior:

```bash
sase memory show memory/long/generated_skills
sase memory show memory/long/generated_skills --rendered
sase memory show .sase/memory/long-generated-skills.md
```

Default should show metadata plus source content. `--rendered` should resolve `$(cat ...)` the way dynamic memory will,
but should avoid running arbitrary command substitution beyond the known memory-generated `$(cat <path>)` shape if
possible.

This is useful for debugging but can wait because users can already read the file directly.

## Deferred Commands

### `sase memory new`

Potentially useful for scaffolding:

```bash
sase memory new long tui_rendering --keywords tui,jk,latency
```

It could create:

```markdown
---
keywords: [tui, jk, latency]
---

# TUI Rendering
```

Defer this until `list` and `doctor` settle the exact metadata contract. Authoring commands should preserve the
project's "do not modify memory without approval" principle and should probably default to printing a proposed file
unless explicitly asked to write.

### `sase memory promote`

Long-term high value, high risk.

This would promote knowledge from chats, agent artifacts, research files, or zettel into canonical memory. The
`sdd/research/202605/zettel_sase_shared_memory.md` research is relevant here: durable memory should use an inbox and
promotion workflow, not let agents write directly into canonical memory.

Possible future shape:

```bash
sase memory promote --from-agent <name> --to-inbox
sase memory promote --from sdd/research/202605/foo.md --kind long --review
```

This should wait for provenance, trust, and review mechanics.

### `sase memory prune`

Useful eventually, but risky as an early command. Start with `doctor` warnings and `doctor --fix` for generated cache
cleanup only.

## Proposed MVP UX

Example `list` output:

```text
NAME                         TIER   DYNAMIC  REACHABLE  KEYWORDS
memory/short/build_and_run   short  no       yes        -
memory/long/generated_skills long   yes      yes        sase commit, SKILL.md, commit skill
memory/long/llm_provider_hooks long no       yes        -
memory/long/tui_jk_baseline  long   no       yes        -
```

Example `match` output:

```text
Matched 1 memory

+ memory/long/generated_skills
  source: memory/long/generated_skills.md
  matched: commit skill
  dynamic path: .sase/memory/long-generated-skills.md

### DYNAMIC MEMORY
- @.sase/memory/long-generated-skills.md (memory/long/generated_skills, matched: `commit skill`)
```

Example `doctor` output:

```text
Memory doctor: 2 warnings

warning: memory/long/llm_provider_hooks.md is listed in AGENTS.md but has no keywords frontmatter
  It is reachable as tier-3 memory, but will never be loaded dynamically.

warning: .sase/memory/long-old-topic.md has no corresponding memory/long source
  Run: sase memory doctor --fix
```

## Implementation Shape

Add:

- `src/sase/main/parser_memory.py`
- `src/sase/main/memory_handler.py`
- top-level registration in `src/sase/main/parser.py`
- dispatch block in `src/sase/main/entry.py`

Keep domain logic outside the handler:

- `src/sase/memory/inventory.py` for `list` and `doctor` collection.
- `src/sase/memory/matching.py` or refactor `dynamic.py` to split matching from writing.

Suggested internal APIs:

```python
def collect_memory_inventory(root: Path, *, include_home: bool = True) -> MemoryInventory: ...
def match_dynamic_memory(prompt: str, project: str | None) -> DynamicMemoryResult: ...
def write_dynamic_memory_matches(result: DynamicMemoryResult) -> list[str]: ...
def diagnose_memory(inventory: MemoryInventory) -> list[MemoryDiagnostic]: ...
```

Do not put new shared backend semantics into Python if other frontends will need them. Per
`memory/short/rust_core_backend_boundary.md`, cross-frontend behavior belongs in `../sase-core`. The first Python CLI
can be a thin orchestrator over existing Python runtime behavior, but if mobile/editor surfaces need the same inventory
or diagnostics, graduate the data model into Rust core.

## Priority Order

1. `sase memory list --json`
2. `sase memory match --json`
3. `sase memory doctor`
4. `sase memory init`
5. `sase memory show`
6. `sase memory new`
7. `sase memory promote`

The first two are the core user value: users can see memory and predict dynamic loading. `doctor` turns that same
inventory into guidance. `init` completes the command group. Authoring and promotion are important, but they should be
built after users can inspect and trust what already exists.

## Open Questions

- Should `memory/long/*.md` without `keywords` be considered a warning, an informational note, or only a warning when
  `AGENTS.md` text implies dynamic behavior?
- Should dynamic matching preview write files by default for exact parity with agent launch, or stay dry-run by default
  for safety?
- Should `sase memory list` include home/provider memory by default, or require `--all-dirs` to avoid surprise?
- Should the Rust structured catalog expose memory keywords, or should Python remain the source of truth for dynamic
  matching until a broader memory API is needed?
- Should `sase init memory` eventually become hidden/deprecated after `sase memory init` exists?
