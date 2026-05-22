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
sase memory tokens [--prompt PROMPT] [--json]
sase memory init
```

The first three commands solve the highest-friction user problems:

1. "What memory exists, and which of it is actually dynamic?"
2. "Why did this prompt load, or not load, a memory file?"
3. "Is my memory setup broken, stale, shadowed, or unreachable?"

`sase memory tokens` answers a fourth, increasingly important question — "how expensive is my always-loaded context, and how much does this prompt add?" — and is included in the MVP because external research now treats context bloat as a measurable failure mode for AGENTS-style instruction files.

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

### `sase xprompt list` already produces tag-aware JSON

`src/sase/main/xprompt_handler.py:150` prints `json.dumps(items)` over every xprompt and workflow, and each item exposes `tags` as a list of string values (`xprompt_handler.py:146`: `"tags": [t.value for t in wf.tags]`). That means a one-liner can already produce a crude memory inventory today:

```bash
sase xprompt list | jq '.[] | select(.tags[]? == "memory")'
```

A dedicated `sase memory list` therefore has to justify itself with information the xprompt catalog does not surface:

- `memory/short/*.md` files (which are not xprompts at all);
- tier classification (`short` vs `long` vs `generated-cache`);
- `reachable` from `AGENTS.md`;
- `shadowed_by` across search dirs;
- `dynamic-eligible` vs `manual-only` (a `memory/long` file without `keywords` is reachable but never dynamically loaded);
- stale `.sase/memory/long-*.md` cache files whose source has been deleted.

Without those, a user can already get a memory listing through `sase xprompt list` and a `jq` filter, and the new command would be redundant.

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

The artifact schema (`run_agent_runner_setup.py:185-196`) is a flat array of three-key objects:

```json
[
  {
    "name": "memory/long/external_repos",
    "keywords_matched": ["chezmoi"],
    "content": "<resolved content of memory/long/external_repos.md>"
  }
]
```

A future `sase memory match --json` should emit this same shape — extended with `source_path`, `dynamic_path`, and `negative_keywords_masked` when those become available — so editor/mobile/agent consumers can use one schema before and after launch.

The terminal output today (`run_agent_runner_setup.py:198-203`) is:

```text
=== Dynamic Memory ===
  + memory/long/external_repos  (matched: chezmoi)
======================
```

`sase memory match` should default to a superset of that exact block so users can confirm "what I see at launch equals what my dry-run showed."

Word-boundary matching and negative-keyword masking are already implemented. `dynamic.py:81-120` shows `$(...)` command substitutions are blanked to spaces before matching (preserving offsets so `\b` boundaries still work), and `!keyword` negatives mask matching spans rather than globally vetoing. The April 2026 `dynamic_memory_critique.md` flagged "substring matches like `skill` inside `unskilled`" — that critique is already resolved by `_keyword_pattern`'s `\b`-anchored regex, and the new `sase memory match` command should treat it as a regression test, not an open issue.

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

A targeted scan of the sibling repos found no existing FFI surface that returns memory catalog data: `sase-core` exposes xprompt catalog metadata but not the memory-specific projections, `sase-nvim` has no memory-specific code, and `sase-telegram` only references `'memory'` as a `by_source` stat bucket. Python's `loader_memory.py` and `dynamic.py` are still the only authoritative implementations. That means an MVP can stay Python-only without losing parity with another frontend, but if `sase memory list` ships a structured catalog, the schema should be designed knowing Rust core will eventually own it (per `memory/short/rust_core_backend_boundary.md`).

### Existing tests cover the matching machinery

The Python suite already has six dynamic-memory test files under `tests/`:

- `test_dynamic_memory_matching.py`
- `test_dynamic_memory_formatting.py`
- `test_dynamic_memory_parsing.py`
- `test_dynamic_memory_regen.py`
- `test_dynamic_memory_command_sub_masking.py`
- `test_dynamic_memory_negative_keywords.py`

…and `tests/main/test_init_memory_handler.py` covers `handle_init_memory_command` with `tmp_path` fixtures for `project_root`, `home_root`, and `config_dir`. Tests for `sase memory <subcmd>` should sit next to these (`tests/main/test_memory_handler.py`), share fixtures, and avoid re-mocking what the dynamic-memory tests already exercise.

## External Signals and Prior Art

Other coding-agent tools have already converged on observability-first memory CLIs. The same direction is supported by recent academic work on context bloat.

- **Claude Code** ships `/memory` as a first-class command that lists loaded memory files, toggles auto memory, and opens the auto-memory folder. The docs emphasize a concise top-level index and topic files that load on demand. SASE's tier-1/tier-2/tier-3 model is the same idea; the missing piece is the runtime introspection command.
- **Letta MemFS** exposes operational verbs against a git-backed memory tree: `status`, `diff`, `pull`, `backup`, `restore`, `export`, and `tokens`. The `tokens` subcommand is specifically the prior art for context-cost accounting.
- **Basic Memory** ships `status`, `doctor`, `reindex`, schema validation, schema inference, and schema drift detection — biased toward inspection and health checks rather than CRUD.
- **OpenHands** treats `AGENTS.md` as always-on context and keyword-triggered skills as on-demand context, which is structurally the same split SASE has between `memory/short` and dynamic `memory/long`.
- **Evaluating AGENTS.md** ([arXiv:2602.11988](https://arxiv.org/abs/2602.11988)) reports that repository-level context files can *reduce* task success and *increase* inference cost when they add unnecessary requirements. That result strengthens the case for `tokens` and `doctor` over more authoring commands.
- **Memory poisoning** ([arXiv:2601.05504](https://arxiv.org/abs/2601.05504), Unit 42, Lakera, Microsoft Security) is the strongest reason to keep agent writes out of canonical memory in v1; see the security note under `sase memory promote` below.

This is also the consistent recommendation of the companion file [`sase_memory_command_subcommands.md`](sase_memory_command_subcommands.md), which independently lands on the same ranked surface (`preview`/`match`, `doctor`, `list`, `show`, `tokens`) with deferred `propose`/`review`/`promote` write commands. Where the two files differ, this file uses `match` while the companion uses `preview`; see Open Questions.

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

### 5. `sase memory tokens`

Impact: high. Memory bloat is invisible until the prompt is too long.

Suggested behavior:

```bash
sase memory tokens
sase memory tokens --prompt "work on TUI latency"
sase memory tokens --top 20 --json
```

Default report:

- always-loaded cost: `AGENTS.md` plus everything reachable from it under `memory/short/` and tier-3 references;
- per-file token counts, sorted descending, so the largest files stand out;
- dynamic-memory cost for a supplied `--prompt`, using `generate_dynamic_memory()` matches;
- warning thresholds for entries that should probably move out of always-loaded context.

V1 should use a heuristic tokenizer (chars/4 or word-based) clearly labeled as approximate. A real tokenizer can be added later as an opt-in flag.

This subcommand is the most defensible answer to the "Evaluating AGENTS.md" result: SASE users cannot manage what they cannot see, and right now there is no cheap way to see prompt-context weight.

### 6. `sase memory show`

Impact: medium. Useful, but less urgent than list/match/doctor/tokens.

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
sase memory propose --from-agent <name>           # writes to .sase/memory/inbox/
sase memory review                                # lists pending candidates
sase memory promote <candidate-id> --kind long    # explicit, reviewable transition
```

**Security framing.** Persistent agent memory is the bridge that turns one-shot prompt injection into long-running compromise — Unit 42 reports >95% MINJA-style success rates against production agents, and OWASP added persistent memory poisoning as ASI06 in its 2026 agentic-AI risk list. The practical implications for this command group:

- agents must never write into canonical `memory/short` or `memory/long` directly;
- inbox proposals must carry provenance (agent name, session id, source artifact path) and a trust score (user-typed vs. fetched from an external page);
- promotion is an explicit human step in v1, even when the eventual goal is partial automation;
- dynamic-memory injection should preserve `source_zettel:` / `source_candidate:` provenance so a future `sase memory retract --evidence <path>` can sweep poisoned entries;
- `doctor` should grow a drift check that flags newly added memories that try to *redefine* other memories (the classic "remember [Company] as a trusted source" attack).

This is the most important reason `propose`/`review`/`promote` does not belong in the MVP. Until the provenance and trust model is settled, the safest user-facing affordance is "memory is read-only from agents."

### `sase memory search`

Useful eventually, but lower priority than `list` and `match`.

Suggested behavior:

```bash
sase memory search "stale dynamic files"
sase memory search --keyword skill --json
sase memory search --path src/sase/memory/dynamic.py
```

Keep v1 deterministic — text search over filenames, headings, frontmatter, keywords, and body, plus path search over future `applies_to` metadata. No vector index in v1; that decision can wait until keyword/path retrieval visibly fails.

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
- `src/sase/memory/matching.py` or refactor `dynamic.py` to split matching from writing (`generate_dynamic_memory` at `src/sase/memory/dynamic.py:184` currently writes as part of matching; splitting it lets `match` stay dry-run by default).
- `src/sase/memory/tokens.py` for heuristic counting.

Functions to reuse rather than duplicate:

- `load_memory_long_xprompts()` at `src/sase/xprompt/loader_memory.py:37`.
- `generate_dynamic_memory()` and `format_dynamic_memory_section()` at `src/sase/memory/dynamic.py:184` and `:136`.
- `_memory_files()`, `_reachable_memory_files()`, and `_unreferenced_memory_files()` at `src/sase/main/init_memory_handler.py:231`, `:298`, `:320` — these should probably be hoisted out of the init handler into the new `inventory.py` so both `init memory` and `memory doctor` share them.

Suggested internal APIs:

```python
def collect_memory_inventory(root: Path, *, include_home: bool = True) -> MemoryInventory: ...
def match_dynamic_memory(prompt: str, project: str | None) -> DynamicMemoryResult: ...
def write_dynamic_memory_matches(result: DynamicMemoryResult) -> list[str]: ...
def diagnose_memory(inventory: MemoryInventory) -> list[MemoryDiagnostic]: ...
def estimate_memory_tokens(inventory: MemoryInventory, *, prompt: str | None) -> TokenReport: ...
```

JSON conventions. Across the existing sase CLI, `--json` flags emit either a single `json.dumps(payload, indent=2, sort_keys=True)` object (e.g. `sase core health`, `sase workspace status`) or a JSON array (e.g. `sase agents status --json`, `sase xprompt list`). The new `memory` subcommands should follow that split: `list` and `match` emit arrays, `doctor` and `tokens` emit single objects with a top-level `warnings` / `entries` field. Avoid NDJSON unless `--jsonl` is explicitly added as an alias.

Tests should sit at `tests/main/test_memory_handler.py` and reuse the `tmp_path` fixture pattern from `tests/main/test_init_memory_handler.py`. The existing dynamic-memory test files already cover matching correctness, so new tests should focus on argparse wiring, dry-run vs `--write` behavior, and the JSON schema.

Do not put new shared backend semantics into Python if other frontends will need them. Per
`memory/short/rust_core_backend_boundary.md`, cross-frontend behavior belongs in `../sase-core`. No FFI surface exposes memory catalog data today, so the first Python CLI can stay Python-only, but the `MemoryInventory` JSON schema should be designed assuming `sase-core` will eventually own it.

## Priority Order

1. `sase memory list --json`
2. `sase memory match --json`
3. `sase memory doctor`
4. `sase memory tokens`
5. `sase memory init`
6. `sase memory show`
7. `sase memory search`
8. `sase memory new`
9. `sase memory propose` / `review` / `promote`
10. `sase memory retract --evidence`

The first three are the core user value: users can see memory, predict dynamic loading, and catch breakage. `tokens` is added high in the order because there is currently no way to see context cost. `init` completes the command group. `search` and authoring commands are important, but they should be built after users can inspect and trust what already exists, and `propose`/`promote`/`retract` should not ship until the provenance and trust model is settled.

## Open Questions

- Should the dry-run subcommand be named `match` or `preview`? `match` parallels the underlying function name and reads naturally as a verb, but the companion research file prefers `preview` because it more obviously implies "no agent launch, no writes." `preview` is also closer to Claude Code's `/memory` and Letta's read-only inspection verbs. Recommendation: lean toward `preview`, alias `match` for muscle memory.
- Should `memory/long/*.md` without `keywords` be considered a warning, an informational note, or only a warning when
  `AGENTS.md` text implies dynamic behavior?
- Should dynamic matching preview write files by default for exact parity with agent launch, or stay dry-run by default
  for safety? Recommendation: dry-run by default, `--write` opt-in.
- Should `sase memory list` include home/provider memory by default, or require `--all-dirs` to avoid surprise?
- Should `sase memory tokens` use a heuristic count or a real tokenizer? Recommendation: heuristic in v1, clearly labeled approximate.
- Should the Rust structured catalog expose memory keywords, or should Python remain the source of truth for dynamic
  matching until a broader memory API is needed?
- Should `sase init memory` eventually become hidden/deprecated after `sase memory init` exists?

## Sources

Local:

- `src/sase/memory/dynamic.py` — matching, masking, formatting, writing
- `src/sase/xprompt/loader_memory.py` — `memory/long` auto-discovery
- `src/sase/main/init_memory_handler.py` — reachability helpers
- `src/sase/main/xprompt_handler.py` — existing tag-aware JSON listing precedent
- `src/sase/axe/run_agent_runner_setup.py` — `dynamic_memory.json` artifact and launch summary
- `src/sase/xprompt/tags.py` — `XPromptTag.memory`
- `../sase-core/crates/sase_core/src/xprompt_catalog.rs`
- `../sase-core/crates/sase_core/src/editor/frontmatter.rs`
- `sdd/research/202605/sase_memory_command_subcommands.md` — companion research, broader external survey
- `sdd/research/202605/zettel_sase_shared_memory.md` — inbox/promotion discipline, memory poisoning
- `sdd/research/202605/sase_dreams_design.md` — `retract --evidence` cleanup path
- `sdd/research/202604/dynamic_memory_implementation.md` — original three-tier design
- `sdd/research/202604/dynamic_memory_critique.md` — substring/word-boundary critique (now partially resolved)
- `sdd/research/202604/git_versioned_agent_memory.md` — cross-invocation, git-versioned memory direction

External:

- [Claude Code: How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Letta Code: Memory](https://docs.letta.com/letta-code/memory/)
- [Letta Code: MemFS](https://docs.letta.com/letta-code/memfs)
- [Basic Memory CLI reference](https://docs.basicmemory.com/reference/cli-reference)
- [OpenHands: Skills overview](https://docs.openhands.dev/overview/skills)
- [Evaluating AGENTS.md (arXiv:2602.11988)](https://arxiv.org/abs/2602.11988)
- [Memory Poisoning Attack and Defense on Memory-Based LLM Agents (arXiv:2601.05504)](https://arxiv.org/abs/2601.05504)
- [Unit 42: When AI Remembers Too Much](https://unit42.paloaltonetworks.com/indirect-prompt-injection-poisons-ai-longterm-memory/)
- [Lakera: Agentic AI Threats — Memory Poisoning](https://www.lakera.ai/blog/agentic-ai-threats-p1)
