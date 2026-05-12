---
create_time: 2026-05-12 11:13:29
status: done
prompt: sdd/prompts/202605/chats_status_skill_runtime_fallback.md
---
# Plan: Teach `sase_chats` / `sase_agents_status` skills to fall through to live agents and mid-run artifacts

## 1. Motivation

Two parallel agents (`o9.cdx` codex/gpt-5.5 and `o9.cld` claude/opus) received the same prompt: "review the two earlier
agents `o8.cdx` and `o8.cld` and pick a plan." `o8.cdx` and `o8.cld` were still running but had already submitted their
plans.

- `o9.cdx` (success): when `sase chats show --agent o8.cdx` failed, it pivoted to `sase agents status`, found the agents
  RUNNING, opened their workspace + artifact dirs, read the submitted plan files, and produced a justified
  recommendation. Transcript: `~/.sase/chats/202605/sase-ace_run-260512_110501.md`.
- `o9.cld` (failure): ran `sase chats list` + `sase agents status`, saw RUNNING, stopped. Dismissed `live_reply.md` as
  "not a fair basis," suggested waiting / `/loop`. Never opened any artifacts dir. Missed two stable surfaces it could
  have evaluated immediately:
  1. The `.plan` child-agent chat entries (e.g. `sase-ace_run-o8_cld_plan-260512_105805.md`) that show
     `Plan submitted for review. Plan file: ~/.sase/plans/202605/<name>.md` and would have been found by a `-q o8.cld`
     content filter on `sase chats list`.
  2. The plan files themselves under `~/.sase/plans/<YYMM>/` (after submission) and in the running agent's workspace
     `sase_<N>/sase_plan_*.md` (pre-submission). Transcript: `~/.sase/chats/202605/sase-ace_run-260512_110500.md`.

Both runtimes have identical capabilities (AGENTS.md "Uniform Agent Runtimes"), so this is a skill-content gap — the
guidance these agents read inline didn't tell them what to do when a named-agent chat lookup fails for a still-running
agent.

## 2. Root-cause gaps in the current skills

`src/sase/xprompts/skills/sase_chats.md`:

- The named-agent lookup section tells the agent: if `sase chats show --agent <name>` exits non-zero, "report that
  plainly instead of guessing." That terminates the search at the wrong place.
- No mention of `-q '<name>'` to catch `<name>.<step>` child-workflow chats (`.plan`, `.commit`, etc.) that may have
  fresh information even when the parent agent is still running.

`src/sase/xprompts/skills/sase_agents_status.md`:

- Lists `artifacts_dir` and `workspace_num` as JSON fields but doesn't describe what's inside them or when to read them.
- No guidance on the streaming-vs-stable artifact distinction.

Neither file cross-references the other, so an agent reading only one of them doesn't discover the alternate surface
when its primary lookup misses.

## 3. Design decisions and trade-offs

**Q1: Where does the streaming-vs-stable artifact guidance live — `sase_chats`, `sase_agents_status`, or both?**

Decision: **`sase_agents_status` only**, with a one-line pointer from `sase_chats`.

Rationale: Artifacts are agent-state, which is `sase_agents_status`'s domain. `sase_chats` is about _transcripts_ — once
it has handed off to the agents-status world (because the named agent is still running), the agent should be reading the
other skill, not a duplicated copy. Avoids drift, keeps each file tight.

Alternative considered: duplicate the guidance into both files for self-contained reading. Rejected because skill files
are loaded inline into agent context — duplication wastes context budget and creates a future drift hazard when the
artifact layout changes. The cross-link is cheap and explicit.

**Q2: Should `sase_chats` actively recommend `sase agents status` as a fallback, or just remove the "report plainly and
stop" advice?**

Decision: **Active recommendation, named fallback chain.** The o9.cld transcript proves passive guidance ("report
plainly") under-determines behavior — the agent followed the letter of the skill and stopped. The fallback chain should
be explicit:

1. `sase chats show --agent <name>` (named lookup, includes `<name>.<step>` child workflows like `.plan`).
2. `sase chats list -j -q '<name>'` (catches step-suffixed siblings the named lookup missed).
3. `sase agents status -a -j` filtered to `<name>` (includes recently DONE/FAILED, not just RUNNING).
4. If RUNNING: hand off to the `sase_agents_status` skill for the artifacts-dir workflow.

**Q3: How prescriptive about "stable artifacts produced mid-run"?**

Decision: Name the specific files an agent can safely treat as stable mid-run, with a short rule for the general case.
The o9.cld failure was specifically about not recognizing two of these:

- `~/.sase/plans/<YYMM>/<descriptive>.md` — once `sase plan` has submitted, the file is committed and won't be rewritten
  by the agent. The submission shows up as a `<name>.plan` chat entry whose response_snippet starts with
  `Plan submitted for review.`
- `<workspace>/sase_plan_*.md` — pre-submission draft inside the agent's workspace (`workspace_num` →
  `<repo-parent>/sase_<N>/`). Treat as draft if no submission chat entry exists yet.
- Per-step JSON under `<artifacts_dir>/prompt_step_*.json` and `workflow_state.json` — written once per step transition,
  safe to read.
- `done.json` — only exists when the agent is no longer running; if present, it is authoritative.

In contrast, `live_reply.md` is the streaming buffer and must be treated as draft. A single rule captures it: _if a
file's content is the agent's in-flight response and the agent is RUNNING, treat as draft; if the file is a checkpoint,
submission, or step output, treat as stable._

**Q4: Should we mention how to discover the workspace dir?**

Yes — `workspace_num` → `<parent-of-this-repo>/sase_<N>/` is a useful piece of glue that's currently implicit. One line.

## 4. Concrete edits

### `src/sase/xprompts/skills/sase_chats.md`

1. **Replace** the named-lookup terminal advice ("If the agent isn't found, the command exits non-zero — report that
   plainly instead of guessing.") with an ordered fallback chain (Q2 above), ending in "hand off to
   `/sase_agents_status` for the running-agent artifacts workflow."
2. **Add** one sentence in the named-lookup section pointing out that step-suffixed child chats (e.g. `<name>.plan`,
   `<name>.commit`) are separate transcript entries — and that a submitted plan appears as a `<name>.plan` chat whose
   `response_snippet` begins with `Plan submitted for review.` and names the `~/.sase/plans/<YYMM>/<file>.md` path.
3. **Tighten** the existing "If a named-agent lookup fails (artifact removed, never saved a transcript)" bullet to apply
   only after the fallback chain is exhausted.

### `src/sase/xprompts/skills/sase_agents_status.md`

1. **Expand** the implementation-notes section (or add a small "Artifacts directory" section) describing the
   `artifacts_dir` layout:
   - `live_reply.md` (streaming draft — only quote with the "in-progress" caveat)
   - `agent_meta.json` (includes `chat_path`)
   - `workflow_state.json` and `prompt_step_*.json` (stable step checkpoints)
   - `done.json` (only present when the agent has stopped; authoritative `outcome`, `response_path`, `plan_path`)
2. **Add** one sentence on `workspace_num` resolution: `<parent-of-this-repo>/sase_<N>/` — and that pre-submission plan
   drafts live at `<workspace>/sase_plan_*.md`.
3. **Add** a short "Stable vs streaming" rule (Q3 above) so an agent reading only this skill knows when mid-run reads
   are fair game.
4. **Cross-link**: add one line under "Other useful forms" pointing at `/sase_chats` for completed-agent transcripts.

## 5. Verification

1. Run `just check` from the workspace (after `just install`, per `memory/short/workspaces.md`). Must pass — there are
   no tests gating skill content, so this is a lint/format/typecheck sanity gate, but it's mandatory.
2. Re-read both edited skill files end-to-end and dry-run the o9.cld prompt against them: "given only the contents of
   these two files, would an agent now (a) try the `-q` fallback, (b) escalate to `sase agents status`, (c) recognize
   `~/.sase/plans/<YYMM>/<name>.md` and the workspace `sase_plan_*.md` as stable, (d) know that `live_reply.md` is
   draft?" All four must be yes.
3. Spot-check that the cross-link from `sase_chats` → `sase_agents_status` (and back) makes sense when each file is read
   in isolation — no orphan references, no need to read both files in order to follow either one's instructions.

## 6. Out of scope

- Any change to `sase chats` / `sase agents` CLI behavior — both skills should describe what already works.
- Restructuring frontmatter or the skill discovery mechanism.
- Adding tests targeted at skill markdown content.
- Changes to other runtimes' copies of the skill (chezmoi-managed); the source of truth here is the xprompts dir, per
  the generated-skills pipeline.

## 7. Risk and reversibility

Low risk — documentation-only edits to two skill files. Fully reversible via git. The main failure mode is bloat: if the
additions push the files past a comfortable length they cost context budget on every agent run. Mitigated by keeping
additions tight (target: each file grows by ≤ ~25 lines), using the cross-link to avoid duplication, and preferring
named-file references over prose explanation.
