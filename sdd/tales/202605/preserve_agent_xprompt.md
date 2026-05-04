---
create_time: 2026-05-04 16:18:16
status: done
prompt: sdd/prompts/202605/preserve_agent_xprompt.md
---
# Preserve AGENT XPROMPT After Agent Completion

## Context

The Agents tab metadata/detail panel currently renders an `AGENT XPROMPT` section from `raw_xprompt.md`, which is the
raw user prompt after alias resolution and before xprompt expansion. This section is useful because it shows the actual
user input that launched the agent, distinct from the expanded `AGENT PROMPT` sent to the runtime.

The section disappears when an agent transitions to terminal states because the renderer explicitly guards it with
`agent.status not in ("DONE", "FAILED")`. The same guard exists in both the normal prompt-panel renderer and the
file-hint renderer. The artifact itself is still written at launch time and remains readable from `raw_xprompt.md`; the
issue is display logic, not artifact persistence.

## Goal

Keep `AGENT XPROMPT` visible in the Agents tab metadata/detail panel after an agent completes or fails, as long as the
raw prompt artifact exists. The behavior should be consistent between normal detail rendering and hint-mode rendering.

## Proposed Approach

1. Update the prompt-panel rendering path in `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` so
   `AGENT XPROMPT` is rendered based on the presence of `agent.get_raw_xprompt_content()`, not on non-terminal status.

2. Apply the same rule to `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py`, preserving file-path hint
   generation inside raw prompts for completed and failed agents.

3. Keep the immediate `update_header_only()` path unchanged. That path intentionally avoids disk reads during fast j/k
   navigation and should not read `raw_xprompt.md`.

4. Add focused regression tests around the prompt-panel rendering behavior:
   - a completed `DONE` agent with `raw_xprompt.md` still renders `AGENT XPROMPT`;
   - a failed `FAILED` agent with `raw_xprompt.md` still renders `AGENT XPROMPT`;
   - hint-mode rendering follows the same behavior.

5. Avoid changing agent artifact creation, loader behavior, or the Rust core scan boundary. The artifact already exists
   and the requested change is a TUI display rule.

## Verification

Run focused tests for prompt-panel rendering first, then run the repository check command required by local
instructions:

```bash
pytest tests/ace/tui/widgets/test_agent_display.py
just check
```

Because this workspace may have stale editable dependencies, run `just install` first if `just check` or focused tests
fail due to import/environment setup rather than code behavior.
