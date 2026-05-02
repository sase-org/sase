---
title: Fix Epic Creation For Google Sibling Workspaces
create_time: 2026-04-30 13:13:39
status: done
prompt: sdd/prompts/202604/epic_google_workspace_path.md
---

# Problem

Creating an epic from the plan approval panel with `E` can fail on Google/Hg workspaces when the active agent is running
in a numbered sibling workspace, for example:

```text
ValueError: '/google/src/cloud/bbugyi/bug/google3/.sase/sdd/tales/202604/missing_buyers_research.md' is not in the subpath of '/google/src/cloud/bbugyi/bug_102/google3'
```

The crash happens in `sase.axe.run_agent_exec_plan.handle_plan_marker()` while building the follow-up `.epic` prompt. In
non-version-controlled SDD mode, SDD files are intentionally written under the primary workspace's `.sase/sdd/`
directory. The current code then unconditionally tries to compute:

```python
sdd_plan_path.relative_to(Path(ctx.workspace_dir))
```

That works only when the SDD plan file is inside the current agent workspace. For Google/Hg clients, the current
workspace can be a sibling such as `bug_102/google3`, while the non-VC SDD directory is shared under the primary client
`bug/google3/.sase/sdd`. The plan file is valid, but it is not relative to `ctx.workspace_dir`, so `Path.relative_to()`
raises and the epic follow-up agent is never launched.

# Root Cause

The epic prompt construction conflates two different path cases:

1. Version-controlled SDD files live in the current workspace and can be referenced relative to `ctx.workspace_dir`.
2. Non-version-controlled SDD files live in the primary workspace's `.sase/sdd/` area and should be referenced as
   `.sase/sdd/tales/<YYYYMM>/<name>.md`, regardless of which numbered sibling workspace created the epic.

The fallback branch already intends to use `.sase/sdd/tales/<name>.md` for non-VC mode, but it is bypassed whenever
`sdd_plan_path.exists()` is true. In the failing case the path exists in the primary workspace, so the code reaches
`relative_to()` and crashes before it can fall back.

# Implementation Plan

1. Add a small helper in `src/sase/axe/run_agent_exec_plan.py` to build the plan reference for epic creation without
   throwing when the SDD file is outside the current workspace.

   The helper should:
   - Return a workspace-relative path when `version_controlled=True` and the generated SDD plan is under
     `ctx.workspace_dir`.
   - Return a `.sase/sdd/...` path when `version_controlled=False`, using the actual path relative to the SDD root so
     the YYYYMM shard is preserved.
   - Fall back to the existing legacy paths only when generation did not produce an existing SDD plan.
   - As a defensive guard, avoid propagating `ValueError` from `Path.relative_to()`.

2. Update `handle_plan_marker()` to call that helper in the `plan_result.action == "epic"` branch.

3. Add regression coverage in `tests/test_axe_run_agent_exec_plan.py` for the exact Google/Hg shape:
   - current workspace: `/.../bug_102/google3`
   - non-VC SDD root: `/.../bug/google3/.sase/sdd`
   - generated plan: `/.../bug/google3/.sase/sdd/tales/202604/missing_buyers_research.md`
   - expected `.epic` prompt includes `#bd/new_epic:.sase/sdd/tales/202604/missing_buyers_research.md`
   - no exception is raised.

4. Add or adjust focused tests for version-controlled behavior so existing Git/SASE prompts still use workspace-relative
   `plans/<YYYYMM>/<name>.md` when possible.

5. Run focused tests first:

```bash
just install
pytest tests/test_axe_run_agent_exec_plan.py tests/test_sdd.py tests/test_epic_approval.py
```

6. Run the repository check required by local memory after modifying this repo:

```bash
just check
```

# Expected Outcome

Epic creation from the plan approval panel will work from numbered Google/Hg workspaces because the epic creator
receives a usable shared SDD path instead of crashing while computing a workspace-relative path. Existing
version-controlled behavior remains unchanged.
