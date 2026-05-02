---
create_time: 2026-04-13 13:26:51
status: done
prompt: sdd/prompts/202604/improve_long_memory.md
---

# Plan: Improve Long-Term Memory Files Based on AGENTS.md Best Practices

## Context

Research into 2,500+ repositories and academic studies (ETH Zurich AGENTbench) reveals a clear consensus on what makes
agent instruction files effective. The core insight: **agents should only be told what they cannot discover
independently**. Architectural overviews, data model field lists, enum values, CLI command tables, and standard
framework patterns are all derivable from code — including them wastes scarce context budget and, per research, can
actually _degrade_ agent performance by 4+ percentage points while increasing inference costs 20-23%.

The most effective agent context files are:

- **Short and specific** — under 150-200 lines for always-loaded content
- **Focused on non-inferable information** — "Would removing this cause the agent to make mistakes?"
- **Heavy on gotchas and design rationale** — the "why" behind non-obvious decisions
- **Light on reference material** — agents read code; they don't need it summarized
- **Human-curated, not auto-generated** — LLM-generated context files perform worse than no context at all

## Guiding Principles for Each File

1. **Delete anything derivable from code** — field lists, enum values, CLI `--help` output, standard framework patterns
2. **Keep non-obvious design decisions** — especially the "why" behind surprising behavior
3. **Keep gotchas and pitfalls** — things that would trip up an agent who only reads the code
4. **Keep cross-cutting invariants** — rules that span multiple files/modules and aren't obvious from any single
   location
5. **Keep actionable instructions** — "do X when Y" workflows that prevent mistakes
6. **Preserve keyword frontmatter** — the dynamic memory system depends on these for tier-2 matching

## File-by-File Changes

### Phase 1: `external_repos.md` — No changes

This file is already well-aligned with best practices. It contains genuinely non-derivable information (repo locations,
cross-repo workflows) and actionable instructions ("run `chezmoi apply` after committing"). No changes needed.

### Phase 2: `generated_skills.md` — No changes

Already focused on actionable workflows (init-skills pipeline), non-derivable coupling requirements (CLI/skill contract
sync), and reference tables that can't be inferred from code alone (which runtimes have which skills). No changes
needed.

### Phase 3: `changespec_lifecycle.md` — Minor trim

**Remove:**

- The "Sections" paragraph listing all ChangeSpec section names (NAME, DESCRIPTION, PARENT, etc.) — directly derivable
  from the `.gp` file format and parsing code

**Keep everything else.** This file is mostly non-obvious design decisions: status transition graph spanning multiple
code paths, suffix append/strip semantics, sibling auto-revert behavior, the deliberate choice to run suffix operations
outside the lock, parent-child invariants, add-then-remove archive strategy for crash safety, and mentor draft flag
serialization.

### Phase 4: `bead_system.md` — Moderate trim

**Remove:**

- Model field listing ("A bead (Issue) has: `id`, `title`, `status`...") — derivable from the dataclass
- Status and type enum values ("Statuses: OPEN, IN_PROGRESS, CLOSED") — derivable from code
- Key CLI Commands table — derivable from `sase bead --help`

**Keep:**

- ID generation scheme (base36 counter, hierarchical child IDs) — non-obvious algorithm
- Dependency semantics ("A depends on B means B must be CLOSED before A") — design decision
- Ready vs In-Progress soft claim mechanism — very non-obvious SQL-level behavior
- Closing cascade behavior for PLANs — design decision
- JSONL as source of truth with SQLite rebuild on mtime — non-obvious persistence strategy
- Workspace merging "most recent wins" strategy — non-obvious conflict resolution

### Phase 5: `xprompt_system.md` — Significant trim

**Remove:**

- Reference syntax table (#name, #name(args), #name:arg, etc.) — derivable from parser code and existing docs
- Directive syntax table (%approve, %edit, %hide, etc.) — derivable from code and `--help`
- Workflow step types list (agent, bash, python, prompt_part, parallel) — derivable from code
- Control flow keywords (if, for, repeat, while) — derivable from code
- Output binding syntax ({{ step_name }}) — derivable from code
- Frontmatter fields list — derivable from code

**Keep:**

- Loading priority chain (6 levels, lowest→highest) — spans multiple loader functions, non-obvious precedence
- Cartesian product behavior with %alt/%() — surprising, non-obvious combinatorial expansion
- All 4 gotchas (100-iteration limit, StrictUndefined, fenced code block protection, disabled regions)

### Phase 6: `tui_development.md` — Significant trim

**Remove:**

- Architecture listing (framework name, app class, 18 mixin names) — derivable from code
- Tab type/names and toggle mechanism — derivable from code
- Prefix-key mode names listing — derivable from code/config
- Modal lifecycle (push_screen pattern) — standard Textual framework usage
- Keymap resolution 5-step pipeline — derivable from code

**Keep:**

- Reactive `recompose=False` convention with manual `.update()` — project-specific convention that contradicts Textual
  defaults
- Prefix-key dispatch pattern — the fact that these are NOT Textual bindings but manual key dispatch in `on_key()` is a
  critical gotcha
- `CopyModeForwardingMixin` requirement for modals — non-obvious requirement
- Widget messaging pattern (emit message → app handler → reactive → display) — project-specific convention
- All 4 pitfalls — very valuable gotchas

### Phase 7: `axe_agent_runner.md` — Significant trim

**Remove:**

- Architecture hierarchy description (Orchestrator → Lumberjacks → Runners) — derivable from code
- Orchestrator startup behavior (PID file, SIGTERM, wait times) — derivable from code
- Lumberjack tick cycle step-by-step — derivable from code
- SharedRunnerPool implementation details (file path, fcntl.flock) — derivable from code

**Keep:**

- Agent Runner Phases (5-phase pipeline) — spans multiple methods, documents the ordering and the critical detail that
  memory injection happens before directive extraction
- Deferred Workspace behavior — non-obvious placeholder→real workspace transition
- No automatic slot expiration in SharedRunnerPool — gotcha, not obvious from the API
- Zombie detection thresholds (2-hour default) — non-obvious timeout value
- SIGTERM soft kill flag pattern — non-obvious that agent runner uses `soft=True` to avoid immediate exit, and the
  rationale (workspace cleanup)

## Scope Boundaries

- **Keywords frontmatter**: Preserve existing keywords in all files. Do not change the dynamic memory matching behavior.
- **AGENTS.md**: Do not modify AGENTS.md itself — the tier-3 descriptions there may need updating to match trimmed
  content, but that's a separate concern.
- **Short-term memory files**: Out of scope — those are always-loaded and already concise.
- **No new files**: This is a trimming exercise, not a reorganization.
