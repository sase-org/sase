---
create_time: 2026-05-24 13:13:42
status: done
prompt: sdd/prompts/202605/agent_machine_commit_tags.md
---
# Plan: Add Agent and Machine Commit Tags

## Goal

Add two runtime provenance tags to every real commit created through `sase commit`:

- `AGENT=<sase agent name>`
- `MACHINE=<host name>`

The tags should be written through the same commit-description mechanism that already writes `PLAN=<plan_file_path>`.
They should apply to actual commit-producing methods (`create_commit` and `create_pull_request`) without changing
proposal semantics, since `create_proposal` saves a diff and does not create a VCS commit.

## Current Behavior

`CommitWorkflow.run()` builds and mutates a payload before dispatching to the active VCS provider. Today:

- `handle_sase_plan()` appends `PLAN=<repo-relative plan path>` to `payload["message"]` for version-controlled SDD
  projects and stages the copied/in-repo plan path.
- `append_pr_tags()` appends configured and inherited PR metadata tags to PR commit messages.
- `build_pr_body()` reads `agent_meta.json` and adds model/agent footer text to PR bodies.
- Git commit dispatchers receive only the final payload message and use it directly in `git commit -m`.

SASE-launched agents already have enough metadata to determine the new tags:

- `extract_directives_and_write_meta()` writes `agent_meta.json` and sets `SASE_AGENT_NAME` when an agent name is
  claimed.
- `SASE_ARTIFACTS_DIR` points to the active artifact directory, so fallback lookup through `agent_meta.json["name"]` is
  available.
- The machine can be determined locally with `socket.gethostname()` at commit time.

One important interaction is PR tag inheritance: child PRs inherit trailing `KEY=VALUE` tags from their parent PR body.
`AGENT` and `MACHINE` are runtime provenance, so a child PR must never inherit stale parent values for those keys.

## Design

1. Add a small commit-tag helper module under `src/sase/workflows/commit/`.
   - Resolve `AGENT` from `SASE_AGENT_NAME` first.
   - Fall back to `SASE_ARTIFACTS_DIR/agent_meta.json` and read `name`.
   - Do not invent a fake agent name when no SASE agent name is available; manual non-agent CLI commits should not get a
     misleading `AGENT=unknown`.
   - Resolve `MACHINE` from `socket.gethostname()`, with a conservative environment fallback such as `HOSTNAME` only if
     needed.
   - Sanitize tag values to single-line strings by stripping whitespace and rejecting/removing newline characters.

2. Append/update runtime tags at the payload-message layer.
   - Add an idempotent helper that updates the trailing `KEY=VALUE` tag block rather than blindly appending duplicates.
   - Preserve existing tag lines such as `PLAN=...`, `BUG=...`, and configured PR tags.
   - Ensure runtime-owned keys (`AGENT`, `MACHINE`) are replaced with the current runtime values if they already exist
     from parent PR inheritance or a retry path.

3. Call the helper from `CommitWorkflow.run()`.
   - Keep bead and plan handling where it is today.
   - Keep precommit execution behavior unchanged.
   - For `create_pull_request`, run PR tag inheritance/config merging first, then apply runtime tags, then build the PR
     body so the PR body sees the final current `AGENT` and `MACHINE` values.
   - For `create_commit`, apply runtime tags before checkpointing and provider dispatch.
   - Skip `create_proposal`.
   - Because checkpoints store the already-mutated payload, conflict resume will replay the same tagged message without
     recomputing or duplicating tags.

4. Prevent stale runtime tags from becoming inherited metadata.
   - Either filter `AGENT` and `MACHINE` out of inherited/config PR tag maps before appending, or rely on the runtime
     tag helper to replace those keys after inheritance.
   - Prefer explicit filtering for parent-inherited tags so a missing current agent name cannot leak a parent agent name
     into a child commit.
   - If config contains `AGENT` or `MACHINE`, treat those keys as runtime-owned and let the helper own the final values.

5. Keep ChangeSpec parsing and COMMITS drawers unchanged.
   - This feature concerns commit descriptions, not the ChangeSpec `COMMITS` drawer fields.
   - Existing `strip_pr_tags()` behavior already strips trailing `KEY=VALUE` lines from ChangeSpec descriptions, so
     `AGENT` and `MACHINE` should not pollute human-readable ChangeSpec descriptions.
   - Do not add new `CommitEntry` dataclass fields unless a later product requirement asks the UI to expose these tags
     directly.

6. Update documentation.
   - Document `AGENT` and `MACHINE` alongside `PLAN` and PR tag behavior in `docs/commit_workflows.md`.
   - Add the relevant environment note for `SASE_AGENT_NAME`.
   - Mention that proposal workflows do not receive these tags because they do not create commits.

## Tests

Add focused unit and workflow tests:

- Runtime tag resolution:
  - Uses `SASE_AGENT_NAME` when set.
  - Falls back to `agent_meta.json["name"]` under `SASE_ARTIFACTS_DIR`.
  - Omits `AGENT` when no agent name exists.
  - Adds `MACHINE` using a mocked hostname.

- Message tag formatting:
  - Adds `AGENT` and `MACHINE` after an ordinary message.
  - Preserves existing `PLAN=...`, `BUG=...`, and configured tags.
  - Replaces stale `AGENT`/`MACHINE` lines without duplicating them.
  - Keeps body text intact when no existing tag block is present.

- CommitWorkflow behavior:
  - `create_commit` provider receives a message containing current `AGENT` and `MACHINE`.
  - `create_pull_request` provider receives current runtime tags after inherited/config PR tags.
  - Parent-inherited `AGENT`/`MACHINE` values are not preserved when current runtime values exist.
  - `create_proposal` does not mutate the payload with runtime commit tags.

Existing plan, PR tag, stripping, and checkpoint/resume tests should keep covering their current behavior; update
expectations only where the final message intentionally contains the new tags.

## Verification

Run focused tests first:

```bash
python -m pytest tests/test_pr_tags.py tests/test_commit_workflow_artifacts.py tests/workflows/test_commit_workflow.py
```

Then run commit-specific coverage:

```bash
python -m pytest tests/test_commit_cli.py tests/test_strip_pr_tags.py tests/test_vcs_provider_git_query.py
```

Before finalizing implementation changes in this repo, run the required repository check:

```bash
just install
just check
```
