---
create_time: 2026-05-22 14:29:23
status: done
prompt: sdd/prompts/202605/tier1_audit_hardening.md
---
# Tighten the Tier 1 Agent Artifact Index Upkeep Audit

## Goal

Close the structural blind spots in `tests/test_agent_artifact_marker_write_audit.py` so future PRs cannot silently
introduce a tracked-marker mutation (or a whole-artifact-directory operation) without either calling a lifecycle helper
or carrying an explicit exemption. The audit currently passes against production code, and the Rust core already
self-heals on signature drift — this plan is preventive maintenance, not a hot-fix.

## Why Now

The recent tales `sdd/tales/202605/tier1_agent_index_upkeep_deep_audit.md`, `tier1_index_meta_staleness.md`,
`tier1_anonymous_workflow_hidden.md`, and `revive_empty_artifact_index.md` all trace back to the same family of bug: a
tracked marker file is mutated on disk but the SQLite Tier 1 index keeps a stale row until a full filesystem rescan. The
deep-audit epic added an AST audit that catches _direct_ mutations through a fixed list of call names. That list misses
three patterns:

1. **Mutation calls outside the allowlist.** Today only `open` (write mode), `dump`, `_write_json_file`, `mkstemp`,
   `remove`, `rmtree`, `unlink`, `write_text`, and `os.replace` are flagged. A future PR could write a marker via
   `Path.rename`, `os.rename`, `shutil.move`, `shutil.copy*`, `shutil.copytree`, `Path.write_bytes`, or `Path.touch` and
   the audit would not see it. No current production code follows this shape — the gap is forward-looking.
2. **Path-passing two-function pattern.** Function A constructs `artifact_dir / "running.json"` (literal in A, no
   mutation call). Function A passes the Path to helper B. Helper B mutates the file (mutation in B, no literal).
   Neither function gets flagged. Again, no current production code follows this shape, but it is a brittle invariant.
3. **Whole-artifact-directory operations.** `shutil.rmtree(artifact_dir)` or `os.rename(artifact_dir, ...)` drops or
   relocates every marker file at once. One such site exists today
   (`src/sase/agent/names/_wipe.py::_remove_artifact_dirs`) and is covered by its caller's
   `delete_agent_artifact_index_artifacts(...)` call. The audit does not enforce this invariant — a new `rmtree` of an
   artifact directory elsewhere would silently miss the lifecycle helper.

## Scope

In scope:

- Strengthen `tests/test_agent_artifact_marker_write_audit.py` with three new sub-tests / coverage extensions.
- Maintain explicit allowlists keyed by `file:function` so the audit is fail-closed on the dimensions we care about.
- A synthetic regression test that proves each new check actually catches a planted violation.

Out of scope:

- Adding lifecycle calls to existing Python code. The audit passes and Rust self-heal already covers mid-run
  `agent_meta.json` drift on the read path.
- Any changes in the `../sase-core` Rust repo. The Python audit hardening stands on its own.
- Changing the lifecycle helper API (`update_agent_artifact_index_for_marker_mutation`,
  `upsert_agent_artifact_index_artifacts`, `delete_agent_artifact_index_artifacts`,
  `sync_dismissed_agent_artifact_index`) or moving callers across the rust_core_backend_boundary.

## Design Decisions

### Why three separate sub-tests instead of one expanded mutation set

The three patterns have different signal-to-noise profiles:

- Direct mutation via more call names (pattern 1) is high-signal: existing review structure handles it cleanly.
- Whole-artifact-directory operations (pattern 3) are high-signal but operate at a different granularity (directory
  rather than file). They need a separate allowlist whose entries declare _why_ the rmtree/rename is safe (covered by
  caller, or provably not an artifact dir).
- Path-passing (pattern 2) is genuinely hard to detect statically without false positives. Treat it as a convention test
  backed by a small organically-growing allowlist rather than a broad scan.

Conflating these into one test would either over-narrow it (miss directory ops) or over-broaden it (false positives on
path-passing).

### Why an allowlist rather than blacklist

The audit is fail-closed by design: any new tracked-marker mutation site must be explicitly classified. This is the same
model the existing audit already uses, and the prior epic showed it works — reviewers see the diff adding a new entry to
`_REVIEWED_MARKER_MUTATION_CONTEXTS` and ask the right questions.

### Why not also touch the Rust core

The Rust self-heal on signature drift addresses _runtime_ staleness, not the upstream invariant that lifecycle hooks
must be called whenever a marker mutates. The two layers are complementary, not redundant: self-heal pays a cost on
every query (signature recheck plus rescan when drift is detected), so the lifecycle path remains the right primary
defense. Per the `rust_core_backend_boundary.md` litmus test, this audit is Python-side presentation/glue and stays
here.

## Implementation Plan

### 1. Extend the existing mutation vocabulary (pattern 1)

In `tests/test_agent_artifact_marker_write_audit.py`:

- Add to `_MUTATION_CALL_NAMES`: `rename` (catches both `Path.rename(...)` and `os.rename(...)`), `move`
  (`shutil.move(...)`), `copy`, `copy2`, `copyfile`, `copytree` (`shutil.copy*(...)`), `write_bytes`, `touch`.
- Update `_mutation_call_name` so attribute calls like `shutil.move(...)` and `os.rename(...)` resolve to the attribute
  name and are matched against the allowlist.
- Re-run the full audit. Expect zero new flags based on the prior grep over `src/sase`. If any do appear, add them to
  `_REVIEWED_MARKER_MUTATION_CONTEXTS` with the appropriate `lifecycle_calls`, `batched_by`, `delegated`, or `exemption`
  entry — but **do not** invent coverage; if a real gap surfaces, surface it for the implementation phase to fix.

### 2. New sub-test for whole-artifact-directory operations (pattern 3)

Add `test_artifact_directory_operation_sites_are_reviewed` to the same audit file:

- Scan `src/sase/**/*.py` for `shutil.rmtree(...)`, `shutil.move(...)`, and `os.rename(...)` calls (regardless of
  whether the function contains a tracked-marker literal — that's the whole point).
- For each call, walk up to the enclosing function; the context key is `file:function`.
- Match each context against a new `_REVIEWED_DIR_OPERATION_CONTEXTS: dict[str, DirOpReview]` allowlist with the same
  `lifecycle_calls | batched_by | delegated | exemption` shape used by `Review`.
- Initial allowlist (one-line reason for each):
  - `src/sase/agent/names/_wipe.py:_remove_artifact_dirs` — batched-by-caller via `wipe_agent_name_for_reuse`'s
    `delete_agent_artifact_index_artifacts(removed_artifacts)` call.
  - `src/sase/llm_provider/codex.py:<containing function>` — exempt (shadow home, not artifact dir).
  - `src/sase/workspace_provider/utils.py:<containing function>` — exempt (workspace checkout, not artifact dir).
  - `src/sase/axe/run_agent_exec_attempts.py:snapshot_attempt` (rmtree of `tmp_dir`) — exempt (attempts subtree only, no
    tracked marker projection).
  - `src/sase/axe/run_agent_exec_attempts.py:snapshot_attempt` (`os.rename(tmp_dir, final_dir)`) — exempt (moves the
    attempts staging dir into place, no tracked marker projection).
  - `src/sase/telemetry/cli_export_config.py:<containing function>` — exempt (telemetry output dir).
  - `src/sase/ace/tui/bgcmd.py:<containing function>` — exempt (bgcmd slot dir).
  - `src/sase/main/workspace_handler.py:<containing function>` (rmtree) — exempt (workspace dir).
  - `src/sase/main/workspace_handler.py:<containing function>` (shutil.move) — exempt (workspace dir move).
  - Atomic-write sites that use `Path.rename`, `os.replace`, or `temp_path.rename(path)` on non-tracked state files (axe
    state, registry, history, etc.) — exempt with `non-tracked state file` reasons.
- Test fails when (a) a context appears in source but is missing from the allowlist, or (b) an allowlist entry
  references a context that no longer exists in source.

### 3. New convention test for path-passing pattern (pattern 2)

Add `test_tracked_marker_path_passing_sites_are_reviewed`:

- Walk every function in `src/sase/**/*.py`.
- Detect functions that (a) construct a `Path(...) / "<tracked marker filename>"` (via `BinOp(Div)` whose right operand
  is a literal with a tracked-marker substring, or `Path("...tracked marker...")`), and (b) pass the resulting Path
  expression as a positional/keyword argument to another callable.
- Filter out callees that are clearly read-only or safe: `Path`, `str`, `os.path.*`, `open` (read mode), `read_text`,
  `read_bytes`, `is_file`, `exists`, `glob`, `iterdir`, `stat`, `lstat`, `json.load`, `json.loads`, `_read_json_object`,
  `marker_signature`, plus the lifecycle helpers themselves.
- The remaining matches form the path-passing inventory. Map each to a `_REVIEWED_PATH_PASSING_CONTEXTS` allowlist keyed
  by `file:function` with either:
  - `lifecycle_coverage`: the function (or one of its in-module callers, traversed one hop) also calls a lifecycle
    helper, or
  - `exemption`: documented reason (e.g. "passes path to dataclass constructor for later read-only use").
- Test fails when source contains a context not in the allowlist.
- This sub-test is intentionally narrower than (1) and (3): we accept that not every callee is statically resolvable, so
  the allowlist will grow as new shapes show up. The value is making the convention visible in diff review.

### 4. Synthetic regression test

Add `test_audit_catches_planted_violations`:

- Use `tmp_path` to materialize a small fake `src/sase` tree containing three synthetic files, one per pattern:
  - A function that calls `shutil.copy2(src, artifact_dir / "agent_meta.json")` with no lifecycle helper (pattern 1).
  - A function that calls `shutil.rmtree(artifact_dir)` with no lifecycle helper (pattern 3).
  - A function that builds `artifact_dir / "running.json"` and passes it to an unrecognized callee (pattern 2).
- Parametrize the audit helpers (factor `_REPO_ROOT` / `_marker_mutation_contexts` so the scan root is injectable) and
  assert each planted violation fails the corresponding sub-test.
- This is the test that proves the audit's claim — without it, we are trusting the AST plumbing on faith.

### 5. Documentation

Add a module-level docstring at the top of `tests/test_agent_artifact_marker_write_audit.py` that:

- Names the four allowlist constants (`_REVIEWED_MARKER_MUTATION_CONTEXTS`, `_REVIEWED_DIR_OPERATION_CONTEXTS`,
  `_REVIEWED_PATH_PASSING_CONTEXTS`, and the existing exemption fields).
- States the rule: every flagged context must declare lifecycle coverage or an explicit exemption.
- Names the lifecycle helpers and links to `src/sase/core/agent_artifact_index_lifecycle.py`.
- Names the eight tracked marker filename patterns.

### 6. Verification

- Run `just install` (workspace bootstrap per `memory/short/workspaces.md`).
- Run `pytest -q tests/test_agent_artifact_marker_write_audit.py` and confirm all sub-tests pass, including the new ones
  and the synthetic regression test.
- Run `just check` and confirm no other tests regress.
- Manually inspect the new allowlist entries — every `exemption` reason should be short and obviously correct for the
  next reader.

## Acceptance Criteria

- A PR that adds `shutil.move(artifact_dir / "agent_meta.json", elsewhere)` without lifecycle coverage fails
  `test_tracked_marker_mutation_sites_are_reviewed`.
- A PR that adds a new `shutil.rmtree(<some artifact dir>)` site without an allowlist entry or
  `delete_agent_artifact_index_artifacts` call fails `test_artifact_directory_operation_sites_are_reviewed`.
- A PR that adds `Path.touch()` or `Path.write_bytes()` on a tracked marker without lifecycle coverage fails
  `test_tracked_marker_mutation_sites_are_reviewed`.
- A PR that constructs `artifact_dir / "running.json"` and passes the Path to an unrecognized callee fails
  `test_tracked_marker_path_passing_sites_are_reviewed` unless the function is added to the allowlist.
- `test_audit_catches_planted_violations` passes, proving the audit machinery actually fires on planted violations.
- Existing tests and `just check` still pass with no Python production code changes.

## Risks and Mitigations

- **False positives in pattern (3) (whole-dir ops).** Several non-artifact-dir rmtree/move/rename sites exist in the
  codebase. The initial allowlist must enumerate them all. Mitigation: walk the existing `rg shutil.rmtree`,
  `rg shutil.move`, `rg os.rename` results from this plan's research and add every legitimate site upfront. Subsequent
  additions show up as test failures with a clear next step.
- **False positives in pattern (2) (path-passing).** The static analysis can't always resolve callees. Mitigation: the
  allowlist starts large enough to cover current callers and shrinks naturally as the convention is better established.
  The sub-test is the weakest of the three and should be tuned to minimize churn.
- **Allowlist drift.** The audit must reject allowlist entries pointing at functions that no longer exist, so a rename
  or delete forces an explicit update. The existing audit already does this for `_REVIEWED_MARKER_MUTATION_CONTEXTS`;
  mirror that behavior in the new sub-tests.
- **Audit performance.** Three extra full-tree AST walks per test run. The existing audit already pays this cost (~2
  seconds for the whole suite); the increase should be at most 2-3 seconds, well under the test budget.
