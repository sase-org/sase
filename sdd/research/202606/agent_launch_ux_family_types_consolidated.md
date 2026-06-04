# Agent Launch UX and Agent Family Types

Status: Consolidated research and design memo
Date: 2026-06-04

This consolidates the prior independent research from:

- `sdd/research/202606/agent_launch_ux_and_family_types.md`
- `sdd/research/202606/agent_launch_ux_family_types.md`

The request is to research a safer launch interface around xprompt-defined "Agent Family Types", a `/sase_run` skill, and user approval for SASE agent launches. No implementation was performed.

## Executive Summary

SASE has launch fanout planning, generated skills, notification pending actions, Telegram/mobile launch surfaces, and plan-chain family metadata, but it does not have a pre-launch approval boundary. Today, new detached agents can be spawned from `sase run -d`, multi-prompt fanout, Telegram free-form messages, mobile launch routes, and TUI launch paths without showing the fully expanded launch graph first.

Recommended design:

- Use xprompt/workflow metadata to declare `agent_family_type`, with at most a discovery tag such as `tags: agent_family_type`. Do not put family IDs into the existing `XPromptTag` behavioral enum.
- Treat family type as explicit launch metadata and policy input, not as hidden behavior found during ordinary xprompt expansion.
- Ship `/sase_run` as a generated skill that teaches agents to submit structured launch requests, backed by host-side `sase run` flags or a thin launch-request command. The skill is not the enforcement point.
- Add a first-class `LaunchApproval` action beside `PlanApproval`, `HITL`, and `UserQuestion`.
- Build a shared launch preview/request object after deterministic expansion and before any spawn. Use it from both `launch_agents_from_cwd()` and the TUI's parallel launch path.
- Approve multi-agent launches as one batch; govern nested fanout with bounded delegated approval rather than prompting for every child.

## Verified Current State

### XPrompt Tags Are Behavioral Lookup Handles

`src/sase/xprompt/tags.py` defines a closed `XPromptTag` enum. `parse_tags()` rejects unknown names, `get_by_tag()` resolves by catalog precedence, and `get_by_tag_strict()` raises if more than one workflow has the same tag. Current tags include `vcs`, `crs`, `fix_hook`, `rollover`, `mentor`, `commit`, `propose`, and bead/epic/legend workflow roles.

Docs describe tags as semantic role lookup, not arbitrary labels. `docs/xprompt.md` says tags let plugins or users override role workflows such as CRS by defining another prompt with `tags: crs`; `docs/workflow_spec.md` exposes `tags` as a top-level workflow field. Tags already affect behavior, for example `tags: vcs` replaces legacy `wraps_all`.

Implication: agent family *values* should not become enum tags such as `research`, `reviewer`, or `triage`. Many prompts may share the same family type, and ordinary embedded xprompt references must not silently change launch behavior.

### Skills Are Generated Instruction Documents

Skills are xprompt sources with `skill: true` or provider-specific `skill: [...]` front matter, sourced from `src/sase/xprompts/skills/` and rendered by `sase skills init` / `sase init skills` into provider `SKILL.md` files. Existing `/sase_plan` and `/sase_questions` skills document host commands (`sase plan`, `sase questions`) rather than enforcing behavior themselves.

The audited generated-skill memory confirms the contract: skill sources are generated, deployed through the initializer, and CLI/skill examples must stay synchronized. There is no `sase_run.md` skill today.

Implication: `/sase_run` should teach agents how to request launches safely, but host launch code must enforce preview, policy, and approval.

### Launch Flow Has Two Important Chokepoints

CLI/mobile/Telegram launch surfaces mostly converge through `src/sase/agent/launch_cwd.py::launch_agents_from_cwd()`:

- `sase run -d` is detected in `src/sase/main/query_handler/special_cases.py`, then `run_query_daemon()` calls `launch_agent_from_cwd()`, which wraps `launch_agents_from_cwd()`.
- Multi-prompt `---`, `%alt`, multi-model, and `%repeat` fanout are auto-routed to detached launch behavior.
- `launch_agents_from_cwd()` canonicalizes project aliases, expands multi-agent xprompts, normalizes default workspace refs, validates names, handles repeat/alt/model fanout, and eventually calls `launch_multi_prompt_agents()` or `execute_launch_plan()`.
- `execute_launch_plan()` iterates `LaunchFanoutPlanWire` slots and calls `spawn_agent_subprocess()` through a spawn hook.
- `spawn_agent_subprocess()` is intentionally low-level; its caller must already have resolved project, workspace, timestamp, prompt, and env.

The TUI is not fully routed through `launch_agents_from_cwd()`. It has a parallel launch path under `src/sase/ace/tui/actions/agent_workflow/` that performs similar prompt/VCS/history work, then calls `execute_launch_plan()`, `launch_multi_prompt_agents()`, or `spawn_agent_subprocess()` through a TUI spawn hook.

Implication: the approval boundary should not be bolted only onto `spawn_agent_subprocess()` or only onto `launch_agents_from_cwd()`. The durable boundary is a shared preview/approval service used by both high-level launch flows before their first `execute_launch_plan()` or multi-prompt segment loop.

### Current Approval Protocols Are Mid-Execution Gates

SASE already has three human-gate protocols:

- Plan approval writes `plan_request.json`, sends `action="PlanApproval"`, and polls `plan_response.json`.
- User questions write `question_request.json`, send `action="UserQuestion"`, and poll `question_response.json`.
- Workflow HITL writes `hitl_request.json`, sends `action="HITL"`, and polls `hitl_response.json`.

These gates pause an already-running agent or workflow. They do not approve creation of new detached agents.

The Python pending action store maps only `PlanApproval`, `HITL`, `UserQuestion`, and `memory_review`. The Rust core mobile action enum recognizes `PlanApproval`, `Hitl`, and `UserQuestion`; unknown actions are unsupported. The generic Rust `NotificationWire` already has `action: Option<String>` and string `action_data`, so the envelope can carry a new launch action, but senders, pending-action state, mobile detail, TUI modals, and Telegram callbacks need explicit support.

Auto-approval precedence is also important. Plan auto-approval checks `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`, `SASE_AGENT_AUTO_PLAN_ACTION`, `agent_meta.auto_approve_plan_action`, then `SASE_AGENT_AUTO_APPROVE` or `agent_meta.approve`. Launch approval needs analogous precedence before any blocking policy is enabled, or unattended jobs can deadlock.

### Telegram Launches First And Confirms Later

The primary `sase-telegram` checkout documents free-form text/photo/image-document/album launch. `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` is a coarse presence-based kill switch for free-form launches; callbacks and slash commands still work.

In `sase_tg_inbound.py`, `_launch_agents_with_notifications()` normalizes a prompt, calls `launch_agents_from_cwd(prompt)`, then sends one launch confirmation per result with Fork, Wait, Kill, and Retry controls. Telegram's actionable notification sets are currently `{"PlanApproval", "HITL", "UserQuestion"}`.

Implication: Telegram is the highest-risk launch surface because it is remote and currently unaudited before spawn.

### Mobile Has A Narrow Bridge And A Small Dry-Run Precedent

`docs/mobile_gateway.md` says mobile cannot supply shell commands, cwd values, environment variables, or host paths. It calls fixed JSON-over-stdin bridge operations such as `launch-text` and `launch-image`.

`src/sase/integrations/_mobile_agent_launch.py` supports `dry_run: true`, but the dry-run response only validates a single prompt/name slot today. Non-dry-run calls `launch_agents_from_cwd(prompt)`.

Implication: mobile should keep its product-shaped bridge, but its dry-run should evolve into the same multi-slot launch preview used for approval.

### "Family" Is Already Overloaded

The prior memo `sdd/research/202606/configurable_agent_families_consolidated.md` covers the existing vertical plan-chain family:

- `agent_family`: base name for plan/question/feedback/code handoff.
- `agent_family_role`: role in that lifecycle, such as `plan`, `q`, `code`, `epic`, `legend`, `commit`, or `feedback`.
- `role_suffix`: suffixes like `--plan`, `--q`, `--code`, `--epic`, `--legend`, `--commit`, and numeric feedback rounds.
- `plan_chain_root`: root marker for plan-chain status mirroring.

The Rust scanner wire already carries those fields, and the TUI uses them for grouping and status overrides. Separately, SASE has user-managed `tag` stored in `~/.sase/agent_tags.json` and saved agent groups in the archive wire. Those are display/organization concepts, not launch-time family type declarations.

Implication: this memo's "Agent Family Type" should be a new horizontal classification, for example `research`, `review`, `triage`, or `refactor`, persisted as `agent_family_type`. It must remain distinct from plan-chain `agent_family` and user-managed `tag`.

## Design

### Family Types Via XPrompt/Workflow Metadata

Use xprompt/workflow definitions to declare family types, but keep the launch behavior explicit.

Recommended shape:

```yaml
name: family/research
tags: agent_family_type
family_type:
  id: research
  version: 1
  label: Research
  default_launch_policy: request
  max_fanout: 4
  roles:
    - id: scout
      display: Scout
    - id: synthesizer
      display: Synthesizer
```

The tag is only a discovery marker. The typed `family_type` block carries the family ID, version, policy defaults, role vocabulary, and validation hash. If the implementation prefers a shorter surface, `family_type: research` can be allowed first and later expanded to the object form.

Rules to avoid hidden coupling:

- Do not add arbitrary family IDs to `XPromptTag`.
- Do not let embedded xprompts mutate family type or approval policy just because they appear during expansion.
- Family type selection is an explicit launch property chosen by a CLI flag, mobile/Telegram field, `/sase_run` request, top-level launch template, or config default.
- If a top-level xprompt/workflow declares a default family type, show it in the preview. Embedded references can contribute prompt text, not hidden spawn policy.
- Discovery order can choose which `family/research` declaration wins, but the resolved family ID and source must be visible in the launch request.

Precedence should be visible:

1. Explicit launch input, such as `--family-type research` or a structured `/sase_run` request field.
2. Top-level launch xprompt/workflow declaration.
3. Project config default for the launch surface.
4. Global default.
5. No family type.

Persist additive metadata:

- `agent_family_type`
- `agent_family_type_version`
- `agent_family_type_source`
- `agent_family_type_hash`
- `agent_family_type_role` when a launch graph has typed slots
- `agent_family_launch_request_id`

Keep existing `agent_family`, `agent_family_role`, `role_suffix`, and `plan_chain_root` intact for the plan-chain lifecycle.

### Where `/sase_run` Belongs

`/sase_run` should be a combination:

- A generated skill source, likely `src/sase/xprompts/skills/sase_run.md`, with `skill: true`.
- Additive host-side launch flags or a thin launch-request command. Reasonable shapes include `sase run --family-type <id> --approval <policy>` or `sase launch request <json>`.
- Optional xprompt/workflow templates for common launch recipes.

It should not be a pure xprompt. A pure `#sase_run` expands text; it cannot enforce process-spawn policy. A skill alone is also insufficient because an agent, Telegram, mobile, or a workflow step could call raw launch paths.

The skill should instruct agents to submit structured requests instead of shelling out directly to `sase run -d` when launching sub-agents:

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

The host command owns validation, preview generation, policy resolution, notification/pending-action creation, revalidation, and final dispatch.

### Launch Preview And Approval Object

Create a shared launch request before spawning:

- `request_id`
- `source_surface`: `cli`, `tui`, `telegram`, `mobile`, `agent_skill`, or `workflow`
- requester context: user/session/agent/workflow where known
- cwd/project/project file/VCS ref/workspace context
- raw prompt and normalized prompt or prompt hashes
- family type, source, version/hash, and resolved policy
- expanded slots: prompt snippet, full prompt hash/path, launch kind, model/provider, planned name, workspace ref, wait/defer info, local xprompt sources/hashes
- fanout counts and warnings
- constraints: max slots, allowed projects/family types, depth, expiry

Suggested files:

- `launch_request.json`
- `launch_preview.md`
- `launch_response.json`

Suggested notification:

- `sender`: `launch`
- `action`: `LaunchApproval`
- `action_data`: `response_dir`, `request_id`, `source_surface`, `slot_count`
- `files`: preview markdown and/or request JSON

Start without edit-in-approval. Editing prompts inside approval would complicate hashing, audit, and Telegram/mobile UI. A reject-with-feedback path is enough for v1.

## Approval Placement

The gate must run after deterministic expansion/planning and before the first child process is spawned. It must share the normalized plan object with execution so the approved graph cannot drift.

### Direct `sase run -d`

- Preserve today's behavior for single-slot interactive local launches unless config or family policy asks for confirmation.
- For multi-slot launches (`---`, multi-agent xprompts, `%repeat`, `%alt`, multi-model), show an interactive preview and ask when policy is `ask` or the family type requires approval.
- For non-interactive launches, do not read stdin. Require an explicit auto-approve/bypass policy or create a pending `LaunchApproval` request that returns a request ID.
- Do not reuse `%approve`; it controls agent autonomy after launch, not authorization to create a process.

### TUI

The TUI has its own launch setup path, so it must call the shared preview/gate service before `execute_launch_plan()`, `launch_multi_prompt_agents()`, or low-level background spawn. For normal user-typed single launches, default can remain immediate. For multi-slot or stricter family policies, show a compact modal with the same preview fields as CLI/Telegram/mobile.

### Telegram

Default remote free-form launch should become staged approval:

1. Text/photo/document/album input builds the same prompt it builds today.
2. The launch service creates a preview request instead of spawning.
3. Telegram sends a `LaunchApproval` message with Approve and Reject buttons, plus a compact fanout summary.
4. Approval writes `launch_response.json` or invokes the shared action bridge.
5. The approved request revalidates, dispatches, then sends the existing launch confirmation with Fork/Wait/Kill/Retry controls.

`SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED` can evolve from boolean presence into a policy such as `disabled`, `request`, or `auto`. If kept as a boolean for compatibility, it should map to `disabled`; otherwise the safe default for remote free-form input is `request`.

### Mobile

Mobile should keep fixed operations:

- `dry_run` returns the shared launch preview object.
- Non-dry-run returns `status: approval_required` with a request ID when policy requires approval.
- Mobile action details learn `LaunchApproval` beside plan/HITL/question.
- Mobile never accepts shell commands, cwd, arbitrary env, project-file paths, or host paths from the client.

### Multi-Agent XPrompts And Multi-Prompt Fanout

Approve the whole graph before any slot spawns. The preview should show segment count, slot count, prompt snippets, planned names, workspace/VCS refs, model overrides, wait/defer relationships, local xprompt sources/hashes, and family type/role mapping.

All-or-nothing approval is the v1 policy. Per-slot approval can come later, but starting with partial approval would make cleanup and audit harder. Later spawn failures are still possible and should be reported as partial launch failures, not partial approvals.

### Nested Workflow Fanout

Workflow `hitl: true` is not launch approval. HITL reviews output after a step completes. Launch approval authorizes creation of new detached agents before they exist.

For ordinary YAML workflow agent steps, approval should be handled by the top-level workflow/family policy and existing workflow HITL, because those steps are part of the already-approved workflow execution. For workflow `bash`/`python`/agent steps that call `/sase_run`, `sase run -d`, or another detached-child launch path, default to approval required unless the parent launch delegated a bounded token.

A delegated token should be constrained by source, project, family type, max slots, max depth, and expiry. It can authorize a specific normalized graph or a bounded family workflow, not arbitrary future launches. Any overflow creates a new `LaunchApproval` request.

## Implementation Sequence

1. Document terminology. Reserve `agent_family_type` for launch-time horizontal classification. Keep it distinct from plan-chain `agent_family` and user-managed `tag`.

2. Extract a read-only launch preview planner. It should cover single launches, multi-prompt, multi-agent xprompts, `%repeat`, `%alt`, multi-model, planned names, wait/defer, VCS/workspace refs, known-project aliases, and local xprompts without spawning.

3. Add family-type declaration and persistence as metadata only. Parse `family_type` and optional `tags: agent_family_type`; validate names with the existing tag charset; write `agent_family_type` fields into artifacts and scanner/mobile/TUI wires. No execution behavior changes yet.

4. Add `/sase_run` and host request flags. Create the generated skill source, update skill-generation tests/docs, and add CLI/request fields such as `--family-type` and `--approval`. Keep defaults compatible until approval policy is enabled.

5. Add `LaunchApproval` pending action support. Add sender, request/response files, pending-action mapping, mobile Rust action kind/detail, TUI modal, and Telegram formatting/callback handling. Wire auto-approve precedence before any blocking behavior ships.

6. Route risky surfaces through approval first. Start with Telegram and agent-initiated `/sase_run`, then mobile, then optional TUI/CLI multi-slot confirmation. Preserve local single-slot compatibility unless config/family policy opts in.

7. Add fanout governance. Implement batch approval for multi-slot launch graphs and bounded delegation for nested child launches.

8. Move stable pure semantics toward `sase-core` after Python behavior stabilizes. Rust already owns launch fanout wire records, scanner wires, notification store, and mobile action contracts; Python should remain host for subprocesses, prompts, filesystem side effects, and UI transport.

## Risks

- Hidden coupling: Family tags that silently mutate launch behavior during embedded xprompt expansion would make prompt composition unsafe.
- Tag enum misuse: Adding many family IDs to `XPromptTag` would break its role-router shape and conflict with strict uniqueness callers.
- Chokepoint bypass: TUI and low-level spawn paths can bypass `launch_agents_from_cwd()`. The gate must be a shared launch service, not a single call-site patch.
- Preview drift: If preview and execution duplicate logic, approved graphs can differ from spawned graphs. Share the normalized plan and revalidate on approval.
- CI deadlock: Any blocking policy must honor explicit auto-approve/bypass configuration before it is enabled.
- Backward compatibility: Local users expect `sase run -d` to launch quickly. Keep direct single-slot defaults permissive.
- Remote stale state: Telegram approval requests involving staged photos/images need TTL cleanup for pending actions and downloaded files.
- Fanout amplification: Nested repeats, parallel workflow steps, and agent-initiated launches can multiply quickly. Enforce max slots/depth and log denials.
- Mobile contract churn: `LaunchApproval` changes Rust/mobile action contracts; version the wire and keep unsupported clients safe.
- Auditability: Store request IDs, source surface, family type source/hash, approver, approval time, and revalidation result so launches can be explained later.

## Recommended Defaults To Decide Before Implementation

- Local interactive single-slot `sase run -d`: keep immediate launch by default.
- Local multi-slot direct launches: show a preview when interactive; require explicit bypass or auto policy when non-interactive.
- Telegram free-form launch: default to `request` approval, with `disabled` and `auto` as explicit policies.
- `/sase_run`: require approval by default unless the parent launch delegated a bounded token.
- Nested detached child launches: consume a parent approval budget or create a new `LaunchApproval`.
