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
sase memory test                      # assert that given prompts match/do-not-match given memory
```

Recommended v2 write and runtime surface:

```bash
sase memory propose                   # write a reviewable candidate into an inbox
sase memory review                    # list/show inbox candidates
sase memory promote <candidate>       # convert candidate into memory/long or another projection
sase memory search <query>            # retrieve memory mid-task (also exposed as an agent skill)
sase memory cache clear               # delete stale .sase/memory/*.md projection files
```

Recommended later/admin surface:

```bash
sase memory sync                      # only after a git-backed memory repository exists
sase memory import-zettel             # only after the zettel projection shape is chosen
sase memory retract --evidence <path> # cleanup path for poisoned or invalid promoted memory
sase memory diff                      # changes since last review (after inbox/promote exists)
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

What is **not** currently wired up (verified by repo exploration):

- **No plugin-supplied memory.** Sibling repos (`sase-github_13`, `sase-telegram_13`, `sase-nvim_13`, `sase-core_13`)
  do not ship `memory/` directories or memory-tagged xprompts today. Discovery is entirely driven by
  `loader_memory._get_memory_long_search_dirs()`. There is no `src/sase/plugin/` extension point for memory.
- **No memory-related hooks.** `src/sase/ace/hooks/` has no `on_memory_match`, `before_memory_load`, or similar event.
  The hook system tracks ChangeSpec and test-target execution, not memory operations.
- **No memory bead type.** Beads are `plan` and `phase` only (`src/sase/main/parser_bead.py`).
- **No memory telemetry.** `src/sase/telemetry/metrics.py` instruments agent runs, LLM invocations, hook executions,
  bead operations, and notifications — but no memory match counters, no match-rate gauges, no prompt-context-weight
  histograms. The April critique flagged this as the biggest gap; nothing has been added since.
- **No agent-callable memory at runtime.** `dynamic.py` runs once at setup before launch. Agents cannot search,
  read, or propose memory mid-run through a skill or MCP-style call.
- **No memory inclusion in multi-machine sync.** `sase sync` and workspace open code do not handle memory.

Existing CLI conventions observed in nearby command groups:

- `sase bead doctor` is a single subcommand and does not currently expose `--json`.
- `sase chats list` uses `--json`; `sase chats show` uses `--format`.
- `sase notify` exposes `create`, `list`, `show`.
- `sase xprompt` exposes `expand`, `explain`, `graph`, `list`, `catalog`; `graph` uses `--format`.
- No existing command exposes `--scope`. Introducing it for memory would be new vocabulary.

Important local research:

- `sdd/research/202604/dynamic_memory_critique.md` says the next step is growing and exercising the memory pool, and
  calls out the lack of a feedback loop on match quality.
- `sdd/research/202604/dynamic_memory_implementation.md` documents the current discovery/match implementation.
- `sdd/research/202604/short_term_vs_long_term_memory.md` defines the tier vocabulary used here.
- `sdd/research/202604/agents_md_token_optimization.md` argues that always-loaded context weight is a real cost; this
  directly motivates `tokens` and `doctor` checks for bloat.
- `sdd/research/202604/git_versioned_agent_memory.md` proposed a broader `sase memory` command, but the proposed CRUD
  surface now looks premature relative to the existing dynamic-memory implementation.
- `sdd/research/202605/zettel_sase_shared_memory.md` recommends inbox-first agent writes and projection into
  `memory/long/*.md`, not direct mutation of canonical memory.
- `sdd/research/202605/sase_dreams_design.md` recommends `sase memory retract --evidence <chat_path>` as a later
  security cleanup path once background memory distillation exists.
- `sdd/research/202605/multi_machine_sync.md` notes memory is not yet in scope for sync.

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

Two additional comparators worth weighing:

- **Cursor rules and Aider conventions.** Both expose memory/context as plain files (`.cursorrules`, `CONVENTIONS.md`)
  and offer no real inspection CLI. The result is exactly the opacity SASE should avoid: users cannot tell whether a
  rule loaded or applied without reading the raw transcript. This validates `preview` as the most differentiating v1
  command.
- **Mem0 / Zep / MemGPT (Letta) memory services.** Their primary surface is programmatic (`add`, `search`,
  `update`, `delete`), with optional dashboards. They expose retrieval as a first-class capability the agent calls at
  runtime, not just at setup. SASE's current model is closer to "compile memory into the prompt before launch," which
  is cheaper and more reproducible — but the gap is that agents have no fallback when needed memory was not matched
  at setup. An agent-callable `sase memory search` (and a corresponding skill) closes that gap without giving up
  reproducibility.
- **Goose memory extension.** Goose ships a built-in memory extension with `remember_memory` / `retrieve_memories`
  tool calls, scoped local vs global. Same agent-callable lesson, plus a useful scope vocabulary (`local`, `global`)
  that maps cleanly onto SASE's project/home distinction.

Recent research is also a warning against indiscriminate context. "Evaluating AGENTS.md" reports that repository
context files can reduce success and increase inference cost when they add unnecessary requirements. That strengthens
the case for `preview`, `doctor`, and `tokens` before adding more write automation.

### Comparator matrix

| System              | Inspect what loaded | Doctor/lint | Tokens   | Agent-callable at runtime | Inbox/promotion | Git-backed sync |
| ------------------- | ------------------- | ----------- | -------- | ------------------------- | --------------- | --------------- |
| Claude Code         | yes (`/memory`)     | partial     | no       | no                        | no              | no              |
| Letta MemFS         | yes (tree)          | partial     | yes      | yes                       | partial         | yes             |
| Basic Memory        | yes                 | yes         | no       | yes (MCP)                 | no              | yes             |
| OpenHands skills    | partial             | no          | no       | partial                   | no              | no              |
| Cursor rules        | no                  | no          | no       | no                        | no              | no              |
| Aider conventions   | no                  | no          | no       | no                        | no              | no              |
| Mem0 / Zep / Letta  | partial (dashboard) | no          | partial  | yes (primary surface)     | varies          | varies          |
| Goose memory ext.   | partial             | no          | no       | yes                       | no              | no              |
| **SASE today**      | only post-run JSON  | partial     | no       | no                        | no              | no              |

Gaps SASE should close first: **inspect what loaded** (preview), **doctor**, **tokens** — three columns that no
comparator does meaningfully better than SASE could with modest CLI work.

## Ranked Subcommands

### 1. `sase memory preview <prompt>`

Highest user impact because it answers the most opaque question: "Why did this memory load, or why did it not load?"

Suggested behavior:

```bash
sase memory preview "update the generated skill files"
sase memory preview --project sase --json "update the generated skill files"
sase memory preview --content "update the generated skill files"
sase memory preview --prompt-file ./long-prompt.md
sase memory preview --why-not memory/long/tui_jk_baseline "work on TUI latency"
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

Accept input from `--prompt-file` and stdin so users can pipe real prompts in without quoting issues — important
because realistic prompts often contain shell metacharacters.

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
sase memory doctor --check unreferenced,bloat,duplicates
```

This should be a checker before it is a fixer. Memory is prompt-shaping code; destructive or interpretive changes need
human review. The `--check` filter lets the same command serve interactive use, pre-commit hooks, and CI without
having to expose ten subcommands.

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

Follow the existing convention: `--json` for `list` (matches `sase chats list`), not `--format`.

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

Follow `sase xprompt graph` / `sase chats show` convention: `--format plain|markdown|json`.

### 5. `sase memory tokens`

This can be part of `doctor` at first, but it is valuable enough to deserve a stable subcommand if memory grows.

Suggested behavior:

```bash
sase memory tokens
sase memory tokens --prompt "work on TUI latency"
sase memory tokens --top 20 --json
sase memory tokens --budget 8000          # exit non-zero if exceeded
```

Report:

- always-loaded `AGENTS.md` and reachable `memory/short` cost;
- dynamic-memory cost for a supplied prompt;
- top largest memory files;
- warning thresholds for files that should move out of always-loaded context.

The `--budget` flag enables CI use: a repository can fail builds when always-loaded memory crosses a chosen ceiling.
This is the cheapest tool against the "AGENTS.md bloat reduces task success" finding.

Tokenizer choice: heuristic (`len / 4` or character classes) by default; expose `--tokenizer claude|gpt|heuristic`
when a real tokenizer is available, with the heuristic clearly labeled so users do not assume billing-level accuracy.

### 6. `sase memory test`

New recommendation, added to address the missing feedback loop on keyword quality.

Suggested behavior:

```bash
sase memory test                                  # run cases from .sase/memory/tests/
sase memory test --case examples/skill_prompt.md  # one case
sase memory test --json
```

Test cases are tiny YAML/Markdown files declaring:

- a prompt body;
- memory names that **must** match;
- memory names that **must not** match;
- optional notes for humans.

This converts keyword tuning from "vibes" into a reproducible regression suite, mirrors `just test` ergonomics, and
makes `dynamic_memory_critique.md`'s feedback-loop concern actionable. It also gives `doctor` a stronger signal —
a memory file with empty test coverage can be warned about.

Test discovery: project `.sase/memory/tests/`, home `~/.sase/memory/tests/`, both globbed. Failures should print the
expected vs actual matched-name diff, not the matched-content blob, to keep output reviewable.

### 7. `sase memory search <query>`

Important, but it can wait until after `list/show/preview/doctor` — with one caveat: it should be designed up front
as an **agent-callable** capability, not only a CLI affordance.

Suggested behavior:

```bash
sase memory search "generated skills"
sase memory search --path src/sase/memory/dynamic.py
sase memory search --keyword skill --json
sase memory search --agent-mode --json    # compact stable schema for skill consumption
```

Start deterministic:

- text search over filenames, headings, frontmatter, keywords, and body;
- path search over future `applies_to` metadata;
- no vector index in v1.

This matches local zettel research: deterministic IDs, triggers, path applicability, and provenance should come before
embeddings. The agent-mode flag exists so a generated skill can call `sase memory search` mid-run and parse the
output without depending on the human-friendly format.

### 8. `sase memory propose`, `review`, `promote`

Writable memory matters, but direct writes should not be v1.

Suggested workflow:

```bash
sase memory propose --type gotcha --title "TUI screenshot tests need Fira Code" < note.md
sase memory propose --from-chat <chat-id>     # provenance: a prior sase chat
sase memory review
sase memory promote <candidate-id> --to memory/long/tui_testing.md
```

Rules:

- agents write proposals to an inbox, not canonical `memory/short` or `memory/long`;
- proposals carry provenance, source agent/chat/artifact paths, confidence, suggested keywords, and target tier;
- promotion is explicit and reviewable;
- `memory/short` promotion should be rare and probably require `--short` plus a warning.

Integration with existing surfaces:

- `--from-chat` ties a proposal to a `sase chats` artifact (see the chats reference); makes retract straightforward.
- A new `memory.proposed` notification (via `sase notify`) surfaces inbox growth without forcing users to poll.

This is the safest way to support "remember this" without opening the door to memory poisoning or low-quality
transcript summaries.

### 9. `sase memory cache clear`

A small but real paper cut today: `.sase/memory/*.md` is rewritten on every launch and orphan files accumulate when a
source memory file is renamed or deleted. `doctor --fix` should already handle this, but a dedicated subcommand is
useful for CI scripts and local triage where users do not want `doctor` to do anything else.

```bash
sase memory cache clear              # delete every .sase/memory/*.md projection
sase memory cache clear --orphans    # only those whose source is gone
sase memory cache path               # print the cache directory
```

### 10. `sase memory sync`

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

### 11. `sase memory import-zettel`

Valuable, but it depends on the zettel projection contract.

Useful later shape:

```bash
sase memory import-zettel --source ~/org --project sase --dry-run
```

It should generate or update `memory/long/*.md` projection files with `keywords` frontmatter and provenance links, not
copy arbitrary notes into always-loaded memory.

### 12. `sase memory retract --evidence <path>`

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
sase memory preview <prompt> [--project <name>] [--json] [--content] [--why-not] [--prompt-file <path>]
sase memory list [--scope project|home|all] [--json]
sase memory show <name-or-path> [--format plain|markdown|json]
sase memory doctor [--json] [--fix] [--check unreferenced,bloat,duplicates,...]
sase memory tokens [--prompt <prompt>] [--budget <n>] [--json]
sase memory test [--case <path>] [--json]
```

That gives users six immediate wins:

1. They can understand dynamic-memory matches before spending an agent run.
2. They can discover what memory exists.
3. They can inspect one memory entry without knowing the source path.
4. They can catch broken references, stale generated files, and keyword mistakes.
5. They can see context cost before memory bloat becomes invisible.
6. They can pin desired matching behavior with regression tests, so keyword churn does not silently degrade.

## Cross-Frontend and Agent-Callable Access

Memory inspection is wanted from more places than the CLI:

- **TUI / editor / mobile** want `list` and `show` for browsing.
- **Hooks and CI** want `doctor --json`, `tokens --budget`, and `test --json` exit codes.
- **Running agents** want `search` and (with care) `propose`.

This pushes two design choices:

1. The catalog/match logic should live in or be reachable from `sase-core` per the repo's rust-core-backend-boundary
   rule, with the Python CLI as one frontend. Today the xprompt catalog already has Rust loading; memory inventory
   should not diverge.
2. `sase memory search` and `sase memory propose` should ship a generated skill so agents can invoke them through the
   normal commit-skill style runtime contract. This avoids per-runtime special cases (Claude vs Codex vs Gemini) and
   keeps a single interface — consistent with the `memory/short/gotchas.md` uniform-runtime rule.

A runtime-callable surface is what differentiates SASE from Cursor/Aider-style flat memory files, without giving up
the reproducibility of compile-at-launch dynamic memory.

## Hook and Telemetry Integration

Memory is currently invisible to both subsystems. Both should change:

- **Hooks.** Add `memory.matched`, `memory.skipped`, and `memory.proposed` events to the `src/sase/ace/hooks/`
  registry. This lets users wire logging, lint, or notification behavior without modifying core. Example: a project
  hook that fails the launch when `memory/short/*` exceeds a token budget.
- **Telemetry.** Add `MEMORY_MATCHES`, `MEMORY_MATCH_BYTES`, `MEMORY_PROMPT_TOKENS`, and `MEMORY_CACHE_WRITES` to
  `src/sase/telemetry/metrics.py`. Match-rate over time is the missing feedback signal that the April critique flagged.
- **Notifications.** When a prompt loads zero dynamic memory but the body strongly resembles a known memory file's
  domain (path or word overlap), emit a `memory.suggestion` notification — actionable without being intrusive.

`doctor` should consume telemetry once available: "this file has matched 0 times in 30 days" is a much stronger
keyword-tuning signal than static analysis alone.

## Risks and Failure Modes

- **Memory poisoning via auto-promotion.** Any future `propose`/`promote` flow must default to manual review.
  Adversarial or low-quality chat transcripts should never reach `memory/long/` without an explicit user step. The
  inbox model plus `retract --evidence` is the mitigation; do not weaken either for convenience.
- **Token bloat regressions.** Adding `tokens --budget` to CI prevents quiet growth. Without it, the next critique
  paper will be SASE's own.
- **Keyword collisions and shadowing.** As `memory/long/` grows, two memories will fight for the same prompt.
  `doctor` must surface shadow chains; `list` must show `shadowed-by`.
- **Cache staleness as a security issue.** A renamed memory file leaves a `.sase/memory/long-old-name.md` projection
  on disk. If anything else reads cache directly (it should not, but agents are creative), the stale content can leak
  back in. `cache clear --orphans` and a `doctor` check should run on every launch in CI.
- **Cross-machine drift.** Until sync exists, two checkouts of the same project on different machines diverge in
  `.sase/memory/`. This is fine if every consumer always regenerates from source, but should be documented.
- **Plugin trust.** When plugin-supplied memory eventually exists, treat third-party memory as untrusted by default.
  `list` should label source provenance; `doctor` should warn on unsigned/unfamiliar sources.

## Out of Scope (Deliberately)

- **Embedding-based or vector retrieval.** Deterministic keyword/path matching first; revisit only after `search`
  is in real use.
- **Automatic summarization or compaction.** Background distillation is the `sase_dreams_design.md` track. Memory
  CLI should not run LLMs by default.
- **Cross-project memory federation.** A single project's memory is hard enough. Federation can wait for the
  sync/zettel work to settle.
- **A "remember this" UX in the TUI launcher.** Worth doing eventually, but should sit on top of `propose`, not
  bypass it.

## Validation / Success Metrics

A v1 release should be considered successful if, four weeks after rollout:

- `sase memory preview` shows up in agent launch traces ahead of `sase ace` for a non-trivial fraction of sessions.
- `sase memory doctor` runs in CI for the main repo and catches at least one real keyword/shadow issue before merge.
- `sase memory tokens --budget` is wired into at least one repo and has prevented a measurable bloat regression.
- The `memory/long/` pool grows (more, smaller, well-keyworded files) instead of `memory/short/` growing.
- Telemetry shows non-zero match counts across most memory files; files with zero matches in 30 days are pruned.

If `preview` does not change user behavior, the whole effort is questionable — that is the single most important
leading indicator.

## Implementation Notes

Likely Python touchpoints:

- `src/sase/main/parser.py` — register a new top-level `memory` command group.
- `src/sase/main/parser_memory.py` — argparse definitions.
- `src/sase/main/memory_handler.py` — dispatch.
- `src/sase/memory/cli_preview.py` — `preview`.
- `src/sase/memory/cli_doctor.py` — `doctor`.
- `src/sase/memory/cli_test.py` — `test` runner.
- `src/sase/memory/catalog.py` — shared inventory resolver over initialized files, dynamic-memory xprompts, and cache
  files.
- `src/sase/memory/tokens.py` — approximate token counters.
- `src/sase/telemetry/metrics.py` — new memory counters.
- `src/sase/ace/hooks/registry.py` — new memory event types.

Reuse:

- `src/sase/memory/dynamic.py` for matching and formatting.
- `src/sase/xprompt/loader_memory.py` and `get_all_prompts()` for memory xprompt discovery.
- `src/sase/main/init_memory_handler.py` reachability helpers, likely moved to a non-CLI module if reused.
- `src/sase/xprompt/catalog.py` and Rust core catalog code if `list` needs parity across CLI/editor/mobile.

Boundary:

- If only the Python CLI needs presentation, keep it local.
- If editor/mobile/TUI also need the memory inventory, move the catalog shape into the Rust core per the repo's
  backend-boundary rule.

Test surface:

- Unit tests over `catalog`, `tokens`, and `cli_test` parsing.
- Integration tests that drive each CLI subcommand against a fixture project under `tests/`.
- Golden `--json` schemas, since this surface will be consumed by editor/mobile/agent skills.

## UX Details

Use stable JSON from day one. SASE agents and editor/mobile helpers will use these commands as tooling.

Match existing SASE CLI conventions confirmed by repo exploration:

- `list` subcommands use `--json` (matches `sase chats list`).
- `show`/`graph` subcommands use `--format plain|markdown|json` (matches `sase chats show`, `sase xprompt graph`).
- `doctor` subcommands return non-zero on failures; `--fix` for mechanical repairs only (matches `sase bead doctor`).
- Verbs already in nearby command groups: `list`, `show`, `status`, `doctor`.
- `preview` is task-specific and avoids overloading `xprompt explain`.

Do not make `sase memory init` the primary initializer yet because `sase init memory` already exists. If a top-level
alias is added later, keep it a thin compatibility alias and make the help text point to one canonical command.

Avoid inventing a new `--scope` flag if `--project` and `--home` already exist anywhere nearby. (Today they do not, so
introducing `--scope project|home|all` is fine — but check `parser_*.py` once just before implementation.)

## Open Questions

1. Should `preview` write `.sase/memory/` files by default, or only simulate? Recommendation: simulate by default, add
   `--write` only for debugging generated cache behavior.
2. Should `doctor --fix` rewrite frontmatter? Recommendation: no for v1. Limit fixes to deleting stale generated cache
   files and creating missing directories/shims.
3. Should `search` be part of v1? Recommendation: only if cheap after `list/show`; otherwise defer — but design the
   `--agent-mode` JSON schema during v1 so it does not change later.
4. Should `tokens` count with a real tokenizer or a heuristic? Recommendation: heuristic first, with clear labeling.
5. Should memory candidates live in `.sase/memory/inbox/` or `~/.sase/memory/inbox/`? Recommendation: project-local
   inbox first for project facts; global inbox later for user preferences.
6. Should `sase memory test` cases live in `tests/` (with the rest of the test suite) or `.sase/memory/tests/`
   (alongside memory)? Recommendation: `.sase/memory/tests/` — they describe memory behavior, not code behavior,
   and should travel with memory in any future memory-only sync.
7. Should agent-callable `search`/`propose` be exposed as commit-skill style skills or as MCP servers? Recommendation:
   skill files generated by the existing pipeline, to keep runtimes uniform per `memory/short/gotchas.md`.
8. Should `doctor` consume telemetry (e.g., "this memory has 0 matches in 30 days") in v1? Recommendation: no — ship
   telemetry as part of v1 but defer telemetry-driven `doctor` checks to v2 once enough data exists.
9. Should plugin-supplied memory be allowed at all in v1? Recommendation: no — leave `loader_memory.py` as-is and
   revisit when an actual plugin asks for memory.

## Sources

Local:

- `src/sase/memory/dynamic.py`
- `src/sase/xprompt/loader_memory.py`
- `src/sase/axe/run_agent_runner_setup.py`
- `src/sase/main/init_memory_handler.py`
- `src/sase/main/parser_bead.py`, `parser_chats.py`, `parser_xprompt.py`, `notify_handler.py` (CLI convention check)
- `src/sase/ace/hooks/` (no memory events today)
- `src/sase/telemetry/metrics.py` (no memory metrics today)
- `docs/xprompt.md`
- `sdd/research/202604/dynamic_memory_critique.md`
- `sdd/research/202604/dynamic_memory_implementation.md`
- `sdd/research/202604/short_term_vs_long_term_memory.md`
- `sdd/research/202604/agents_md_token_optimization.md`
- `sdd/research/202604/git_versioned_agent_memory.md`
- `sdd/research/202605/zettel_sase_shared_memory.md`
- `sdd/research/202605/sase_dreams_design.md`
- `sdd/research/202605/multi_machine_sync.md`

External:

- [Claude Code docs: How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Letta Code docs: Memory](https://docs.letta.com/letta-code/memory/)
- [Letta Code docs: MemFS](https://docs.letta.com/letta-code/memfs)
- [Basic Memory CLI reference](https://docs.basicmemory.com/reference/cli-reference)
- [OpenHands docs: Skills overview](https://docs.openhands.dev/overview/skills)
- [Cursor docs: Rules for AI](https://docs.cursor.com/context/rules-for-ai)
- [Aider conventions docs](https://aider.chat/docs/usage/conventions.html)
- [Goose docs: Memory extension](https://block.github.io/goose/docs/tutorials/memory-extension)
- [Mem0 docs](https://docs.mem0.ai/)
- [Zep docs: Memory](https://help.getzep.com/concepts)
- [Git Context Controller: Manage the Context of LLM-based Agents like Git](https://arxiv.org/abs/2508.00031)
- [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/abs/2602.11988)
