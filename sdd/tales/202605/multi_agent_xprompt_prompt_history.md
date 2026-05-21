---
create_time: 2026-05-21 09:58:14
status: done
prompt: sdd/prompts/202605/multi_agent_xprompt_prompt_history.md
---
# Multi-Agent XPrompt Prompt History Plan

## Problem

Launching a multi-agent xprompt such as `#!research_swarm` expands the submitted prompt into multiple agent prompts
before the prompt history write happens. The history layer then sees the expanded `---`-joined prompt and records both
the expanded combined prompt and its individual segments. The user-facing history should instead retain the prompt the
user submitted, so replaying history brings back the xprompt invocation and any surrounding call-site context.

## Goals

- Save the original submitted prompt for multi-agent xprompt fanout.
- Do not save the expanded per-agent prompts produced by that fanout.
- Preserve the existing launch behavior: agents should still receive the expanded segments.
- Preserve prompt history metadata, including project name, branch/workspace key, cancelled status on validation
  failure, and file-reference recording where it still reflects user-authored text.
- Cover both TUI launch and CWD/mobile launch paths, since both currently save the expanded prompt for multi-agent
  fanout.

## Current Shape

- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` parses the submitted prompt, expands multi-agent xprompts,
  joins expanded segments into `normalized_prompt`, and writes `normalized_prompt` to prompt history before launching
  the expanded segments.
- `src/sase/agent/launch_cwd.py` follows the same pattern for CWD/mobile launch: it expands to `expanded_segments`,
  joins them into `normalized_query`, writes that value to prompt history, then launches those expanded segments.
- `src/sase/history/prompt.py` currently adds segment-level history mutations for any prompt that itself contains real
  `---` multi-prompt separators. This means passing expanded text into history creates the undesired per-agent entries.

## Proposed Design

1. Keep launch fanout expansion unchanged.
   - The launcher should still expand multi-agent xprompts into per-agent segments and pass those segments to
     `launch_multi_prompt_agents`.
   - VCS/ref resolution for display name and launch context can continue using the expanded normalized text, because
     that is what the child agents will actually run.

2. Decouple "launch text" from "history text" in multi-agent fanout branches.
   - In the TUI branch, retain the original submitted prompt before expansion.
   - When `len(multi.segments) > 1`, save that original submitted prompt to history instead of `normalized_prompt`.
   - On launch-name validation failures in the same branch, save the original submitted prompt with `cancelled=True`.
   - Continue recording file references from the user-submitted prompt, not from generated child prompts.

3. Apply the same rule to `launch_agents_from_cwd`.
   - Track the original `query` before multi-agent expansion.
   - For the `len(expanded_segments) > 1` branch, save that original query in both success and validation-failure paths.
   - Continue using the expanded normalized query for VCS/context discovery and for actual agent launch.

4. Guard against future regressions with focused tests.
   - Add or update tests proving that a multi-agent xprompt launch saves the submitted invocation, not the expanded
     child prompts.
   - Include both a TUI-oriented unit path and the CWD/mobile launch path if the existing test fixtures make this
     practical.
   - Update prompt history expectations only where they directly conflict with the new product behavior. If manual
     user-authored multi-prompts are still expected to save segments, leave that behavior intact; this change targets
     generated fanout history pollution.

## Verification

- Run the focused prompt-history and multi-agent launch tests.
- Run `just install` first if needed for this workspace.
- Run `just check` before final response, per repo instructions.
