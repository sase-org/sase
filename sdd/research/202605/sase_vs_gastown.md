# SASE vs. Gas Town

A grounded comparison of this project (SASE) with Steve Yegge's **Gas Town**, written to surface
concrete ideas SASE could borrow and to clarify where the two diverge on purpose.

- **Date:** 2026-05-11
- **Gas Town ref:** v1.1.0, May 7 2026 (release dates in this note treated as April–May 2026; see
  caveat in §7).
- **SASE ref:** current `master`, this workspace.

## 1. Source map

**Gas Town — primary sources**

- Yegge, *Welcome to Gas Town* — https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04
- Yegge, *Gas Town: From Clown Show to v1.0* —
  https://steve-yegge.medium.com/gas-town-from-clown-show-to-v1-0-c239d9a407ec
- Yegge, *Welcome to the Wasteland: A Thousand Gas Towns* —
  https://steve-yegge.medium.com/welcome-to-the-wasteland-a-thousand-gas-towns-a5eb9bc8dc1f
- Yegge, *Gas Town Emergency User Manual* —
  https://steve-yegge.medium.com/gas-town-emergency-user-manual-cf0e4556d74b
- Repo: https://github.com/gastownhall/gastown (MIT)
- Architecture: https://gastown.dev/docs/design/architecture/
- Hooks: https://github.com/gastownhall/gastown/blob/main/docs/HOOKS.md
- Agent provider integration:
  https://github.com/gastownhall/gastown/blob/main/docs/agent-provider-integration.md
- Releases: https://github.com/gastownhall/gastown/releases
- HN thread: https://news.ycombinator.com/item?id=47770124

**SASE — primary sources** (this repo)

- `AGENTS.md`, `memory/short/*.md`, `memory/long/*.md`
- Provider registry: `src/sase/llm_provider/registry.py`, per-runtime adapters in
  `src/sase/llm_provider/{claude,codex,gemini,opencode,qwen}.py`
- ChangeSpec parser/models: `src/sase/ace/changespec/parser.py`,
  `src/sase/ace/changespec/section_parsers.py`, `models.py`
- XPrompt loader/processor: `src/sase/xprompt/loader.py`, `processor.py`, `workflow_models.py`
- ACE TUI: `src/sase/ace/tui/app.py` (`AceApp`)
- AXE engine: `src/sase/axe/run_agent_runner.py`
- Bead model/db: `src/sase/bead/model.py`, `src/sase/bead/db.py`
- Workspace launcher: `src/sase/agent/launch_spawn.py:spawn_agent_subprocess`
- Hookspecs: `src/sase/workspace_provider/_hookspec.py`, `src/sase/agent/_hookspec.py`
- Skill deploy: `src/sase/main/init_skills_handler.py`
- Sibling repos: `../sase-core` (Rust), `../sase-github`, `../sase-telegram`, `../sase-nvim`,
  `../sase-gchat`, `../sase-google`, `../sase-android`

## 2. One-paragraph positioning

Both systems are **multi-agent SWE orchestration layers** sitting on top of existing CLI coding
agents (Claude Code, Codex, Gemini, OpenCode, etc.). Neither tries to be its own coding model. The
divergence is in scope and metaphor:

- **SASE** is a *workflow + control-plane* for one developer running many agents on many local
  worktrees, with a strong emphasis on (a) ChangeSpec-as-source-of-truth for in-flight CLs/PRs,
  (b) reusable, composable prompts (XPrompts), and (c) a Textual TUI (ACE) to drive everything.
  It is Python-first with a Rust core (`sase-core`) for shared backend logic.
- **Gas Town** is a *town-and-rigs orchestrator* in Go, organized around a Mad-Max metaphor (Mayor,
  Polecats, Convoys, Refinery, Witness, Deacon). It is much more opinionated about agent lifecycle
  ("a polecat takes a bead, works end-to-end, opens an MR, hands off to the Refinery") and uses
  **Dolt** as a SQL-backed canonical store rather than per-project files.

## 3. Side-by-side feature comparison

| Dimension | SASE | Gas Town |
| --- | --- | --- |
| **Language / runtime** | Python (with Rust core `sase-core`) | Go 1.25+, single binary |
| **Agent runtimes supported** | Claude, Codex, Gemini, OpenCode, Qwen, "plain" | Claude Code, Codex, Copilot, Cursor, Auggie, OpenCode, Pi; Gemini/AMP via Tier-0 |
| **Agent invocation model** | Subprocess per agent in ephemeral `sase_<N>` workspace (full repo clone, own venv) | Per-agent tmux session keystroke-injected by the Deacon |
| **Work-unit canonical form** | **ChangeSpec** `.gp` text file in `~/.sase/projects/<project>/`, lifecycle WIP → Draft → Ready → Mailed → Submitted | **Bead** record in Dolt (`hq-*` at town, per-rig prefixes), consumed via the `bd` CLI |
| **Issue / dep tracker** | `sdd/beads/` JSONL + SQLite (`sase bead {create,ready,list,dep,show}`) | Beads (separate Yegge project, https://github.com/steveyegge/beads) consumed by Gas Town |
| **Central coordinator** | None per se; ACE TUI is the user's cockpit, AXE runner schedules agents | **Mayor** — a long-lived Claude Code instance with full town context; the user talks to it |
| **Worker abstraction** | Ad-hoc agents launched from ACE / xprompts; lifetime tied to one task | **Polecats** (ephemeral session, persistent identity), **Crew** (long-lived design), **Dogs** (cross-rig batch) |
| **Storage layer** | Files (`.gp`, JSONL, SQLite for beads, repo state in git worktrees) | **Dolt** SQL server (one per town, port 3307); agents write directly to `main` with transaction discipline |
| **Merge gate** | Per-runtime commit skills + hook history; CI on PR | **Refinery** — Bors-style batch-then-bisect merge queue |
| **Health monitoring** | None as a first-class subsystem | **Witness** (per-rig), **Deacon** (heartbeats + plugins), **Boot** (watchdog when Deacon dies) |
| **Hook taxonomy** | pytest-style hookspecs (`workspace_provider`, `agent`); per-CL HOOKS section; hook history JSON | `SessionStart`, `PreCompact`, `UserPromptSubmit`, `Stop`, `PreToolUse` — explicitly mirrors Claude Code's native hooks |
| **Reusable prompt library** | **XPrompts** (`.md` single-step or `.yml` multi-step: `prompt_part` / `python` / `bash`); resolved from `xprompts/`, `.claude/xprompts/`, and built-ins | "Roles" templates (mayor, polecat, witness, …) embedded in the binary; merged base → role → rig+role |
| **Multi-machine model** | Single-developer, single-machine assumption; sync research exists (sdd/research/202605/multi_machine_sync.md) | "Town" can host many rigs; "A Thousand Gas Towns" envisions a federated mesh |
| **UX surface** | Textual TUI (`sase ace`) with ChangeSpecs / Agents / Background Tasks / Dashboard tabs; CLI commands; nvim plugin; Telegram/GChat notifiers | tmux sessions + Mayor as conversational interface; CLI (`gt`) |
| **Frontends / integrations** | Sibling repos: sase-github, sase-telegram, sase-gchat, sase-nvim, sase-android | Plugins via Deacon; settings/agents.json presets |
| **License / source posture** | Mixed private + open siblings; not yet a single public release | MIT, single repo, public from day one |

## 4. Where the metaphors *actually* differ

**"Bead" is a name collision, not a shared abstraction.**
SASE beads (`sdd/beads/`) are local JSONL issues with a small SQLite index, scoped to one repo's
SDD process. Gas Town's beads come from Yegge's standalone Beads project — a git-backed knowledge
graph distributed via the `bd` CLI, with hierarchical IDs (`gt-abc12`) and town-vs-rig scoping.
The Gas Town flow ("a polecat picks up a bead → opens an MR → hands off to the Refinery") is much
more pipeline-shaped than SASE's "a ChangeSpec accumulates commits and comments over its lifetime."

**ChangeSpec ≠ bead, even functionally.**
The SASE ChangeSpec is closer to a Phabricator revision or a long-form PR description: it carries
NAME / DESCRIPTION / PARENT / CL|PR|BUG / STATUS / TEST_TARGETS / COMMITS / HOOKS / COMMENTS /
MENTORS / TIMESTAMPS / DELTAS in one editable text file. Gas Town keeps issue-tracking data
relational (Dolt) and PR-shaped data in the forge (GitHub/Bitbucket); there is no equivalent
combined artifact.

**Mayor is the most distinctive Gas Town primitive.**
A persistent conversational coordinator with the whole town's state in its context window is
something SASE currently has no analog for. SASE has a TUI cockpit (ACE) and an orchestrator (AXE)
but no *agent you talk to about the agents*. This is also Gas Town's most opinionated bet — it
spends one whole agent slot, continuously, on coordination.

**Refinery vs. SASE commit hooks.**
Gas Town owns the merge gate explicitly with a batch-then-bisect queue. SASE delegates merge
decisions to CI on the forge (GitHub) plus per-runtime commit skills (`sase_git_commit.md`) that
enforce hooks like `just check`. The SASE approach is lighter but yields no batching across
in-flight agents.

**Dolt vs. files.**
Gas Town's "everything is rows in a Dolt table on one well-known port" replaces a lot of
file-watching, lock-coordination, and stale-cache complexity at the cost of a daemonized SQL
server. SASE's "everything is files plus a small SQLite index" keeps the surface area smaller
and git-trackable but has hit consistency issues in practice (see the notification-store /
ACE test failures around `dismiss_agent_completions` observed in the prior run).

## 5. Strengths and weaknesses

**SASE strengths**

- ChangeSpec is the right shape for one developer reviewing many in-flight PRs: human-editable,
  diffable, and fits naturally with code review.
- XPrompts are *first-class composable* — the `.yml` workflow form with `prompt_part`/`python`/
  `bash` steps is more flexible than Gas Town's role templates.
- Per-agent workspace clones (`sase_<N>`) give true isolation without tmux contortions, and
  enable agents to run with separate dependency sets.
- Rust core (`sase-core`) creates a clean place for cross-frontend (TUI, web, mobile, nvim) logic.
- Memory tiering (short / dynamic / long) is more structured than Gas Town's role templates.

**SASE weaknesses (where Gas Town points at concrete gaps)**

- No coordinator-agent / "Mayor" pattern. The user is the integration point.
- No first-class agent health monitoring (no Witness/Deacon/Boot). Agents that wedge or
  silently fail aren't surfaced as such.
- No merge queue. Concurrent PRs from many agents land in unspecified order via plain CI.
- No "lightweight, named, composable role" notion — XPrompts are workflows, not personae you
  attach to a polecat for its whole life.
- No landing/triage queue equivalent to the Refinery for finished but unmerged work.
- Notification/state code has hit production-style consistency issues (the
  `dismiss_agent_completions` ACE failure observed last run) that a SQL-backed canonical store
  like Dolt would side-step.

**Gas Town strengths SASE could selectively borrow**

- Mayor-style "always-on conversational coordinator" agent.
- Witness/Deacon/Boot triad for liveness and recovery.
- Bors-style Refinery for batch-then-bisect merging across parallel agent PRs.
- Tiered agent-provider contract (Tier 0 = keystroke injection, Tier 1 = JSON preset,
  Tier 2 = hooks, Tier 3 = native API).
- Explicit "role" abstraction merged base → role → rig+role.
- Centralized SQL store as an alternative to scattered files for state that's *not* meant to
  be human-edited (notifications, agent health, run history).

**Gas Town weaknesses (where SASE is already ahead)**

- No ChangeSpec-equivalent: PR-level narrative lives entirely on the forge.
- Tmux dependency is a real coupling; tmux 3.0+ assumed.
- Dolt + Beads + tmux + Go-binary stack is heavier to set up than SASE's `just install`.
- Single-developer ergonomics (Textual TUI, nvim plugin, mobile notifiers) are less developed.
- Active-but-recent: v1.0 was April 2026 (see §7 caveat), and the "Clown Show" name reflects
  real instability of the Mayor/Deacon during the first three months.

## 6. Concrete recommendations for SASE

Ordered by leverage, not by effort.

1. **Coordinator-agent prototype.** Run an Opus-class agent permanently subscribed to ACE state
   (open ChangeSpecs, recent agent transcripts, hook history). Expose a Telegram/GChat chat to
   it. This is the Mayor pattern, scoped to one developer. Start as an xprompt + long-lived
   AXE agent, no schema changes needed.
2. **Agent health subsystem.** Add a Witness-style hookspec firing on heartbeat / silent stall /
   hook-failure, surfaced as a new ACE tab. Many wedged-agent reports today require eyeballing
   the Agents tab; a "dead/stale/blocked" status would be cheap.
3. **Lightweight roles on top of XPrompts.** Today every agent's persona is a one-shot xprompt
   invocation. Add a "role" header that survives across xprompts (`role: reviewer`,
   `role: refactor`) and is merged with the runtime's system prompt. This is the smallest piece
   of Gas Town's role abstraction worth borrowing.
4. **Refinery-like landing queue.** A queue of "agent says PR is ready" entries with batch CI
   and bisect-on-failure. Even a Python implementation that just serializes merges and re-runs
   `just check` would catch a class of interaction bugs current per-PR CI misses.
5. **Provider-integration tier matrix.** Gas Town's Tier 0..3 model is a useful framing for
   SASE's `llm_provider/` registry: explicitly classify what each runtime supports today
   (subprocess, hook injection, session resume, native non-interactive). Surfacing this would
   make uniform-runtime invariants enforceable in code, not just policy
   (`memory/short/gotchas.md`).
6. **SQL-backed store for non-human-edited state.** Not Dolt specifically, but Gas Town's
   bet that notifications / agent health / hook history *want* to be relational is worth
   taking seriously. The notification-store/ACE test failure observed in the previous run
   suggests the file-based approach has reached an awkward middle.
7. **Beads naming hygiene.** Given Gas Town's beads have a real public footprint (and a `bd`
   CLI), SASE may want to disambiguate — either in docs ("SASE beads, not Yegge beads") or
   eventually with a different surface noun.
8. **XPrompt operations.** Multi-step XPrompts are SASE's most underused power feature; many
   workflows still live as one-shot `.md` prompt parts. A short audit pass converting common
   ChangeSpec workflows into `.yml` xprompts would let the Mayor-style coordinator drive them
   programmatically.

## 7. Caveats and unresolved items

- **Release-date ambiguity.** The Gas Town release page rendered ambiguous years in fetched
  HTML. v1.0 is dated **April 2026** on Yegge's Medium byline; v1.1 followed within weeks
  (May 7 2026 per release notes). Exact dates beyond that should be re-verified from the
  GitHub releases UI directly before citing.
- **Dolt internals** of Gas Town (schema, migration story, backup model) are not described in
  detail in the public docs; the "Clown Show" post says only that switching to Dolt ended the
  catastrophic-loss era.
- **Crew/Dogs lifecycle** is named in the architecture doc but not deeply specified publicly.
  Treat any borrowing of those primitives as speculative.
- **SASE's notification-store regression** (`dismiss_agent_completions` unknown to the Rust
  binding) showed up in the previous run's `just check`. It is independent of this note but
  worth flagging because it's exactly the kind of file/cache drift that motivates Gas Town's
  central-store approach. See `../sase-core/crates/sase_core` for the binding side.
