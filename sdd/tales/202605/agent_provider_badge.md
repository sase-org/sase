---
create_time: 2026-05-23 11:54:58
status: done
prompt: sdd/prompts/202605/agent_provider_badge.md
---
# Agent Provider Badge Metadata Plan

## Context

The Agents tab row renderer already knows how to show provider icons. It calls
`provider_emoji_badge(agent.llm_provider)`, so a missing icon means the row's `Agent` model has no usable
`llm_provider`.

The affected `@a5n` artifacts confirm that shape:

- The root plan-chain artifact at `~/.sase/projects/sase/artifacts/ace-run/20260523114303/agent_meta.json` has
  plan-chain fields but no `model`, `llm_provider`, or `vcs_provider`.
- Its active code follow-up at `~/.sase/projects/sase/artifacts/ace-run/20260523114630/agent_meta.json` has
  `model: gpt-5.5` and `llm_provider: codex`.
- The root row is displayed as `TALE APPROVED` because status override logic mirrors the active code follow-up onto the
  root family row, but it does not backfill missing provider/model metadata from that same child.

There is also a nearby merge gap in `dedup_running_vs_workflow`: when an `ace-run` RUNNING/done marker is merged into
the preferred WORKFLOW row, the code copies `model` and `vcs_provider` but omits `llm_provider`. That can produce the
same visible symptom for other rows.

## Plan

1. Preserve provider metadata in RUNNING to WORKFLOW deduplication.
   - Update `dedup_running_vs_workflow` so it copies `llm_provider` when the preferred workflow row does not already
     have one.
   - Extend the existing dedup test that already checks `model` and `vcs_provider` preservation to also cover
     `llm_provider`.

2. Backfill missing root family display metadata from the effective child.
   - In plan-chain status override logic, when a root plan workflow mirrors the newest logical child status, copy
     missing display/runtime metadata such as `model`, `llm_provider`, `vcs_provider`, `workspace_num`, and
     `workspace_dir` from that child.
   - Only fill missing parent fields. Do not overwrite explicit root metadata, so mixed-provider or historical rows with
     deliberate root metadata keep their current meaning.

3. Add a focused regression test for the `@a5n` shape.
   - Build a root plan workflow with no provider metadata and an active `-code` follow-up with `llm_provider="codex"`.
   - Run status overrides and assert the root has `TALE APPROVED` plus the copied provider/model.
   - Render the root row and assert the Codex emoji appears.

4. Verify with targeted tests first, then repository checks.
   - Run the focused tests for dedup, status override, and row rendering.
   - Because source files will change, run `just install` if needed and then `just check` per repo instructions.
