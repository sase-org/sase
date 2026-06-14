# Agents Tab `,r` — Revert a Done Agent's Commits

Status: Research and design options (no implementation performed)
Date: 2026-06-14

## Request

Add a new leader-mode keymap `,r` to the **Agents** tab of the `sase ace` TUI that reverts
**all commits associated with the currently selected agent** — including the plan/prompt
files that were committed into the `sdd/` directory. The action must only be offered for
agents that are **done with their work** (accept every status that signals "done").

This memo maps the existing machinery, surfaces the central design tension, lays out the
implementation options, and ends with a recommendation.

## Executive Summary

The TUI wiring for a new `,r` action is well-trodden and low-risk: there is a clear,
copyable precedent (`,x` / `kill_and_edit`) covering keymap config, dispatch, the
selected-agent lookup, and confirmation modals.

The **hard part is the revert semantics**, and there is an important trap:

- The existing revert path (`revert_changespec()`) is a **whole-CL throwaway** — it abandons
  the PR, prunes (deletes) the branch, renames the ChangeSpec, and flips status to
  `Reverted`. It does **not** `git revert` anything, and it operates at ChangeSpec
  granularity, not agent granularity. Reusing it would *not* satisfy the request.
- Commits are linked to an agent through a **`AGENT=<name>` trailer in each commit message**,
  written by `runtime_tags.py`. This is the only reliable agent→commit link — the ChangeSpec
  `COMMITS` section stores no SHAs.
- Both code commits **and** the `sdd/` plan/prompt commits carry that `AGENT=` tag (the SDD
  ones additionally carry `TYPE=sdd`), and they are interleaved on the same branch. So a
  single discovery query (`git log --grep='^AGENT=<name>$'`) naturally finds *both* kinds of
  commits — the "including sdd/ files" requirement falls out for free.

**Recommended solution (Option D):** implement a new backend function `revert_agent_commits()`
that (1) resolves the canonical agent name, (2) finds the agent's commits via the `AGENT=`
trailer, and (3) `git revert`s them (newest→oldest, non-destructive) through the existing
`vcs_provider` abstraction, with clean conflict abort-and-report. Expose it as a CLI
subcommand and make the TUI `,r` keymap a thin caller behind a confirmation modal, gated on
the "done" status set. This matches the request literally, is non-destructive/re-revertible,
reuses the VCS abstraction, and keeps reusable logic out of the TUI.

**Rough effort:** Medium — roughly 1–2 focused days. TUI wiring is a few hours of
boilerplate; the bulk is the revert backend (name resolution, commit discovery, conflict
handling) plus tests.

---

## How the pieces work today

### 1. Leader-mode keymap wiring (the easy part)

There is a complete, copyable precedent in the `,x` ("kill and edit") action. Adding `,r`
touches the same chain:

| Step | File | Note |
|------|------|------|
| Config default | `src/sase/default_config.yml` (`leader_mode.keys`, ~L183+) | add `"revert_agent": "r"` |
| Typed defaults | `src/sase/ace/tui/keymaps/types.py` (`LeaderModeKeymaps.keys`) | add `"revert_agent": "r"` |
| Dispatch | `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` (~L164) | add `if key == leader_keys["revert_agent"]: ...` block, gated on `current_tab == "agents"` |
| Action impl | `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` | add `_revert_agent()` (mirror `_kill_and_edit_agent`, L477+) |
| Command palette | `src/sase/ace/tui/commands/catalog.py` | add to `_LEADER_LABELS` + `_LEADER_TABS` (`_AGENTS_ONLY`) |
| Footer | `src/sase/ace/tui/widgets/keybinding_footer.py` | conditional binding, shown only when selected agent is done |
| Help modal | `src/sase/ace/tui/modals/help_modal/agents_bindings.py` | document the binding |

The selected agent is retrieved by `_get_selected_agent()`
(`src/sase/ace/tui/actions/agents/_selection.py:17`), which returns the `Agent` dataclass
(`src/sase/ace/tui/models/agent.py:42`) at `self._agents[self.current_idx]`.

Confirmation modals follow the `ConfirmKillModal` pattern
(`src/sase/ace/tui/modals/confirm_kill_modal.py`) pushed via
`self.push_screen(Modal(...), on_dismiss)`. A revert is destructive, so a confirm modal
(e.g. `ConfirmRevertAgentModal` showing the agent name + commit count) is appropriate.

Two `ace/AGENTS.md` obligations apply to *any* new ace option and must not be skipped:
- **Footer convention:** a binding belongs in the footer iff its availability is sometimes
  true / sometimes false. `,r` (only for done agents) qualifies.
- **Help popup maintenance:** the `?` help content must be updated in lockstep.
- Also remember (per `memory/short/gotchas.md`) to update `default_config.yml` keymaps.

### 2. Which statuses mean "done"

The canonical "agent finished its work" set is already defined and used for dismissal:

`src/sase/ace/tui/models/agent_status.py:8` — `DISMISSABLE_STATUSES`:
```python
DISMISSABLE_STATUSES = {
    "DONE", "FAILED", "PLAN COMMITTED", "PLAN DONE",
    "TALE DONE", "PLAN REJECTED", "EPIC CREATED",
}
```
`"FAILED (RETRIED)"` is a `FAILED`-prefixed variant and buckets as `Failed`
(`src/sase/agent/status_buckets.py:88`).

**Recommendation for the gate:** use `DISMISSABLE_STATUSES` (optionally via a small
`is_revertable_agent_status()` helper). These are exactly the states where the agent has
stopped working. Decision point for the user: the **Stopped** bucket (`PLAN`, `QUESTION` —
agent paused *awaiting your input*) is arguably "not done with its work." The conservative
default is to **exclude** Stopped and use `DISMISSABLE_STATUSES`. (See Open Questions.)

### 3. How commits link to an agent

When an agent makes a real VCS commit, `apply_runtime_commit_tags()`
(`src/sase/workflows/commit/runtime_tags.py:63`) appends a trailing
`AGENT=<name>` (and `MACHINE=<host>`) tag to the commit message. The name resolves from
`SASE_AGENT_NAME`, falling back to `agent_meta.json`'s `name`
(`runtime_tags.py:32`).

Verified against this repo's history — code and SDD commits both carry the tag:
```
4537b7024 refactor(history): trim prompt facade ...        AGENT=6x
78c73749b chore: Add SDD prompt and plan for prompt_pyvision_cleanup   AGENT=6x  TYPE=sdd
f1631941e feat(prompt): polish ... (sase-4o.5)             AGENT=sase-4o.5
```

Discovery query (anchored, so `sase-4o` does **not** match `sase-4o.5`):
```bash
git log --grep='^AGENT=<name>$' -E --format='%H'
```
Verified: `^AGENT=6x$` returns the agent's code commit *and* its `sdd/` commit; `^AGENT=sase-4o$`
and `^AGENT=sase-4o\.5$` are correctly disjoint.

Important: the `AGENT=` block is written as trailing `KEY=VALUE` lines but is **not always a
clean `git` trailer** (no enforced blank-line separation), so `--format=%(trailers:key=AGENT)`
returns empty. `--grep` is the robust mechanism, not trailer parsing.

The ChangeSpec `COMMITS` section / `CommitEntry`
(`src/sase/ace/changespec/models.py:148`) stores `number/note/chat/diff/plan` references —
**no SHA** — so it cannot be the discovery source.

### 4. SDD plan/prompt commits

`sdd/` files are written by `write_sdd_files()` (`src/sase/sdd/_write.py:22`) as a
prompt+plan pair under `sdd/prompts/<YYYYMM>/` and `sdd/<kind>/<YYYYMM>/`, and committed
either via `sase commit` (`src/sase/axe/run_agent_exec_plan_sdd.py:14`) or
`commit_sdd_files()` (`src/sase/sdd/_commit.py:13`) with a `TYPE=sdd` tag and message
`chore: Add SDD prompt and plan for <name>`. Crucially these commits carry the same
`AGENT=` tag, so the discovery query above sweeps them up alongside code commits — no
special-casing of `sdd/` is required for the common path.

Caveat: `epic`/`legend` plan actions pre-commit SDD files (so `#gh` workflows can read them),
and may land on a different branch/ref than a coder agent's code commits. The revert should
search the relevant ref(s) in the agent's workspace, not assume one branch (see Risks).

### 5. Existing revert machinery (what NOT to reuse blindly)

`revert_changespec()` (`src/sase/ace/revert.py:82`) is the only "revert" today. It:
kills running processes → validates no children → renames the ChangeSpec with a suffix →
saves the diff → `provider.abandon_change()` (close PR) → `provider.prune()`
(`git branch -D`) → status → `Reverted`. It is reachable from the **ChangeSpecs** tab via the
StatusModal (`src/sase/ace/tui/actions/status.py:175`) and from `sase cl` (`cl_handler.py:186`).

This is a *destructive whole-branch* operation at ChangeSpec granularity. It does not `git
revert`, does not preserve history, and a ChangeSpec can contain commits from **multiple**
agents (original + retries + follow-ups). Using it for `,r` would over-revert and would miss
SDD commits that live outside the pruned branch.

VCS execution goes through the `vcs_provider` plugin layer
(`src/sase/vcs_provider/_base.py`, `plugins/_git_core_ops.py`) which shells out to `git`.
A new revert flow should run `git revert` through this same abstraction (there is no
`git revert` helper yet — it would be added).

### 6. The agent-name resolution gap

The TUI `Agent` dataclass has `agent_name: str | None` (`agent.py:161`) but it is only
populated for `%name`/manually-named agents — it is `None` for the common auto-named agent
(`6x`, `sase-4o`, …). The value used in the `AGENT=` tag comes from `agent_meta.json`'s
`name`. The robust resolution path is `Agent.get_artifacts_dir()` (`agent.py:508`) →
read `agent_meta.json` → `name`. This must be implemented carefully; it is the linchpin of
the whole feature.

---

## The core design tension

> "Revert the agent's commits" ≠ "revert the agent's ChangeSpec."

An agent maps to a ChangeSpec (`Agent.cl_name`), but the relationship to *commits* is
many-agents-to-one-CL. The request is explicitly **per-agent and per-commit** ("any commits …
associated with the currently selected … agent"). The only data that supports that
granularity is the `AGENT=` commit trailer. Therefore the feature is fundamentally a
**"find this agent's commits and git-revert them"** operation, distinct from the existing
ChangeSpec-level revert.

---

## Implementation options

### Option A — Reuse `revert_changespec()` keyed off the agent's ChangeSpec
Map selected agent → `cl_name` → ChangeSpec → call `revert_changespec()`.
- **Pros:** Minimal new code; reuses tested/blessed machinery (PR abandon, branch prune,
  status, process kill).
- **Cons:** Semantically wrong — reverts the *entire CL*, over-reverts when multiple agents
  share a CL; destructive branch discard, not a `git revert`; does not address `sdd/` commits
  on other refs; `,r` becomes a duplicate shortcut to existing ChangeSpecs-tab behavior.
- **Verdict:** Does not satisfy the request. Reject as the primary design (could be offered
  as a separate "revert whole CL" affordance, but that is not what was asked).

### Option B — New `git revert` by `AGENT=` tag (literal interpretation)
Resolve agent name → `git log --grep='^AGENT=<name>$'` in the agent's workspace →
`git revert --no-edit <sha>…` newest→oldest, creating revert commits.
- **Pros:** Matches the request exactly; non-destructive and re-revertible; sweeps up code +
  `sdd/` commits together; agent-granular (leaves sibling agents' commits intact).
- **Cons:** Reverting non-tip commits can hit conflicts when later commits depend on them
  (needs `git revert --abort` + clear report); must pick the right ref scope; revert commits
  appear in an open PR (may or may not be desired); no ChangeSpec bookkeeping unless added.
- **Verdict:** Correct core mechanism.

### Option C — History rewrite (drop the commits via rebase/filter)
Remove the agent's commits from the branch entirely.
- **Pros:** Clean history, no revert commits.
- **Cons:** Rewrites history — requires force-push, breaks open PRs and any shared clones;
  fails when commits aren't contiguous; interactive rebase is unavailable in agent
  environments; high blast radius.
- **Verdict:** Reject — too dangerous for pushed branches.

### Option D — Option B, packaged as reusable backend + CLI + thin TUI caller (recommended)
Option B's mechanism, but structured so the logic is not trapped in the TUI:
- New backend module, e.g. `src/sase/ace/revert_agent.py`, exposing
  `revert_agent_commits(agent_name, workspace_dir, *, console=None) -> tuple[bool, str|None]`
  mirroring the shape/return contract of `revert.py`.
- Steps: resolve canonical name → discover SHAs via `AGENT=` grep across the relevant ref(s)
  → kill the agent's running processes if any (reuse
  `kill_and_persist_all_running_processes`) → save a combined diff to `~/.sase/reverted/`
  (mirroring `revert_changespec`) → `git revert --no-edit` newest→oldest via a new
  `vcs_provider` helper → on conflict, `git revert --abort` and return a precise error →
  optionally annotate the ChangeSpec `COMMENTS`/`COMMITS` that the agent was reverted.
- New CLI subcommand (e.g. `sase cl revert-agent <name>` or under the agent command group) so
  a CLI/web/editor frontend gets identical behavior.
- TUI `,r` → confirm modal → background task calling the backend (reuse
  `_submit_background_task`, as `status.py` does for revert today).
- **Pros:** All of Option B; reusable across frontends; consistent with existing
  `revert.py` + `vcs_provider` architecture; testable without the TUI.
- **Cons:** Most surface area (backend + CLI + TUI + tests).

---

## Rust core boundary note

Per `memory/short/rust_core_backend_boundary.md`, behavior a CLI/web/editor would want to
match the TUI is "core backend logic" that ideally lives in `../sase-core/crates/sase_core`.
Reverting an agent's commits qualifies. However, the **existing precedent is Python**:
`revert_changespec()` lives in `src/sase/ace/revert.py` and all git execution is in the
Python `vcs_provider` plugins; the Rust core today owns ChangeSpec *status* state-machine and
name utilities, not raw git plumbing.

Pragmatic reading: keep git execution in the Python `vcs_provider` (consistent with today),
and put the orchestration in a Python backend module + CLI (Option D) so it is frontend-
agnostic. The genuinely portable *policy* — "which statuses are revertable" and "how an agent
maps to its commit set" — is a candidate to formalize in `sase-core` later; flag it for the
team rather than splitting it prematurely while the rest of revert/VCS lives in Python.

---

## Effort, files, and tests

**Effort: Medium (~1–2 days).** TUI wiring ≈ a few hours (copy `,x`). The backend revert
(name resolution, commit discovery, conflict handling, diff capture) plus tests is the bulk.

**Files to create / modify:**
- New: `src/sase/ace/revert_agent.py` (backend), `ConfirmRevertAgentModal`, a CLI handler.
- New helper: `git revert` in `vcs_provider` (`_base.py` + `plugins/_git_core_ops.py`).
- Modify (TUI wiring): `default_config.yml`, `keymaps/types.py`,
  `actions/agent_workflow/_leader_mode.py`, `actions/agent_workflow/_entry_points.py`,
  `commands/catalog.py`, `widgets/keybinding_footer.py`,
  `modals/help_modal/agents_bindings.py`.
- Gate helper: `src/sase/ace/tui/models/agent_status.py` (`is_revertable_agent_status`).

**Tests:** unit tests for `revert_agent_commits` (mirror `tests/test_revert.py`): no commits
found, code+SDD commits reverted, conflict → abort+error, ephemeral workspace missing, exact
vs family-name selectivity; plus a TUI action test (status gate, modal, no-selection).
Run `just check` (after `just install`) before finishing, per `build_and_run.md`.

---

## Risks & edge cases

1. **Name resolution** — `Agent.agent_name` is `None` for auto-named agents; read
   `agent_meta.json` `name` via `get_artifacts_dir()`.
2. **Family / child agents** — exact-match (`sase-4o`) excludes children (`sase-4o.5`). But a
   plan agent often makes the SDD commit while its *coder child* makes the code commits.
   Reverting only the selected agent may leave the other half behind. **User decision:** revert
   exactly the selected agent, or the whole agent family?
3. **Revert conflicts** — later commits depending on reverted ones cause conflicts; must
   `git revert --abort` and report, never leave a half-reverted tree.
4. **Ref scope** — code commits live on the feature branch; some SDD commits (epic/legend
   pre-commit, `#gh`) may be elsewhere. Decide whether to search only the current branch's
   history or additional refs in the workspace.
5. **Pushed commits / open PR** — revert commits will need pushing; surface this rather than
   silently diverging local vs remote.
6. **Ephemeral workspace gone** — `Agent.workspace_dir` may no longer exist (workspaces are
   ephemeral); validate like `revert_changespec` does and fail clearly.
7. **No commits found** — common for plan-only / failed agents; report "nothing to revert"
   instead of erroring.

## Open questions for the user

1. **Done set:** include the **Stopped** bucket (`PLAN`, `QUESTION` — awaiting your input), or
   only the finished set `DISMISSABLE_STATUSES`? (Recommend: `DISMISSABLE_STATUSES`.)
2. **Granularity:** revert exactly the selected agent's commits, or the whole agent family
   (so a plan agent's `,r` also reverts its coder child's code commits)?
3. **Mechanism:** `git revert` (non-destructive, recommended) vs. discard — confirmed
   `git revert`?
4. **Bookkeeping:** should the revert also annotate the ChangeSpec (a `COMMENTS` note /
   status touch), or only touch git?

## Recommended solution

Adopt **Option D**: a new `revert_agent_commits()` backend (Python, using the existing
`vcs_provider` for a new `git revert` helper), exposed via a `sase` CLI subcommand, with the
Agents-tab `,r` keymap as a thin caller behind a `ConfirmRevertAgentModal`, gated on
`DISMISSABLE_STATUSES`. Discover commits via the anchored `AGENT=<name>` grep (which sweeps up
both code and `sdd/` commits), revert newest→oldest, and abort+report cleanly on conflict.
This matches the request precisely, is non-destructive and re-revertible, reuses the
established revert/VCS architecture, and keeps the logic reusable beyond the TUI. Resolve the
four open questions above before implementation, as #1 and #2 change the gate and discovery
query.
