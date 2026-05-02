---
create_time: 2026-04-13 13:08:50
status: done
prompt: sdd/prompts/202604/grow_memory_pool.md
---

# Plan: Grow Dynamic Memory Pool

## Context

The dynamic memory critique (`sdd/research/202604/dynamic_memory_critique.md`) identifies "Grow the memory pool" as the #1
priority. Currently only 2 long-term memory files exist (`external_repos.md`, `generated_skills.md`) totaling ~60 lines
and ~16 keywords. The system is architecturally validated but empirically under-exercised.

## Goal

Add 5 new long-term memory files targeting domains that are complex, frequently worked on, and not already covered by
short-term memory. This exercises the keyword matching system with real diversity and provides agents with high-value
conditional context.

## Content Philosophy

Match the style of existing memory files: practical, concise (~30-60 lines), focused on **non-obvious knowledge** that
agents can't easily derive from reading code alone. Prioritize: invariants, gotchas, interaction patterns, architectural
"why" decisions, and key sequences of operations. Avoid: encyclopedic API docs, file listings, or anything derivable
from `grep`.

## Keyword Design

Each file gets 6-10 keywords. Keywords should be specific enough to avoid false positives with the current substring
matching (critique item #1), while covering the main entry points an agent prompt would use to talk about the domain.
Avoid single-character or extremely common words.

---

## Phase 1: Create the 5 memory files

All files go in `memory/long/`. Format: YAML frontmatter with `keywords` list, then markdown body.

### 1.1 — `changespec_lifecycle.md`

**Keywords:** `[changespec, status transition, suffix strip, archive, sibling, draft flag, mentor draft, parent-child]`

**Content covers:**

- ChangeSpec section overview (NAME, DESCRIPTION, PARENT, CL/PR, STATUS, COMMITS, HOOKS, COMMENTS, MENTORS, TIMESTAMPS)
- Status lifecycle graph: WIP → Draft ↔ Ready → Mailed → Submitted (terminal: Submitted, Reverted, Archived)
- Suffix semantics: `_<N>` appended on Ready→Draft, stripped on Draft/WIP→Ready; triggers sibling auto-revert
- Parent-child invariant: children must be WIP/Draft/Reverted before parent can reach Ready
- Suffix operations happen **outside** the lock (git branch rename can be slow); brief inconsistency window is by design
- Archive movement: terminal statuses move to `project-archive.gp`; add-then-remove strategy prevents data loss
- Mentor draft flags: Draft-eligible mentors tracked via `is_draft` flag; cleared on Draft→Ready, set on Ready→Draft
- PARENT reference auto-update: renaming a changespec atomically updates all PARENT references to it

### 1.2 — `xprompt_system.md`

**Keywords:** `[xprompt, directive, workflow step, prompt_part, reference expansion, workflow yaml, xprompt loading]`

**Content covers:**

- Loading priority (9 sources, lowest to highest): internal → plugins → config YAML → memory/long → project config →
  ~/xprompts → ~/.xprompts → xprompts/ → .xprompts/. Later sources overwrite earlier by name.
- Reference syntax: `#name`, `#name(args)`, `#name:arg`, `#name+`, `#name: text` (shorthand). Namespace: `#project/name`
- Directive syntax: `%approve`, `%edit`, `%hide`, `%model:X`, `%name:X`, `%plan`, `%repeat:N`, `%wait:X`. Short aliases:
  `%a`, `%e`, `%h`, `%m`, `%n`, `%p`, `%N`, `%w`
- `%alt` / `%(...)` Cartesian product: multiple `%alt` directives produce all combinations
- Workflow step types: `agent`, `bash`, `python`, `prompt_part`, `parallel`. Control flow: `if:`, `for:`,
  `repeat: until:`, `while:`. Output binding: `{{ step_name.field }}` in Jinja2 context
- Gotchas: 100-iteration circular expansion limit; Jinja2 uses StrictUndefined; fenced code blocks protected from
  expansion; `%model(m1,m2)` internally rewrites to `%alt(%model:m1,%model:m2)`
- Frontmatter fields: name, description, snippet, skill, tags, keywords, input (shortform preferred)

### 1.3 — `bead_system.md`

**Keywords:** `[bead, epic, phase, dependency, claim, beads create, beads ready, beads close]`

**Content covers:**

- Bead model: id (hierarchical for phases: `plan-id.N`), title, status (OPEN/IN_PROGRESS/CLOSED), issue_type
  (PLAN/PHASE), parent_id, assignee, dependencies
- PLAN = epic (top-level, has design file path); PHASE = work item under a PLAN (must have parent_id)
- Dependency semantics: `A depends on B` means B must be CLOSED before A is READY. Both OPEN and IN_PROGRESS block.
- Ready = OPEN + no non-CLOSED blockers. IN_PROGRESS never appears in ready list (soft claim mechanism)
- Closing a PLAN cascades to all non-CLOSED children with same close_reason
- Cross-epic dependencies allowed (PHASE in Plan A can depend on PHASE in Plan B)
- JSONL persistence: `issues.jsonl` is source of truth for git; DB rebuilt from JSONL if JSONL newer
- Workspace merging: scans sibling workspaces, takes version with most recent `updated_at`
- Key CLI: `beads create --type plan(file)`, `beads create --type phase(plan_id)`, `beads ready`, `beads dep add`,
  `beads close`, `beads sync`

### 1.4 — `tui_development.md`

**Keywords:** `[TUI, textual, widget, modal, keymap, panel, ace tui, keybinding, prefix mode]`

**Content covers:**

- Framework: Textual. Main app: `AceApp` with 14 action mixins. 3 tabs: changespecs, agents, axe (toggled via `.hidden`
  CSS class, no DOM recompose)
- Reactive properties with `recompose=False`: watch callbacks do manual `.update()` instead of DOM rebuild
- Prefix-key modes (%, z, leader comma, !, custom): activated via `_*_mode_active` boolean flags, dispatched in
  `on_key()`, not via Textual bindings. Pattern: activate flag → update footer → wait for second key → dispatch → clear
  flag → restore footer
- Keymap resolution: defaults from `default_config.yml` (single source of truth) → user/plugin overrides → validation
  (revert invalid/duplicate) → `KeymapRegistry` object passed to widgets
- Modal lifecycle: `push_screen(Modal, callback)` → user interacts → `modal.dismiss(result)` → callback. Modals must
  inherit `CopyModeForwardingMixin` for % keys to work
- Widget pattern: list selection → `SelectionChanged` message → app catches → updates `current_idx` reactive → watch
  callback → `_refresh_display()` → queries detail panel → `panel.update(data)`
- Pitfalls: don't call `_refresh_display()` in widget methods (emit message instead); don't query widgets in `compose()`
  (use `on_mount()`); don't use `recompose=True` on frequently-changing reactives; remember to clear mode flags on tab
  change

### 1.5 — `axe_agent_runner.md`

**Keywords:** `[axe, lumberjack, chop, agent runner, scheduler, daemon, runner pool, zombie]`

**Content covers:**

- Architecture: Orchestrator (parent) → Lumberjacks (schedulers) → Runners (agents/mentors/hooks)
- Lumberjack tick: refresh changespecs → filter by query → check chop eligibility (run_every + singleton per agent chop)
  → run eligible chops via ThreadPoolExecutor → aggregate results → persist timestamps atomically
- Agent runner phases: (1) workspace prep + dynamic memory gen + directive extraction → (2) wait dependencies (agent
  name / absolute time / duration) → (3) reference resolution → (4) execution with retry → (5) completion +
  notifications
- Deferred workspace: agents with %wait don't hold a real workspace during wait; placeholder claimed upfront, real
  workspace allocated after dependencies satisfied
- Concurrency: SharedRunnerPool uses file-based `fcntl.flock` counter; no automatic slot expiration — runners must
  explicitly release
- Zombie detection: stale suffix timestamps (>2h default) or dead PID checks; killed via SIGKILL
- SIGTERM handling: soft kill sets flag, allows finally blocks for workspace cleanup; exit code 128+15
- Orchestrator: kills existing on startup (SIGTERM → 15s → SIGKILL); monitors children every 1s; restarts any that exit
  unexpectedly (no backoff)
- Dynamic memory injection happens before directive extraction, so memory content can contain directives

## Phase 2: Update AGENTS.md

Add the 5 new files to the "Tier 3 (long-term) Memory" section with one-line descriptions, matching the existing bullet
format.

## Phase 3: Validate

Run `just check` to ensure no lint/format issues were introduced.
