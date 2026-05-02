---
status: done
create_time: 2026-04-25 17:20:05
bead_id: sase-r
prompt: sdd/prompts/202604/epic_work_automation.md
---

# Epic Work Automation: `sase bead work <epic>` → auto-launch phase + land agents

## Background

Today, after creating an epic bead (a `plan` bead with `phase` children), the user manually drives execution:

- Runs N `#bd/next` agents (one per phase) sequenced via the `%w` (alias `%wait`) directive.
- Runs one `#bd/land_epic` agent that `%w`-waits on the last phase agent.

The hand-off between bead-creation and bead-execution is a wholly manual ritual. The required information (parent →
children, child → child dependencies) is already in the bead store, so the launch can be derived deterministically and
we can run independent phases in parallel waves rather than one strict sequence.

We will land a built-in automation: a single `sase bead work <epic_id>` command that (a) marks the epic ready, (b)
computes a phase-wave schedule from the dependency DAG, (c) pre-claims each phase bead, and (d) spawns one background
agent per phase plus a final land-epic agent.

### Today's anchors (verified during research)

- **Bead model** (`src/sase/bead/model.py`): `Issue` is a dataclass with `IssueType` ∈ {`plan`, `phase`}. Phase issues
  require `parent_id`. Dependencies are a separate table; resolved per-issue into
  `issue.dependencies: list[Dependency]`.
- **DB schema** (`src/sase/bead/db.py`): SQLite + JSONL mirror in `sdd/beads/` (VC mode) or `.sase/sdd/beads/`
  (non-VC). A `_migrate_issue_types` function already shows the migration pattern.
- **`sase bead` CLI** (`src/sase/main/parser_bead.py` + `src/sase/bead/cli.py`): 13 subcommands; `update`
  - `close` mutate state, `ready` lists open beads with no active blockers.
- **Built-in xprompts** (`src/sase/default_config.yml` lines 250–333): `bd/new_epic`, `bd/next`, `bd/land_epic`,
  `bd/review/...` already exist. They are referenced by `#bd/<name>` from prompts.
- **`%wait` / `%w` directive** (`src/sase/xprompt/directives.py`): multi-value directive that takes agent names,
  durations (`5m`), or absolute times (`1430` / `260501/1430`). Bare `%w` resolves to the most-recent named agent.
  `%name` (alias `%n`) assigns an agent name. The launcher already supports `deferred_workspace=True` for `%w`-blocked
  agents.
- **Multi-prompt** (`src/sase/agent/multi_prompt.py` + `multi_prompt_launcher.py`): a single prompt with `---` segment
  separators is parsed into N segments; each launches as a separate agent. This is exactly the orchestration substrate
  the manual workflow uses today.
- **Programmatic launch** (`src/sase/agent/launcher.py`): `launch_agent_from_cwd(query)` is the public entry point. It
  auto-detects multi-prompt and dispatches to `launch_multi_prompt_agents`.
- **XPrompt tags** (`src/sase/xprompt/tags.py`): a closed `XPromptTag` enum + `get_by_tag` / `get_by_tag_strict` lookup
  that already honours the loader's precedence chain (local > user > plugin > builtin). Adding a tag = adding an enum
  member + tagging the builtin.
- **No bead-event hook system exists.** The launch must be triggered synchronously inside the `sase bead work` handler.

## Goals

1. **`is_ready_to_work` field on epic beads.** New boolean on `plan`-type issues, default `false`, flipped to `true`
   only by `sase bead work <epic_id>`. Phase beads do not carry the field.
2. **`sase bead work <epic_id>` CLI subcommand.** Marks the epic ready, then synchronously launches a wave-scheduled
   multi-prompt that runs one agent per phase plus a final land-epic agent.
3. **Override-friendly built-in xprompts.** Three new tags — `create_epic_bead`, `work_phase_bead`, `land_epic` — bind
   to built-in xprompts that the user can replace by tagging an xprompt of their own. The built-in `bd/new_epic` content
   is updated to instruct the creating agent to run `sase bead work <epic_id>` after committing.
4. **Pre-claimed beads.** Each phase bead is pre-claimed (status → `in_progress`, assignee set to the agent name) before
   its agent spawns, and the bead ID is passed explicitly to the agent's prompt.
5. **DAG-aware parallelism.** Phase agents whose blockers are all closed/satisfied can run in the same wave; later waves
   `%w`-wait on the previous wave's agent names.

## Non-goals

- No new bead-event hook system. Automation is wired directly into the `sase bead work` handler.
- No re-architecture of the multi-prompt launcher; we use it as-is.
- No retries, resume, or "land already-running epic" support — first cut is a single-shot launch.
- No TUI changes (a "running epics" panel can come later as its own plan).

## Design

### Bead schema change (`is_ready_to_work`)

- Add `is_ready_to_work: bool = False` to `Issue` (model.py).
- Add a nullable `is_ready_to_work INTEGER NOT NULL DEFAULT 0` column to the `issues` table; extend
  `_migrate_issue_types` (or add a sibling migration) to add the column when missing — follow the existing "rebuild
  table" or `ALTER TABLE ADD COLUMN` pattern. Phase beads always store `0`; only `plan` rows are ever flipped.
- Round-trip the field through `_row_to_issue`, `create_issue`, `update_issue` (gate it: only allow on plans), and the
  JSONL serializer (`src/sase/bead/jsonl.py`).
- `BeadProject.create()` always writes `is_ready_to_work=False`. A new `BeadProject.mark_ready_to_work (epic_id)`
  mutator exists solely to flip it (validates `issue_type == PLAN`, idempotent — re-flipping an already-ready epic
  raises `AlreadyReadyError` so `sase bead work` can fail loudly). `update()` rejects this field so `sase bead update`
  can never set it.

### `sase bead work <epic_id>` — CLI surface

- Argument: positional `id` (the epic plan bead ID).
- Flags:
  - `-n, --dry-run` — print the assembled multi-prompt and the wave plan, do not launch.
  - `-y, --yes` — skip the confirmation prompt that summarises "N agents in M waves".
- Validation:
  - Epic exists, is `plan` type, is not already `is_ready_to_work=True`.
  - Has at least one open phase child.
  - Dependency graph is a DAG and references only this epic's phase children (cross-epic deps are permitted but only
    count toward wave scheduling if the blocker is also a phase of this epic; blockers outside the epic must already be
    closed, otherwise abort).
- Behaviour:
  1. Flip `is_ready_to_work` to `True` (commits to JSONL via existing `_export()` machinery).
  2. Build the wave plan + multi-prompt (see next sections).
  3. Pre-claim every open phase child: `status=in_progress`, `assignee=<chosen agent name>`.
  4. Hand the assembled prompt to `launch_agent_from_cwd(query)`. The multi-prompt path inside the launcher does the
     per-segment spawning, naming, and `%w`-deferred-workspace logic for free.
  5. Print a summary: agent names, waves, and the workspace directories returned by the launcher.

### XPromptTag expansion

Add three enum members to `XPromptTag` (`src/sase/xprompt/tags.py`):

- `create_epic_bead`
- `work_phase_bead`
- `land_epic`

Tag the existing built-ins in `default_config.yml`:

- `bd/new_epic` → `tags: [create_epic_bead]`, with content amended to instruct the agent to run `sase bead work <id>`
  after the create-and-commit step.
- `bd/land_epic` → `tags: [land_epic]` (content unchanged).
- New `bd/work_phase_bead` → `tags: [work_phase_bead]`. Content is a parameterised variant of `bd/next` that takes an
  explicit `bead_id` instead of calling `sase bead ready`:

  ```
  Can you complete the work for bead {{ bead_id }}? The bead has already been claimed for you
  (status=in_progress, assignee set). Read its description and design file, do the work, commit,
  and close the bead. Do NOT close the parent epic. Do NOT create new beads.
  ```

The handler resolves the three xprompts via `get_by_tag_strict`, so a user xprompt under `xprompts/` (or in
`~/.config/sase/sase.yml`) tagged with the matching tag automatically wins through the existing precedence chain. No new
override knob needed.

### Dependency DAG → wave plan → multi-prompt

A new module `src/sase/bead/work.py` (pure logic, easy to unit-test) exposes:

```python
@dataclass(frozen=True)
class PhaseAssignment:
    bead_id: str
    agent_name: str
    waits_on: tuple[str, ...]          # agent names this segment must %w on
    wave: int

@dataclass(frozen=True)
class EpicWorkPlan:
    epic_id: str
    waves: tuple[tuple[PhaseAssignment, ...], ...]
    land_agent_name: str
    land_waits_on: tuple[str, ...]      # all leaf phase agent names

def build_epic_work_plan(view, epic_id: str) -> EpicWorkPlan: ...
def render_multi_prompt(plan: EpicWorkPlan,
                        work_phase_xprompt: Workflow,
                        land_epic_xprompt: Workflow) -> str: ...
```

Algorithm:

1. Pull all open phase children of `epic_id` and their dependency edges.
2. Topologically partition into waves using Kahn-style layering: wave 0 is all children with no in-epic open blockers;
   wave k is all children whose blockers are all in waves < k.
3. Detect cycles → raise.
4. Generate deterministic agent names: `epic_<epic_id>_p<bead_id>` (sanitised to match the agent-name character class).
5. For each phase, `waits_on = (agent_names of in-epic blockers across earlier waves)`.
6. The land-epic agent waits on **every** leaf phase agent name (a leaf = a phase nothing else depends on within the
   epic). This matches today's manual ritual but is more precise than waiting on the "last" agent.

Rendering a multi-prompt segment for a phase:

```
%name:<agent_name>
%w:<waits_on_1>,<waits_on_2>,...     # omitted in wave 0
#bd/work_phase_bead:<bead_id>
```

Land segment:

```
%name:<land_agent_name>
%w:<leaf_1>,<leaf_2>,...
#bd/land_epic:<epic_id>
```

Segments are joined by `\n---\n`. Tag-resolved xprompt names (which may differ if the user has overridden them) are
substituted into the `#...` references so user overrides are honoured.

### Pre-claim mechanics

After the wave plan is built (and before launch):

```python
for wave in plan.waves:
    for assignment in wave:
        proj.update(assignment.bead_id,
                    status="in_progress",
                    assignee=assignment.agent_name)
```

If any update fails (bead vanished, already in_progress with a different assignee, etc.), abort and roll back the prior
updates in this run. Acceptable to reuse `BeadProject.update()` — no need for a new transactional API in v1.

### Agent runtime contract

- Each phase agent is launched in a deferred-workspace state if it has waits, otherwise in a fresh axe workspace — both
  behaviours already exist in `spawn_agent_subprocess`.
- The agent receives the bead ID directly through the rendered `#bd/work_phase_bead:<bead_id>`; no env var needed.
- The agent must NOT call `sase bead ready` or invent new beads — the built-in xprompt content makes this explicit,
  mirroring the existing `bd/next` guardrails.

## Phasing

Each phase below is sized for a single agent instance to land end-to-end. Phases are mergeable independently: 1 ships a
useful state (manual users can already mark epics ready), 2 ships a useful override mechanism, 3 ships a tested library
nobody depends on yet, 4 wires it all together.

### Phase 1 — `is_ready_to_work` field + `sase bead work` flip + create-epic prompt update

**Scope**

- Schema migration adding `is_ready_to_work` column (Issue dataclass, db.py, jsonl.py).
- `BeadProject.mark_ready_to_work(epic_id)` with validation + custom exception.
- `sase bead work <id>` parser + handler that _only_ flips the flag and prints a confirmation. (The launch wiring
  happens in Phase 4.) Document explicitly that further wiring is incoming.
- Update `bd/new_epic` content in `default_config.yml` to instruct the agent to run `sase bead work <epic_id>` after
  committing the bead-creation work.
- Tests: model round-trip, migration on a pre-column DB, `update()` rejects the field, plan-only guard, idempotency
  error, JSONL round-trip.

**Verification**

- `just check` green.
- Manual smoke: create an epic + phases, run `sase bead work <epic>`, observe the field flips and the JSONL diff is what
  you expect.

### Phase 2 — XPromptTag expansion + new built-in `bd/work_phase_bead` + tag-based lookup

**Scope**

- Add `create_epic_bead`, `work_phase_bead`, `land_epic` to `XPromptTag`.
- Tag `bd/new_epic`, `bd/land_epic` in `default_config.yml`. Add `bd/work_phase_bead` (content per the design above),
  tagged `work_phase_bead`.
- Add a small helper in `src/sase/bead/work.py` (or `src/sase/bead/xprompts.py`) that resolves the three tags via
  `get_by_tag_strict`, raising a clear error if a user has tagged two xprompts with the same tag.
- Tests: tag enum parses, three built-ins resolvable by tag, user override wins (use a fixture xprompt file).

**Verification**

- `just check` green.
- Manual smoke: drop a tagged xprompt under `xprompts/work_phase_override.md`, run the helper from a Python shell,
  confirm the override resolves.

### Phase 3 — DAG → wave plan → multi-prompt builder (pure library)

**Scope**

- Implement `build_epic_work_plan` and `render_multi_prompt` in `src/sase/bead/work.py`.
- Cycle detection, cross-epic-blocker rejection, deterministic agent naming.
- Heavy unit tests using in-memory bead fixtures (re-use `db.create_memory_db()`):
  - Linear chain (P1 → P2 → P3): three waves, land waits on P3.
  - Diamond (P1 → P2, P1 → P3, P2+P3 → P4): three waves, land waits on P4.
  - Independent fan-out (no edges): one wave, land waits on all.
  - Closed blockers don't gate a phase.
  - Cycle raises.
- Snapshot test on the rendered multi-prompt for the diamond case so the `%name`/`%w`/`#bd/...` output is locked in.

**Verification**

- `just check` green. No production caller yet.

### Phase 4 — Wire `sase bead work` to claim + launch

**Scope**

- Extend the `sase bead work` handler from Phase 1: after flipping the flag, build the plan, pre- claim each phase bead,
  render the multi-prompt, and call `launch_agent_from_cwd(query)`.
- Add `--dry-run` and `--yes` flags.
- Confirmation prompt (skippable with `-y`) summarising waves and agent count.
- On launch failure, attempt to roll back the bead claims and the `is_ready_to_work` flip; print a clear remediation
  message either way.
- Integration test that monkeypatches `launch_agent_from_cwd` and asserts:
  - The pre-claim updates land in the right order.
  - The query passed to the launcher matches the rendered multi-prompt.
  - Dry-run never calls the launcher and never mutates beads.
- Glossary entry in `memory/short/glossary.md` for "Epic work automation".

**Verification**

- `just check` green.
- Manual smoke on a throwaway epic: `sase bead work <epic> --dry-run` shows the plan, then the real run launches the
  expected number of agents and they appear in the TUI Agents tab.

## Open questions / risks

- **Cross-epic deps.** First cut aborts if a phase blocker outside the epic is still open. Worth revisiting if it bites
  in practice — could fall back to "wait until that bead closes" via a long `%w` duration, but that's brittle.
- **Bead claim rollback.** If half the pre-claims succeed and the launcher then fails, the rollback is best-effort.
  Acceptable for v1 — failure mode is "you go fix the bead statuses by hand."
- **Agent name collisions.** Deterministic names like `epic_<id>_p<id>` should be globally unique per epic, but if the
  user re-runs `sase bead work` on the same epic after a partial failure they could collide. The `AlreadyReadyError`
  from `mark_ready_to_work` blocks the obvious second-run path; for a partial-failure recovery story we'd add an
  explicit `--force-relaunch` flag in a follow-up.
- **No event hook today.** Because the only path to flip `is_ready_to_work` is `sase bead work`, the launch is bound to
  that command and we don't need a new hook subsystem. If a future caller wants to flip the flag without launching (e.g.
  importing beads from elsewhere), they'd call `BeadProject.mark_ready_to_work` directly and skip the CLI.
