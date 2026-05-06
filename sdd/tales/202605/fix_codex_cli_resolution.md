---
create_time: 2026-05-05 08:43:36
status: done
prompt: sdd/prompts/202605/fix_codex_cli_resolution.md
---
# Fix Codex CLI Resolution for SASE Agents

## Context

Recent SASE notifications show a burst of `CODEX(gpt-5.5)` agents failing on May 5, 2026, all with:

```text
WorkflowExecutionError: Step 'main' failed: Error: [Errno 2] No such file or directory: 'codex'
```

The attached report for notification `63ebe299-e731-410e-ac4d-944a6a1356a4` traces the failure to
`src/sase/llm_provider/codex.py`: SASE selects the Codex provider and reaches
`subprocess.Popen(["codex", "exec", ...])`, but process creation fails before Codex starts. The workflow artifacts
confirm this affected the `recent bead-work` bead-work agents and not their source logic.

The current axe process has a usable PATH, but older/background launch paths can still have a weaker environment, and
Codex is currently the only built-in Node-style provider without an explicit `SASE_*_PATH` executable override. Gemini
already has `SASE_GEMINI_PATH`; Codex should have equivalent resolution and better diagnostics.

## Goals

1. Stop Codex agents from failing with an opaque `No such file or directory: 'codex'` when Codex is installed but PATH
   differs between the interactive shell and background agents.
2. Add an explicit, documented `SASE_CODEX_PATH` escape hatch.
3. Keep runtime behavior uniform and narrowly scoped to the Codex provider executable lookup, not the agent-launch
   machinery.
4. Cover the behavior with focused unit tests and run the repo checks after source changes.

## Proposed Implementation

1. Add a small Codex executable resolver in `src/sase/llm_provider/codex.py`.
   - Prefer `SASE_CODEX_PATH` when set.
   - Otherwise use `shutil.which("codex")`.
   - If PATH lookup fails, check `NVM_BIN/codex` when `NVM_BIN` is set, because the observed install is under NVM and
     background services commonly lose shell-initialized PATH.
   - Fall back to the bare `"codex"` command only after those checks, preserving normal system behavior.

2. Use the resolver when constructing Codex `base_args`.
   - Replace the hard-coded first argv element with the resolved command.
   - Keep all existing flags, model mapping, shadow `CODEX_HOME`, interrupt handling, and extra-args precedence
     unchanged.

3. Improve missing-binary error reporting at the provider boundary.
   - Catch `FileNotFoundError` around the Codex `Popen` call.
   - Raise a `FileNotFoundError` with a message that names `SASE_CODEX_PATH`, PATH lookup, and `NVM_BIN` fallback so the
     workflow report tells the operator exactly what to fix.
   - Do not swallow nonzero Codex exit codes; those should remain `CalledProcessError`.

4. Update documentation.
   - Add `SASE_CODEX_PATH` to the Codex CLI Integration environment table in `docs/llms.md`.
   - Add it to the general LLM Provider environment variable table in `docs/configuration.md`.

5. Add focused tests in `tests/test_llm_provider_codex.py`.
   - Assert `SASE_CODEX_PATH` becomes `cmd[0]`.
   - Assert `NVM_BIN/codex` is used when PATH lookup fails and the file exists.
   - Assert existing command construction and shadow-home tests still pass.

## Verification

1. Run the focused test file:

```bash
pytest tests/test_llm_provider_codex.py
```

2. Because this repo expects a refreshed editable install before checks in an ephemeral workspace, run:

```bash
just install
just check
```

3. Optionally, after the source fix is installed, launch a trivial Codex-backed SASE agent or retry one failed bead
   agent to confirm a new workflow no longer fails at process creation.
