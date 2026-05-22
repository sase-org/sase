# `sase memory` Command Research

## Question

What `sase memory` subcommands would be most impactful to users?

## Short Answer

The highest-impact first version should make memory **observable and debuggable**, not primarily writable.

Recommended v1 command surface:

```bash
sase memory preview <prompt>          # show dynamic-memory matches before launching an agent
sase memory list                      # inventory memory entries by scope/source/type
sase memory show <name-or-path>       # inspect one memory entry and its metadata
sase memory doctor                    # validate reachability, keywords, conflicts, and bloat
sase memory tokens                    # estimate always-loaded and matched-memory token cost
```

Recommended v2 write surface:

```bash
sase memory propose                   # write a reviewable candidate into an inbox
sase memory review                    # list/show inbox candidates
sase memory promote <candidate>       # convert candidate into memory/long or another projection
sase memory search <query>            # retrieve memory mid-task
```

Recommended later/admin surface:

```bash
sase memory sync                      # only after a git-backed memory repository exists
sase memory import-zettel             # only after the zettel projection shape is chosen
sase memory retract --evidence <path> # cleanup path for poisoned or invalid promoted memory
```

## Local Current State

SASE already has two overlapping memory concepts:

1. **Initialized project/home memory files.** `sase init memory` creates `memory/short/`, `memory/long/`, `AGENTS.md`,
   and provider shims. It also checks for unreferenced memory files by walking `@` references from `AGENTS.md`.
2. **Dynamic memory.** `src/sase/memory/dynamic.py` loads memory-tagged xprompts, matches their `keywords` against the
   expanded prompt, writes matched content to `.sase/memory/`, and appends a `### DYNAMIC MEMORY` section to the prompt.

Current dynamic-memory source discovery:

- `src/sase/xprompt/loader_memory.py` auto-discovers `memory/long/*.md` files with YAML `keywords` frontmatter.
- It also scans runtime-specific memory dirs such as `.claude/memory/long`, `.gemini/memory/long`, and
  `.codex/memory/long` at both project and home scope.
- `src/sase/axe/run_agent_runner_setup.py` records `dynamic_memory.json` in the agent artifacts directory, but users do
  not have a direct CLI to ask "what would match this prompt?"

Important local research:

- `sdd/research/202604/dynamic_memory_critique.md` says the next step is growing and exercising the memory pool, and
  calls out the lack of a feedback loop on match quality.
- `sdd/research/202604/git_versioned_agent_memory.md` proposed a broader `sase memory` command, but the proposed CRUD
  surface now looks premature relative to the existing dynamic-memory implementation.
- `sdd/research/202605/zettel_sase_shared_memory.md` recommends inbox-first agent writes and projection into
  `memory/long/*.md`, not direct mutation of canonical memory.
- `sdd/research/202605/sase_dreams_design.md` recommends `sase memory retract --evidence <chat_path>` as a later
  security cleanup path once background memory distillation exists.

## External Signals

Claude Code has made memory inspectability a first-class UX. Its `/memory` command lists loaded memory files, toggles
auto memory, and opens the auto memory folder. Claude's docs also emphasize a concise `MEMORY.md` index, topic files
loaded on demand, and troubleshooting by verifying what memory loaded.

Letta Code's MemFS is the strongest prior art for a git-backed coding-agent memory filesystem. The relevant CLI
commands are operational: `status`, `diff`, `pull`, `backup`, `restore`, `export`, and `tokens`. Letta's docs also make
`system/` always-loaded and expose non-system files through a memory tree, using descriptions as navigational metadata.

Basic Memory's CLI and MCP wrappers emphasize `status`, `doctor`, `reindex`, note read/write/edit/search, schema
validation, schema inference, and schema drift detection. The useful pattern for SASE is not the exact note API; it is
the combination of health checks, machine-readable output, search, and schema drift tooling.

OpenHands' skills docs reinforce the same progressive-disclosure pattern SASE already uses: repository-wide `AGENTS.md`
for always-on context, and keyword-triggered or agent-invoked optional skills for context that should not always occupy
the prompt.

Recent research is also a warning against indiscriminate context. "Evaluating AGENTS.md" reports that repository context
files can reduce success and increase inference cost when they add unnecessary requirements. That strengthens the case
for `preview`, `doctor`, and `tokens` before adding more write automation.

## Ranked Subcommands

### 1. `sase memory preview <prompt>`

Highest user impact because it answers the most opaque question: "Why did this memory load, or why did it not load?"

Suggested behavior:

```bash
sase memory preview "update the generated skill files"
sase memory preview --project sase --json "update the generated skill files"
sase memory preview --content "update the generated skill files"
```

Output should show:

- matched memory name, source path, and written `.sase/memory/*` cache path;
- matched keywords;
- negative keywords that masked spans, when relevant;
- skipped memory candidates with optional `--why-not`;
- approximate token/line cost;
- `--json` for editor, mobile, and tests.

Why this is first:

- It reuses `generate_dynamic_memory()` and `format_dynamic_memory_section()` with minimal new domain logic.
- It directly supports memory authoring: users can tune `keywords` and immediately see the result.
- It makes the existing `dynamic_memory.json` artifact available before launch, not only after an agent has already run.

Naming note: `preview` is clearer than `explain` for a first command because it implies no agent launch and no writes
except optional cache writes. A future alias `sase memory explain` could include deeper tracing.

### 2. `sase memory doctor`

Second-highest impact because memory silently rots: files become unreferenced, keywords drift, generated projections
get stale, and always-loaded context grows until it hurts agent performance.

Suggested checks:

- `AGENTS.md` reachability, reusing `_unreferenced_memory_files()` from `init_memory_handler.py`.
- `memory/long/*.md` files with `keywords` but missing the effective memory tag after loader conversion.
- duplicate dynamic-memory names across project, runtime-specific, home, config, and plugin sources.
- keyword problems: empty keywords, duplicate keywords, overly broad one-word keywords, negative-only lists.
- files over configurable line/token thresholds.
- generated `.sase/memory/long-*.md` cache files whose source no longer exists.
- missing provider shims or shims that do not point at `@AGENTS.md`.
- optional `--fix` for mechanical repairs only, such as stale cache deletion.

Suggested examples:

```bash
sase memory doctor
sase memory doctor --json
sase memory doctor --fix
```

This should be a checker before it is a fixer. Memory is prompt-shaping code; destructive or interpretive changes need
human review.

### 3. `sase memory list`

High impact because users need an inventory before they can curate anything.

Suggested behavior:

```bash
sase memory list
sase memory list --scope project
sase memory list --tag memory --json
sase memory list --keywords skill
```

Columns:

- name, tier/scope, source path, keywords count, first keywords, line count, approximate token count;
- whether it is always loaded, dynamically matchable, generated/cache, or inbox candidate;
- shadowed-by / shadows when priority order causes collisions.

Implementation should reuse the xprompt catalog as much as possible. The Rust core already has xprompt catalog loading
for memory xprompts, so cross-frontend inventory belongs in core if this grows beyond Python CLI presentation.

### 4. `sase memory show <name-or-path>`

This is the natural companion to `list` and `preview`.

Suggested behavior:

```bash
sase memory show memory/long/generated_skills
sase memory show memory/long/generated_skills --metadata
sase memory show memory/long/generated_skills --format json
```

It should resolve by:

- xprompt-style memory name, such as `memory/long/generated_skills`;
- filesystem path;
- generated cache filename, such as `.sase/memory/long-generated-skills.md`;
- inbox candidate id later.

Useful details:

- parsed frontmatter;
- effective keywords;
- source precedence;
- whether it would be considered by dynamic memory;
- references from and to `AGENTS.md`/other memory files when cheap.

### 5. `sase memory tokens`

This can be part of `doctor` at first, but it is valuable enough to deserve a stable subcommand if memory grows.

Suggested behavior:

```bash
sase memory tokens
sase memory tokens --prompt "work on TUI latency"
sase memory tokens --top 20 --json
```

Report:

- always-loaded `AGENTS.md` and reachable `memory/short` cost;
- dynamic-memory cost for a supplied prompt;
- top largest memory files;
- warning thresholds for files that should move out of always-loaded context.

This maps directly to the AGENTS.md evaluation concern: unnecessary repository context can increase cost and reduce
task success, so users need a cheap way to see prompt-context weight.

### 6. `sase memory search <query>`

This is important, but it can wait until after `list/show/preview/doctor`.

Suggested behavior:

```bash
sase memory search "generated skills"
sase memory search --path src/sase/memory/dynamic.py
sase memory search --keyword skill --json
```

Start deterministic:

- text search over filenames, headings, frontmatter, keywords, and body;
- path search over future `applies_to` metadata;
- no vector index in v1.

This matches local zettel research: deterministic IDs, triggers, path applicability, and provenance should come before
embeddings.

### 7. `sase memory propose`, `review`, `promote`

Writable memory matters, but direct writes should not be v1.

Suggested workflow:

```bash
sase memory propose --type gotcha --title "TUI screenshot tests need Fira Code" < note.md
sase memory review
sase memory promote <candidate-id> --to memory/long/tui_testing.md
```

Rules:

- agents write proposals to an inbox, not canonical `memory/short` or `memory/long`;
- proposals carry provenance, source agent/chat/artifact paths, confidence, suggested keywords, and target tier;
- promotion is explicit and reviewable;
- `memory/short` promotion should be rare and probably require `--short` plus a warning.

This is the safest way to support "remember this" without opening the door to memory poisoning or low-quality transcript
summaries.

### 8. `sase memory sync`

Defer until SASE chooses a git-backed memory repository shape.

The April git-versioned memory research recommended a dedicated memory git repo. Letta validates that direction, but
the current repo already has project-local `memory/` plus runtime-specific discovery dirs. A sync command should not be
added until the storage source of truth is settled.

When it exists, scope it narrowly:

```bash
sase memory sync status
sase memory sync pull
sase memory sync push
```

Avoid hiding too much git behavior. Letta's MemFS docs explicitly leave commits and pushes mostly to git; SASE can wrap
common status/pull/push flows, but users should still be able to inspect the repository normally.

### 9. `sase memory import-zettel`

Valuable, but it depends on the zettel projection contract.

Useful later shape:

```bash
sase memory import-zettel --source ~/org --project sase --dry-run
```

It should generate or update `memory/long/*.md` projection files with `keywords` frontmatter and provenance links, not
copy arbitrary notes into always-loaded memory.

### 10. `sase memory retract --evidence <path>`

Important later security/admin command, not an MVP command.

Use once promoted memories carry provenance:

```bash
sase memory retract --evidence ~/.sase/chats/bad-session.md
```

Expected behavior:

- find promoted memories whose provenance cites the evidence path;
- quarantine or mark them retracted;
- regenerate affected projections;
- show downstream dynamic-memory names that changed.

This is the cleanup counterpart to the inbox/promotion model.

## Proposed MVP

Build the first release around read/diagnostic commands:

```bash
sase memory preview <prompt> [--project <name>] [--json] [--content] [--why-not]
sase memory list [--scope project|home|all] [--json]
sase memory show <name-or-path> [--format plain|markdown|json]
sase memory doctor [--json] [--fix]
sase memory tokens [--prompt <prompt>] [--json]
```

That gives users five immediate wins:

1. They can understand dynamic-memory matches before spending an agent run.
2. They can discover what memory exists.
3. They can inspect one memory entry without knowing the source path.
4. They can catch broken references, stale generated files, and keyword mistakes.
5. They can see context cost before memory bloat becomes invisible.

## Implementation Notes

Likely Python touchpoints:

- `src/sase/main/parser.py` — register a new top-level `memory` command group.
- `src/sase/main/parser_memory.py` — argparse definitions.
- `src/sase/main/memory_handler.py` — dispatch.
- `src/sase/memory/cli_preview.py` — `preview`.
- `src/sase/memory/cli_doctor.py` — `doctor`.
- `src/sase/memory/catalog.py` — shared inventory resolver over initialized files, dynamic-memory xprompts, and cache
  files.
- `src/sase/memory/tokens.py` — approximate token counters.

Reuse:

- `src/sase/memory/dynamic.py` for matching and formatting.
- `src/sase/xprompt/loader_memory.py` and `get_all_prompts()` for memory xprompt discovery.
- `src/sase/main/init_memory_handler.py` reachability helpers, likely moved to a non-CLI module if reused.
- `src/sase/xprompt/catalog.py` and Rust core catalog code if `list` needs parity across CLI/editor/mobile.

Boundary:

- If only the Python CLI needs presentation, keep it local.
- If editor/mobile/TUI also need the memory inventory, move the catalog shape into the Rust core per the repo's
  backend-boundary rule.

## UX Details

Use stable JSON from day one. SASE agents and editor/mobile helpers will use these commands as tooling.

Prefer verbs users already understand from nearby SASE commands:

- `list`, `show`, and `status` match `agents`, `chats`, `notify`, and `telemetry` patterns.
- `doctor` matches existing `bead doctor` and Basic Memory's health-check vocabulary.
- `preview` is task-specific and avoids overloading `xprompt explain`.

Do not make `sase memory init` the primary initializer yet because `sase init memory` already exists. If a top-level
alias is added later, keep it a thin compatibility alias and make the help text point to one canonical command.

## Open Questions

1. Should `preview` write `.sase/memory/` files by default, or only simulate? Recommendation: simulate by default, add
   `--write` only for debugging generated cache behavior.
2. Should `doctor --fix` rewrite frontmatter? Recommendation: no for v1. Limit fixes to deleting stale generated cache
   files and creating missing directories/shims.
3. Should `search` be part of v1? Recommendation: only if cheap after `list/show`; otherwise defer.
4. Should `tokens` count with a real tokenizer or a heuristic? Recommendation: heuristic first, with clear labeling.
5. Should memory candidates live in `.sase/memory/inbox/` or `~/.sase/memory/inbox/`? Recommendation: project-local
   inbox first for project facts; global inbox later for user preferences.

## Sources

Local:

- `src/sase/memory/dynamic.py`
- `src/sase/xprompt/loader_memory.py`
- `src/sase/axe/run_agent_runner_setup.py`
- `src/sase/main/init_memory_handler.py`
- `docs/xprompt.md`
- `sdd/research/202604/dynamic_memory_critique.md`
- `sdd/research/202604/git_versioned_agent_memory.md`
- `sdd/research/202605/zettel_sase_shared_memory.md`
- `sdd/research/202605/sase_dreams_design.md`

External:

- [Claude Code docs: How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Letta Code docs: Memory](https://docs.letta.com/letta-code/memory/)
- [Letta Code docs: MemFS](https://docs.letta.com/letta-code/memfs)
- [Basic Memory CLI reference](https://docs.basicmemory.com/reference/cli-reference)
- [OpenHands docs: Skills overview](https://docs.openhands.dev/overview/skills)
- [Git Context Controller: Manage the Context of LLM-based Agents like Git](https://arxiv.org/abs/2508.00031)
- [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/abs/2602.11988)
