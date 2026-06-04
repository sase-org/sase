# Agent Launch UX and Agent Family Types

Date: 2026-06-04
Status: research and design memo
Scope: SASE xprompt model, generated skills, daemon launch flow, Telegram/mobile launch surfaces, approval flows, and existing family/group metadata. No implementation was performed.

## Executive Summary

SASE already has most of the ingredients for a safer launch interface, but they are split across launch setup, xprompt expansion, notification pending actions, and plan-chain metadata. The design should introduce a first-class launch preview/request boundary before any agent subprocess is spawned. That boundary should be shared by CLI daemon launches, TUI launches, Telegram/mobile launches, agent-initiated `/sase_run`, and nested fan-out workflows.

The key recommendation is:

- Use xprompt tags to discover "agent family type" declarations, not to hide launch behavior in arbitrary xprompt expansion.
- Back `/sase_run` with a host command that validates, previews, requests approval, and only then dispatches through the existing launch executor. The slash skill should be agent-facing instructions, not the enforcement point.
- Add a first-class `LaunchApproval` notification/pending-action protocol alongside `PlanApproval`, `HITL`, and `UserQuestion`.
- Require approval after the launch graph is expanded and planned, but before the first slot is spawned. This is especially important for Telegram, mobile, multi-agent xprompts, and nested workflow fan-out.
- Persist selected family type metadata into launch artifacts and scanner wires instead of inferring it from `%group`, xprompt names, or plan-chain suffixes.

## Current Model

### XPrompt Tags

XPrompts and workflows support a `tags` field for semantic role lookup. The current tag model is closed and enum-backed: `src/sase/xprompt/tags.py` defines `XPromptTag`, and `parse_tags()` rejects unknown tag names. Current tags include `vcs`, `crs`, `fix_hook`, `rollover`, `mentor`, commit/propose tags, and bead/epic/legend role tags.

Important current properties:

- Tags are role lookup handles, not arbitrary metadata. `get_by_tag()` searches the loaded catalog and uses discovery/override order to pick a matching workflow or xprompt.
- Docs describe tags as role-based extensibility for things like overriding CRS by defining another `tags: crs` prompt.
- Workflow YAML and markdown frontmatter both accept `tags`.
- Because the enum rejects unknown tags today, a design like `tags: family/research` or `tags: family:research` requires a model change before it can work.

Relevant sources:

- `src/sase/xprompt/tags.py`
- `src/sase/xprompt/models.py`
- `docs/xprompt.md`, "Tags"
- `docs/workflow_spec.md`, top-level `tags`

### Skill Model

The current skill model is generated from xprompt sources marked `skill: true`. The xprompt catalog exposes these entries with `is_skill: true`, and `sase skills init` renders provider-specific `SKILL.md` files. Bundled skill sources live under `src/sase/xprompts/skills/`.

The existing `/sase_plan` and `/sase_questions` skills are thin instruction layers over host commands:

- `/sase_plan` tells the agent to write a plan file and run `sase plan <file>`.
- `/sase_questions` tells the agent to run `sase questions '<json>'`.

That pattern is the right one for `/sase_run`: the skill can teach agents how to request a launch, but it cannot be the authority that enforces approval. Enforcement must live in a host command and the launch dispatcher.

Relevant sources:

- `docs/xprompt.md`, "Skill Field"
- `docs/init.md`, skills initializer
- `src/sase/xprompts/skills/sase_plan.md`
- `src/sase/xprompts/skills/sase_questions.md`
- `memory/long/generated_skills.md` via audited `sase memory read`

### Launch Flow

The main launch setup path already has a useful separation between parsing/planning and spawning, but it is not yet a complete "preview then approve" API.

For `sase run`:

- `src/sase/main/query_handler/special_cases.py` strips `-d/--daemon`.
- Direct daemon mode calls `run_query_daemon()`.
- Multi-prompt, `%alt`, and multi-model prompts auto-route to daemon mode even if `-d` was not specified.
- `src/sase/main/query_handler/_daemon.py` calls `launch_agent_from_cwd(query)` and exits after printing the first PID.

For high-level launches:

- `src/sase/agent/launch_cwd.py` is the main CWD-sensitive entry point used by CLI daemon and mobile surfaces.
- It canonicalizes project aliases, parses multi-prompt frontmatter, expands multi-agent xprompts, normalizes default workspace refs, validates names, resolves VCS/workspace context, handles `%repeat`, `%alt`, and multi-model fan-out, and eventually spawns.
- Multi-segment prompts go through `src/sase/agent/multi_prompt_launcher.py`.
- Normalized fan-out execution goes through `src/sase/agent/launch_executor.py::execute_launch_plan()`.
- Rust-backed wire records in `sase-core` model `LaunchFanoutPlanWire` and `LaunchFanoutSlotWire`.

The best approval boundary is just after launch setup has expanded and planned the complete graph, and just before any call to `execute_launch_plan()` or the multi-prompt segment loop can spawn. The current multi-prompt launcher can raise a partial-launch error after some agents already spawned, which is a strong signal that approval must happen before iterating over segments.

Relevant sources:

- `src/sase/main/query_handler/special_cases.py`
- `src/sase/main/query_handler/_daemon.py`
- `src/sase/agent/launch_cwd.py`
- `src/sase/agent/multi_agent_xprompt.py`
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/agent/launch_executor.py`
- `../sase-core/crates/sase_core/src/agent_launch/mod.rs`

### Current Approval Protocols

SASE already has three distinct approval/request protocols:

- Plan approval: `/sase_plan`/`sase plan` writes pending plan state, sends `PlanApproval`, and waits for `plan_response.json`.
- User questions: `/sase_questions`/`sase questions` writes a question request, sends `UserQuestion`, and waits for `question_response.json`.
- Workflow HITL: `hitl: true` pauses after a workflow step has produced output, sends `HITL`, and waits for `hitl_response.json`.

These protocols all use notifications and pending actions, but they are intentionally different from launch approval:

- Plan approval is about approving a plan produced by an already-running agent.
- Questions are about providing missing input to an already-running agent.
- HITL is about approving, editing, rejecting, or rerunning workflow step output after the step completes.
- Launch approval is about authorizing new agent processes before they exist.

The Python pending-action store currently maps notification actions `PlanApproval`, `HITL`, `UserQuestion`, and `memory_review`. The Rust core pending-action/mobile model recognizes `PlanApproval`, `HITL`, and `UserQuestion`. Adding launch approval should be a new first-class action, not an overload of any existing one.

Relevant sources:

- `src/sase/llm_provider/_plan_utils.py`
- `src/sase/axe/run_agent_helpers_questions.py`
- `src/sase/xprompt/workflow_hitl.py`
- `src/sase/notifications/pending_actions.py`
- `../sase-core/crates/sase_core/src/notifications/pending_actions.rs`
- `../sase-core/crates/sase_core/src/notifications/mobile.rs`

### Telegram and Mobile Launch Surfaces

Telegram is currently a remote launch surface:

- Free-form text that is not a callback response or slash command launches a new agent.
- Photos, image documents, and albums are downloaded to local files and converted into launch prompts.
- Launches call `launch_agents_from_cwd(prompt)` directly, then Telegram sends a launch confirmation with Fork/Wait/Kill/Retry controls.
- `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is the only pre-launch control. It disables free-form launches while preserving callbacks and slash commands.

That means Telegram confirms after the host has already spawned the agent. For safer launch UX, Telegram should stage a launch request and ask for approval before dispatching.

Mobile is similar but more structured:

- The mobile gateway exposes narrow bridge operations like `launch-text` and `launch-image`.
- Mobile launch code has a `dry_run` response path, then otherwise calls `launch_agents_from_cwd(prompt)`.
- The mobile docs emphasize fixed JSON-over-stdin bridge operations, not arbitrary shell commands.

The existing mobile `dry_run` shape is a good precedent for a launch preview/request object.

Relevant sources:

- `../sase-telegram/README.md`
- `../sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`
- `../sase-telegram/src/sase_telegram/inbound.py`
- `src/sase/integrations/_mobile_agent_launch.py`
- `docs/mobile_gateway.md`

### Existing Family and Group Metadata

There are several existing concepts that sound related but should remain distinct:

- Agent Family: today this mostly means plan-chain phases tied by names and suffixes like `--plan`, `--q`, `--code`, `--epic`, `--legend`, `--commit`, and feedback suffixes.
- `%group`: a user-managed tag directive, useful for display and filtering, but not a runtime family type.
- Saved agent groups: archived UI group metadata, not a launch-time behavioral family model.
- Scanner metadata: Rust scanner wire already surfaces `agent_family`, `agent_family_role`, `plan_chain_root`, and `role_suffix`.

The current plan-chain model is suffix-driven and role-specific. It is not a general "Agent Family Type" abstraction. A new family type should be explicit metadata chosen at launch and written into artifacts, rather than inferred from name shape or `%group`.

Relevant sources:

- `src/sase/plan_chain.py`
- `src/sase/axe/run_agent_helpers_artifacts.py`
- `../sase-core/crates/sase_core/src/agent_scan/wire.rs`
- `../sase-core/crates/sase_core/src/agent_group_archive/wire.rs`
- `sdd/research/202606/configurable_agent_families_consolidated.md`

## Design Goals

1. Make the launch graph visible before side effects.
2. Keep local interactive launches fast while giving remote and agent-initiated launches a clear approval gate.
3. Avoid hidden coupling where an embedded xprompt tag silently changes process-spawning behavior.
4. Preserve existing prompt/xprompt composition semantics.
5. Keep family types observable in artifacts, scanner output, Telegram/mobile/TUI previews, and SDD history.
6. Use the existing notification/pending-action architecture, but create a distinct launch action.
7. Leave workflow HITL, plan approval, and question approval as separate concepts.

## Agent Family Types via XPrompt Tags

### Recommended Interpretation

Use xprompt tags to discover family type declarations, not to encode all family behavior inside a tag.

A safe model is:

```yaml
name: family/research
tags: agent_family_type
description: Research swarm family definition
agent_family_type:
  id: research
  version: 1
  default_launch_policy: require_approval
  roles:
    - id: scout
      suffix: "--scout"
    - id: synthesizer
      suffix: "--synth"
```

This uses tags for what tags are good at: catalog discovery and override. The actual semantics are in a typed `agent_family_type` block with an explicit `id`, version, role list, defaults, and policy. Today that requires extending the xprompt/workflow model, because the current `XPromptTag` enum has no `agent_family_type` tag and the `XPrompt` dataclass does not carry arbitrary family schema.

An alternative is an extensible typed-tag system such as `tags: ["agent_family_type:research"]`, but that is a larger change to the current enum-backed tag model. It also invites hidden coupling if runtime code starts scanning all embedded tags and changing launch behavior. A single discovery tag plus explicit metadata is easier to validate and explain.

### Hidden Coupling to Avoid

The launch planner must not do this:

- Expand a prompt.
- Notice that some embedded xprompt happened to have `tags: family/research`.
- Silently change the launch family type or approval policy.

That would make composition unsafe. Users routinely embed xprompts for prompt text, and those references should not carry invisible process-spawning policy unless the launch boundary explicitly opts in.

Safer rules:

- Family type selection is an explicit launch property.
- An xprompt or workflow can define a default family type only when it is invoked as the top-level launch template or family declaration.
- Embedded xprompts can contribute prompt text, but cannot mutate launch policy unless the family type schema explicitly exposes that behavior in the launch preview.
- The final resolved family type, policy version/hash, source xprompt/workflow, and per-slot roles are shown in the launch approval preview.
- The approved request stores the exact normalized launch graph or a stable hash plus enough inputs to revalidate drift before spawning.

### Precedence

Use a visible precedence order:

1. Explicit user/host input, such as a future `--family-type research`, mobile field, Telegram command option, or agent `/sase_run` request field.
2. Top-level xprompt/workflow family declaration selected by the user, such as `#!research_swarm`.
3. Project/local config default for the launch surface.
4. Global default.
5. Fallback to no family type.

Do not let "first tag found during expansion" or discovery order decide runtime family behavior. Discovery order can pick which `family/research` declaration wins, but the selected family ID must still be explicit in the launch request and preview.

### Persistence

Add metadata fields to launch artifacts, not just prompts:

- `agent_family_type`
- `agent_family_type_version`
- `agent_family_type_source`
- `agent_family_type_hash`
- `agent_family_role`
- `agent_family_parent`
- `agent_family_policy`

The existing `agent_family`, `agent_family_role`, `plan_chain_root`, and `role_suffix` fields can remain for plan-chain compatibility. New family types should not rely on suffix inference, though they may define suffix conventions for display.

## Where `/sase_run` Belongs

`/sase_run` should be a combination:

1. A generated xprompt skill source, likely `src/sase/xprompts/skills/sase_run.md`, so agents learn the correct procedure.
2. A host command wrapper, for example `sase launch request` or `sase run --request-approval`, that owns validation, preview generation, pending-action notification, response handling, and final dispatch.
3. Optional xprompt/workflow templates for common launch families or recipes.

It should not be only a skill. Skills are instructions to the agent runtime. A skill cannot enforce host policy if an agent runs `sase run -d` directly, a Telegram message launches a prompt, or a workflow fans out into children.

The `/sase_run` skill should instruct agents to submit structured launch requests instead of shelling out to raw `sase run -d`. A command-oriented request can be strict and product-shaped:

```json
{
  "schema_version": 1,
  "prompt": "...",
  "reason": "...",
  "family_type": "research",
  "approval": "required",
  "max_slots": 4
}
```

The command should then:

- Build the same preview a human launch surface would show.
- Apply source-specific policy, such as agent-initiated launches requiring approval by default.
- Create a `LaunchApproval` pending action when approval is required.
- Dispatch through the shared launch executor only after approval.
- Write launch result metadata back to the requesting agent if it waits for completion.

The exact command shape can be decided later, but the enforcement must live below the skill layer.

## Approval Placement

### Shared Boundary

Approval should happen after all deterministic launch setup that affects the graph:

- Multi-agent xprompt expansion.
- Multi-prompt splitting.
- Default workspace ref insertion.
- Project alias canonicalization.
- VCS/workspace context resolution.
- `%repeat`, `%alt`, and `%model` fan-out planning.
- Name validation and planned-name allocation when knowable.
- Family type and role resolution.

Approval must happen before:

- Reserving irreversible external resources, where possible.
- Spawning the first subprocess.
- Claiming final workspaces in a way that leaks state on rejection.
- Writing "launched" notifications.

Workspace/name availability can change between preview and approval, so final dispatch should revalidate and either spawn the same graph or fail with a clear "request drifted" result.

### Direct `sase run -d`

For direct local `sase run -d`, use a policy matrix:

- Single-slot, local interactive, user-typed launch: keep current behavior by default, but support config/flag-driven confirmation.
- Multi-slot launch, including `---`, `%alt`, `%model`, `%repeat`, or multi-agent xprompt: show a concise launch preview and ask for confirmation in an interactive terminal.
- Non-interactive direct daemon launch: create a `LaunchApproval` pending action or require an explicit bypass flag. Do not prompt on stdin that may not exist.
- Agent-initiated shell command calling `sase run -d`: require approval unless an approved parent launch token explicitly authorizes that exact child graph.

Do not reuse `%approve` for launch approval. `%approve` currently means autonomous plan/checkpoint behavior for an agent after it starts. Launch approval is about authorizing process creation. If an override is needed, use a scoped launch flag or policy field.

### Telegram

Telegram should stage first and launch after approval:

1. Text/photo/document/media input builds a launch prompt as it does today.
2. The launcher creates a preview/request instead of calling `launch_agents_from_cwd()` immediately.
3. Telegram sends a `LaunchApproval` message with Approve/Reject buttons and a compact fan-out summary.
4. Approval callback writes `launch_response.json` or calls the shared action bridge.
5. The approved request dispatches and then sends the existing launch confirmation with Fork/Wait/Kill/Retry controls.

The existing `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` can evolve into a policy:

- `disabled`: ignore free-form launch inputs.
- `request`: stage and require approval.
- `auto`: launch immediately for trusted hosts.

The default for remote free-form Telegram launch should be `request` if this feature is introduced.

### Mobile

Mobile already has fixed launch bridge operations and `dry_run`. Extend that model:

- `dry_run` returns the same launch preview object used by CLI/TUI/Telegram.
- A non-dry-run request can return `status: approval_required` plus a request/prefix ID when policy requires approval.
- Mobile action detail should learn a `LaunchApproval` action kind, parallel to plan/HITL/question actions.
- The gateway should remain product-shaped: no mobile-supplied shell commands, cwd, arbitrary env, or host paths.

### Multi-Agent XPrompts

Approval should happen after `expand_multi_agent_xprompts()` has produced concrete segments and after nested fan-out planning has been resolved enough to count slots.

The preview should show:

- Segment count and slot count.
- Per-slot prompt snippets.
- Planned names when known.
- Workspace/VCS refs.
- Wait relationships and deferred starts.
- Model/provider overrides.
- Family type and per-role mapping.
- Local xprompt sources or hashes.

Approval should apply to the whole graph. Reject cancels all. Partial approval of individual slots can be a later feature, but starting with all-or-nothing avoids partial-launch cleanup complexity.

### Nested Workflow Fan-Out

Workflow `hitl: true` is not launch approval. HITL pauses after a step produces output. Launch approval is before a child agent or child workflow is spawned.

Nested fan-out can happen through:

- An agent using `/sase_run`.
- A workflow/bash/python step invoking launch commands.
- A workflow that resolves to standalone child agents.
- A parent launch whose approved prompt contains fan-out directives that create downstream launches.

Recommended policy:

- Agent-initiated child launches require `LaunchApproval` by default.
- Parent approval may delegate limited authority with an approval token, but the token should be constrained by source, project, family type, max slots, max depth, and expiry.
- A token should authorize a specific normalized graph or a bounded family workflow, not arbitrary future `sase run -d`.
- Nested fan-out beyond the approved bounds must create a new approval request.

## Launch Approval Object

Introduce a shared request shape. It can start as Python dataclasses mirrored into Rust wire types later, or go straight to a core wire if mobile/TUI need it immediately.

Minimum fields:

- `schema_version`
- `request_id`
- `source_surface`: `cli`, `tui`, `telegram`, `mobile`, `agent_skill`, `workflow`
- `requested_by`: optional agent name/timestamp/session
- `created_at`
- `cwd`, `project_name`, `project_file`
- `raw_prompt`
- `normalized_prompt`
- `family_type` and `family_policy`
- `slots`: prompt snippet, full prompt path or hash, launch kind, model, planned name, workspace ref, wait info, local xprompt info
- `warnings`: fan-out count, remote source, hidden prompt changes, explicit name reuse, deferred workspace, recursive fan-out
- `constraints`: max slots, allowed projects, allowed family types, expiry

Files:

- `launch_request.json`
- `launch_preview.md`
- `launch_response.json`

Notification:

- `sender`: likely `launch` or `agent-launch`
- `action`: `LaunchApproval`
- `action_data`: `response_dir`, `request_id`, `source_surface`, maybe `slot_count`
- `files`: include the markdown preview and/or JSON request

Response:

```json
{
  "action": "approve",
  "approved_at": "...",
  "approved_by": "..."
}
```

For the first version, avoid editing prompt text inside the approval response. Edits are powerful but complicate request hashes, audit, and Telegram/mobile UI. A reject-with-feedback path can come later.

## Implementation Sequence

1. Build a read-only launch preview planner.

   Extract a shared planner from current launch setup. It should return a normalized graph without spawning. Cover direct single launches, multi-prompt, multi-agent xprompts, `%repeat`, `%alt`, `%model`, workspace refs, known-project refs, name validation, and local xprompts.

2. Add `LaunchApproval` pending action support.

   Add a notification sender, pending-action mapping, response files, TUI modal/action handling, CLI interactive prompt, and Rust core/mobile action kind support. Keep it parallel to `PlanApproval`, `HITL`, and `UserQuestion`.

3. Route risky launch surfaces through preview and approval.

   Start with Telegram and agent-initiated `/sase_run`, because they are remote or delegated. Then add optional confirmation for direct CLI multi-slot daemon launches. Keep single direct local launches compatible unless config opts into confirmation.

4. Add `/sase_run` generated skill source and command wrapper.

   The skill should instruct agents to submit structured launch requests. The command wrapper should enforce approval policy and dispatch through the shared executor only after approval.

5. Add family type declaration schema.

   Add a discovery tag such as `agent_family_type` and typed metadata such as `agent_family_type: { id, version, roles, policy }`. Validate uniqueness/override behavior. Add preview rendering and artifact persistence.

6. Extend Telegram/mobile launch UX.

   Telegram should format `LaunchApproval` previews and callbacks. Mobile should expose launch approval as a first-class action detail and preserve the fixed-operation bridge model.

7. Add nested fan-out constraints.

   Implement approval tokens or request constraints for parent-approved child launches. Enforce max slots, max depth, source/project/family bounds, and expiry.

8. Move pure launch/family semantics toward `sase-core` where appropriate.

   Fan-out wire types and scanner metadata already live in Rust. Once the Python behavior is stable, core can own the stable request/preview/action wire and scanner fields.

## Risks and Open Questions

- Hidden coupling: If tags directly mutate launch policy during ordinary xprompt expansion, users will not understand why a prompt spawned a different family of agents.
- Preview drift: If preview logic duplicates launch logic, the approved graph can differ from the executed graph. The planner and executor should share the same normalized plan object.
- Partial launches: Approval inside `launch_multi_prompt_agents()` or after the first `execute_launch_plan()` call can leave already-spawned agents on rejection or failure.
- `%approve` ambiguity: Reusing `%approve` for launch approval would blur plan/checkpoint autonomy with process-spawn authorization.
- Remote trust: Telegram and mobile launch surfaces should not become arbitrary host command surfaces. Keep product-shaped requests.
- Stale approvals: Names, workspaces, files, and xprompt definitions can change while a launch waits for approval. Revalidate on approval and fail clearly on drift.
- Recursive fan-out: Multi-agent xprompt recursion is bounded today, but agent-initiated nested launch requests need max depth and max slot policy too.
- Mobile contract churn: Adding `LaunchApproval` to Rust mobile action enums and gateway routes changes contract shape. Version the wire and keep unsupported clients safe.
- Family metadata compatibility: Existing plan-chain fields and scanner filters should keep working. New family types should be additive and persisted explicitly.
- Telegram media staging: Photo/document launches need local files before preview. Stale rejected requests must clean up staged images eventually.
- Approval latency: Long-running approval waits should not hold fragile subprocesses indefinitely. Agent-side `/sase_run` may need a marker/resume model or a bounded blocking command with clear timeout semantics.

## Recommended Next Design Decision

Before implementation, decide the launch policy defaults:

- Should local interactive `sase run -d` single-slot launches remain auto-approved?
- Should all multi-slot launches require confirmation by default?
- Should Telegram default to request/approve rather than immediate launch?
- Should `/sase_run` block the requesting agent, park it via marker/resume, or submit-and-return a request ID?

My recommended default is conservative but compatible: direct local single-slot launches remain unchanged, remote and agent-initiated launches require approval, and multi-slot direct daemon launches show an interactive preview unless explicitly bypassed by a scoped launch flag.
