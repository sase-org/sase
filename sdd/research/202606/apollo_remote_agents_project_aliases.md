# Apollo Remote Agents And Stable Project Identity

Date: 2026-06-04
Status: research/design memo

## Question

How should SASE use Apollo to run agents on remote machines without creating duplicate project identities for the same
GitHub repository across local paths, bare repositories, and remote hosts?

This memo reads Apollo as a new execution/control-plane concept from Bryan's inbox. There is no Apollo implementation
or documented Apollo API in this repository today. The design below therefore describes the SASE-side boundary Apollo
needs to satisfy, and stages the work so it can be tested locally before real remote execution exists.

## TL;DR

SASE currently assumes a single local machine for the entire agent lifecycle: workspace checkout, workspace claim,
process spawn, command execution, provider CLI invocation, logs, artifacts, credentials, and cleanup. The workspace
provider layer resolves a VCS ref into a local `ResolvedRef`; the launch layer preclaims a local numbered workspace;
the runner process `chdir`s into a local checkout; and `RUNNING` stores local PIDs.

Remote-capable agents need a new execution boundary around launch, not a replacement for every VCS/workspace provider.
Apollo should allocate or accept a target host, materialize the provider's checkout plan on that host, start the whole
SASE runner remotely, and return a host-qualified process handle. Remoting individual shell commands from a local runner
would leak too many local assumptions through cwd, env, provider CLIs, signals, logs, and credentials.

Project aliases are useful but not sufficient by themselves. Today's aliases map short human refs such as `#gh:bob` to a
canonical SASE project name such as `#gh:bob-cli`; they do not yet define stable repository identity. To prevent duplicate
GitHub repo identities, SASE needs a canonical project identity layer: provider-normalized remote identity
(`github:owner/repo`, normalized remote URL, or a declared host-local bare repo identity), display name, aliases, and
host-local checkout paths must be separate concepts.

Recommended path:

1. Keep workspace and VCS providers responsible for ref semantics, checkout targets, and submit/review behavior.
2. Add an execution provider boundary with local and Apollo implementations.
3. Introduce canonical project identity and an alias/remote-identity index before any remote host path is trusted.
4. Add host-qualified workspace leases and process handles while the local implementation still executes exactly as it
   does today.
5. Test the remote model with two local workspace roots and a loopback Apollo adapter before adding true remote transport.

## Source Map

Primary code paths read:

- Workspace provider contract and registry:
  - `src/sase/workspace_provider/_hookspec.py`
  - `src/sase/workspace_provider/_registry.py`
  - `src/sase/workspace_provider/store.py`
  - `src/sase/workspace_provider/utils.py`
  - `src/sase/workspace_provider/registry.py`
  - `src/sase/workspace_provider/marker.py`
- Workspace plugins:
  - `src/sase/workspace_provider/plugins/bare_git_ref.py`
  - `src/sase/workspace_provider/plugins/bare_git_workspace.py`
  - `src/sase/workspace_provider/plugins/cd_workspace.py`
  - sibling `sase-github`: `src/sase_github/workspace_plugin.py`
  - sibling `sase-github`: `src/sase_github/plugin.py`
- Project aliases and lifecycle:
  - `src/sase/project_aliases.py`
  - `src/sase/main/project_handler.py`
  - `src/sase/core/project_lifecycle_wire.py`
  - `src/sase/core/project_lifecycle_facade.py`
  - `docs/project_spec.md`
  - `sdd/epics/202606/project_aliases.md`
- Agent launch and runner:
  - `src/sase/agent/launch_cwd.py`
  - `src/sase/agent/launch_executor_workspace.py`
  - `src/sase/agent/launch_spawn.py`
  - `src/sase/core/agent_launch_wire.py`
  - `src/sase/core/agent_launch_facade.py`
  - `src/sase/axe/run_agent_runner.py`
  - `src/sase/axe/run_agent_runner_setup.py`
  - `src/sase/axe/run_agent_runner_finalize.py`
  - `src/sase/axe/run_agent_phases.py`
  - `src/sase/axe/runner_utils.py`
  - `src/sase/axe/chop_agents.py`
- Running field and command execution:
  - `src/sase/running_field/_workspace.py`
  - `src/sase/running_field/_operations.py`
  - `src/sase/core/shell.py`
  - `src/sase/llm_provider/claude.py`
  - `src/sase/llm_provider/codex.py`
  - `src/sase/xprompt/workflow_executor.py`
  - `src/sase/xprompt/workflow_executor_steps_script.py`
  - `src/sase/xprompt/workflow_executor_steps_prompt.py`

Related docs and prior research:

- `docs/workspace.md`
- `docs/vcs.md`
- `docs/configuration.md`
- `sdd/research/202605/workspace_directory_layout_research.md`
- `sdd/research/202605/sibling_repos_workspace_generalization.md`
- `sdd/research/202605/same_named_github_repos.md`
- `sdd/research/202605/multi_machine_sync.md`

## Current Topology

### Workspace Providers Resolve Local Checkouts

The workspace-provider hook contract returns `ResolvedRef(project_file, project_name, primary_workspace_dir,
checkout_target, extra)`. That is a local shape:

- `project_file` is a path in the current machine's SASE home.
- `primary_workspace_dir` is a local checkout path.
- `checkout_target` is a provider-specific local checkout target.
- `extra` can carry metadata, but the current launch paths do not treat it as a stable identity layer.

`WorkspaceStore` derives and manages local checkout directories. Its managed root can be adjacent to the repo, under
XDG state, under `SASE_WORKSPACE_ROOT`, or under an absolute configured path. `ensure_workspace_checkout()` clones new
workspaces from the local primary checkout path and then restores the real `origin`.

The managed registry records:

- `checkout_dir`
- materialization
- role
- timestamps
- pinned/generation metadata

It does not record host identity, transport, remote execution handles, credential state, or a provider-normalized repo
identity.

### Running Claims Are Local Process Claims

`running_field` reserves `#0` for home/deferred work, `#1` through `#9` for old/manual compatibility, and allocates
normal agent workspaces from `#10` upward. The `RUNNING` field stores local process information: workspace number,
workflow, local PID, ChangeSpec name, and optional artifact metadata.

The launch path relies on that locality:

- non-home launches preclaim a workspace with the parent process PID;
- spawn transfers the claim to the child PID;
- the child runner releases the workspace at exit;
- chop/live-agent scanning is keyed by local PID and local process liveness.

That model cannot distinguish "PID 12345 on laptop" from "PID 12345 on desktop", and it cannot ask a remote machine to
kill, inspect, or heartbeat that process.

### Agent Launch Starts A Local Runner

`spawn_agent_subprocess()` builds an `AgentLaunchRequestWire`, passes it through the Rust launch facade, then starts a
local detached process running `sase.axe.run_agent_runner`. The prepared launch contains local argv/cwd/env deltas, and
the process handle is a local PID.

The runner then:

- reads prompt files from local disk;
- creates artifact directories under the local SASE project tree;
- changes directory into the local workspace;
- runs `prepare_workspace_if_needed()`;
- invokes provider CLIs through the local process environment;
- writes done/error markers and notifications locally;
- releases the local workspace claim.

The LLM providers are also local. Claude spawns the `claude` CLI. Codex spawns `codex exec` with a SASE-managed local
Codex home. Script workflow steps use local subprocesses. VCS cleanup/sync/checkout commands run locally.

### Project Aliases Canonicalize Human Refs, Not Repo Identity

Project aliases currently live in ProjectSpec metadata as `PROJECT_ALIASES`. The Python alias helper builds an alias map
from project records and rewrites prompt refs early, for example `#gh:bob` to `#gh:bob-cli`.

Important boundaries:

- aliases map to the canonical SASE project name;
- aliases intentionally skip owner/repo refs containing `/`;
- aliases are provider-neutral and happen at launch/xprompt boundaries;
- aliases are not a canonical remote-repository identity model.

This solves the first ergonomic problem: "I want a shorter name for this project." It does not solve: "This GitHub repo
already exists under a different SASE project name, on a different path, or on a different machine."

### GitHub Resolution Drops Owner From The Storage Key

The GitHub plugin keeps the owner in the checkout path for `#gh:owner/repo`:

```text
~/projects/github/<owner>/<repo>/
```

but it uses the repo basename as the SASE project name and ProjectSpec path:

```text
~/.sase/projects/<repo>/<repo>.sase
```

The May same-named GitHub repo research already identifies the durable fix: use an owner-aware flat canonical id such as
`owner__repo` for the project metadata key, preserve `owner/repo` as display metadata, and use aliases for short refs
only when they are unambiguous or explicitly configured.

Remote execution makes that fix mandatory rather than optional. A local path cannot be the project identity when the
same repo may be checked out under different host roots.

## What "Remote Machine" Means For SASE

A remote machine is not just another path. It is an execution host that can run the SASE child runner and provider CLIs
against a host-local checkout while the controlling SASE UI/CLI may be on another machine.

That definition breaks into six surfaces.

### 1. Workspace Allocation

Today, workspace allocation returns a number and a local checkout path. Remote-capable allocation should return a
host-qualified workspace lease:

```text
canonical_project_id
workflow_type
checkout_target
workspace_num
host_id
host_workspace_dir
lease_token
lease_epoch
materialization_generation
```

For the first remote-capable version, keep `workspace_num` globally allocated by the controlling SASE home for a
canonical project. The display can show `host_id #17`, but the coordinator still owns one `RUNNING` table and one
workspace-number namespace. This avoids two hosts both claiming `#17` for the same project while the rest of the system
still assumes global ChangeSpec/artifact lookup.

Later, if Apollo becomes a durable coordinator, SASE can move to per-host workspace numbering. That should be a later
choice because it touches UI labels, retry chains, artifact paths, and any command that asks for "workspace 17".

Workspace directories are host-local. The lease should record the remote path, but the ProjectSpec should not treat
that path as project identity. A host workspace registry can map:

```text
(host_id, canonical_project_id, workspace_num) -> host-local checkout path
```

### 2. Command Execution

The minimal coherent remote unit is the whole runner process, not individual shell commands.

Reasons:

- the runner owns cwd changes, deferred workspace claiming, dependency waits, artifact setup, and finalization;
- provider CLIs need host-local credentials and config;
- shell workflow steps assume `os.getcwd()` is the active workspace;
- signal handling, interrupts, and kill/status checks need a host-qualified process handle;
- streaming logs from a remote process is easier to reason about than remoting arbitrary nested subprocesses from a
  local runner.

Apollo should therefore start something equivalent to:

```text
python -m sase.axe.run_agent_runner ...
```

on the target host, with a host-local workspace and a host-local SASE runtime environment.

### 3. Logs

There are two kinds of logs:

- live agent output needed by TUI/revive/status;
- heavy local diagnostic logs such as `axe/logs`, lumberjack logs, perf traces, and provider debug output.

Live output should be part of the Apollo execution stream or mirrored into the controlling SASE home under the run's
artifact directory. Heavy diagnostic logs should remain host-local by default and be collected explicitly through a
support-bundle or log-pack command. This matches the May multi-machine sync recommendation to avoid syncing high-churn
or huge runtime logs.

The live-agent model should stop depending on "tail this local file and check this local PID." It needs a process handle:

```text
run_id
host_id
remote_pid or provider_process_id
started_at
last_heartbeat_at
artifact_root
log_stream_id
```

### 4. Artifacts

Artifacts are user-facing run records and should converge back to the controlling SASE project tree. The remote runner
can write artifacts locally first, but Apollo should mirror them to the control host or to an object store with a local
index.

The artifact identity should be independent of the host-local path:

```text
canonical_project_id
workflow_name
run_id or timestamp
host_id
workspace_num
```

Completed artifacts are mostly append-only and sync-friendly. Active artifacts need explicit ownership and heartbeat
metadata so a second host can tell the difference between running, stale, failed, and merely unsynced.

### 5. Credentials

Credentials should live on the execution host. Apollo should not copy GitHub tokens, SSH keys, Claude/Codex auth, or
provider-specific config by default.

Instead, the host scheduler should use capabilities and preflight checks:

- has SASE installed at a compatible version;
- has the required workspace provider and VCS provider available;
- can reach the canonical repo remote;
- has `git`, `gh`, `claude`, `codex`, or any other required CLI;
- has auth for the target provider;
- has enough disk and an allowed workspace root;
- has any configured sibling projects available or materializable.

This keeps secret scope clear: "the agent ran on host X using host X's credentials." If credential forwarding is ever
needed, it should be a deliberate Apollo feature with audit logs and a narrow lifetime, not an implicit SASE side effect.

### 6. Synchronization

There are three different sync problems:

1. Project source code.
2. SASE control state.
3. Run artifacts and logs.

Project source code should sync through the real VCS remote whenever possible. A remote host should materialize a GitHub
workspace by cloning/fetching `github.com/owner/repo`, not by cloning from the control machine's primary checkout path.
For local bare repos, SASE must either publish a remote accessible to the target host or mark the project as host-local
and ineligible for Apollo remote execution.

SASE control state should follow the May multi-machine sync guidance: immutable artifacts and chats can sync; runtime
locks, PID files, local logs, local workspace checkouts, and ephemeral daemon state should not. Cross-machine correctness
requires a coordinator or a single control host that owns workspace claims.

Run artifacts should be mirrored as append-mostly records. Active artifact state needs a lease/heartbeat so stale remote
runs are visible instead of silently becoming local zombie records.

## Stable Project Identity And Aliases

Remote execution requires SASE to separate four concepts that are currently often conflated:

| Concept | Meaning | Example |
| --- | --- | --- |
| Canonical project id | Durable SASE storage key | `bbugyi200__bob-cli` |
| Provider remote identity | Normalized repo identity | `github:bbugyi200/bob-cli` |
| Display name | Human label | `bbugyi200/bob-cli` or `bob-cli` when unambiguous |
| Alias | User shortcut to the canonical project | `bob` |
| Host checkout path | Per-host filesystem path | `/home/bryan/projects/github/bbugyi200/bob-cli` |

Aliases should prevent duplicate GitHub repo identities by making every human ref converge on the canonical project id,
but that only works if the resolver also indexes provider remote identities.

### Current Alias Behavior

Current project aliases:

- are stored in ProjectSpec metadata;
- rewrite prompt text before launch and xprompt expansion;
- resolve `#workflow:alias` and related forms to `#workflow:canonical-project`;
- reject collisions between aliases and real project names;
- skip refs containing `/`.

That is correct for the existing `#gh:bob -> #gh:bob-cli` use case. It is not enough for remote-capable identity because
`#gh:bbugyi200/bob-cli` bypasses alias rewriting, and the GitHub provider may still create or select project metadata
based on a local basename.

### Required Identity Contract

Each project should have one canonical identity record. For GitHub, use an owner-aware flat id as recommended by the
same-named repo research:

```text
canonical_project_id = github_project_id(owner, repo)
display_name = owner/repo
remote_identity = github:lowercase-owner/lowercase-repo
```

A ProjectSpec or adjacent lifecycle record should expose enough metadata to build an index:

```text
PROJECT_ID: bbugyi200__bob-cli
PROJECT_DISPLAY_NAME: bbugyi200/bob-cli
PROJECT_REMOTE_ID: github:bbugyi200/bob-cli
PROJECT_ALIASES: bob
```

The exact field names can change, but the distinction should not. `WORKSPACE_DIR` is a host-local convenience path; it
must not be the durable identity.

For bare Git repositories, identity depends on whether the repo has a network-reachable remote:

- if it has a canonical remote URL, normalize that URL and use it as the provider remote identity;
- if it is purely local, declare it host-local and include `host_id` in the identity, or require the user to publish it
  before remote Apollo execution;
- do not pretend two different hosts' `/home/bryan/.sase/repos/foo.git` paths are the same repo unless a shared remote
  or explicit alias says so.

### Resolver Behavior

Recommended resolver order:

1. Canonicalize explicit project aliases in the prompt, as today.
2. For provider refs with remote identity, such as `#gh:owner/repo`, normalize the remote identity and look up an
   existing ProjectSpec before creating or mutating project metadata.
3. If exactly one project has that remote identity, route to its canonical project id and use host-local workspace
   materialization for the target host.
4. If no project has that remote identity, create a ProjectSpec using the canonical provider id and persist remote
   metadata.
5. For short refs such as `#gh:repo`, first check explicit aliases, then check whether exactly one known GitHub project
   has short repo `repo`. If multiple exist, return an ambiguity error listing `owner/repo` candidates.
6. For local path refs or bare repo refs, parse the repo's remote URL. If it maps to an existing canonical identity,
   attach to that project. If it has no remote identity, keep it host-local unless the user explicitly aliases or
   publishes it.

This prevents all of these from becoming separate SASE projects:

```text
#gh:bob
#gh:bob-cli
#gh:bbugyi200/bob-cli
/home/bryan/projects/github/bbugyi200/bob-cli
/remote/dev/projects/bob-cli
```

provided they normalize to the same `PROJECT_REMOTE_ID` or alias chain.

### Migration Implications

The May same-named GitHub repo research should be treated as the identity migration base:

- use flat owner-aware ids, not nested `owner/repo` paths;
- preserve display metadata separately;
- add owner-aware `ws_get_workspace_name()` for GitHub checkouts;
- parse `remote.origin.url` rather than trusting clone paths;
- refuse migration while a legacy project has active `RUNNING` claims;
- treat completed historical artifacts as historical unless active/resumable state needs rewrite.

Remote execution adds one extra migration constraint: do not migrate by copying host-local checkout paths into global
identity fields. Paths belong in host registries. The canonical project record should say what repo it is, not where one
machine happened to clone it.

## Apollo Integration Model

Apollo should be an execution provider around agent launch. It should not be modeled as a workspace provider such as
`#apollo:foo`, and it should not duplicate GitHub, bare-git, or `cd` provider semantics.

### Boundary

The launch pipeline should become:

1. Canonicalize project aliases.
2. Resolve the workflow ref using the existing workspace provider.
3. Convert the resolved ref into a workspace materialization plan.
4. Ask an execution provider for a host-qualified workspace lease.
5. Start the runner through the execution provider.
6. Record a host-qualified process handle and artifact stream.

The local execution provider can keep using the current path:

```text
claim_next_axe_workspace -> get_workspace_directory -> spawn_agent_subprocess -> local PID
```

The Apollo execution provider should use the same higher-level launch request, but it should:

- select or accept a `host_id`;
- materialize the checkout on that host;
- create or sync the run's artifact root;
- start the runner remotely;
- return a remote handle;
- stream or mirror logs and artifacts;
- heartbeat the lease.

### Workspace Materialization Plan

Current workspace-provider hooks return local paths. Apollo needs a provider-neutral plan that can be executed on another
host. A plan could include:

```text
canonical_project_id
project_display_name
workflow_type
vcs_family
vcs_provider_name
remote_identity
clone_url or fetch_url
checkout_target
setup_workflow
primary_workspace_hint
provider_extra
```

The local adapter can derive this plan from existing `ResolvedRef` and still call `get_workspace_directory()`. The Apollo
adapter can send the plan to a remote host and let that host's workspace store choose a local path.

Some providers will not be remote-capable at first:

- `cd` workspaces are path-based and should be local-only unless Apollo has a configured path mapping or shared mount.
- local bare-git repos are local-only unless a remote URL is declared.
- GitHub is the best first true-remote provider because owner/repo already gives a network materialization source.

### Process Handles

`RUNNING` and live-agent registries should stop treating PID as the unique process id. A remote-capable handle needs at
least:

```text
run_id
host_id
workspace_num
remote_pid
execution_provider
lease_token
last_heartbeat_at
artifact_root
log_stream_id
```

The local provider can set `host_id` to the current machine id and `remote_pid` to the local PID. This makes the schema
remote-ready without changing the first execution behavior.

### Control Host Versus Remote Host State

The current runner requires local access to `project_file` and SASE home state. There are two viable staged approaches:

1. Control-owned ProjectSpec with serialized runner input.
   - The control host resolves and locks project state.
   - The remote runner receives a serialized project snapshot and emits state-change events.
   - More correct long term, but larger refactor.
2. Mirrored SASE home subset on the execution host.
   - Apollo syncs the target project file and needed config to the remote host before launch.
   - The remote runner can initially keep using existing `ProjectSpec.load(project_file)` code.
   - Simpler bridge, but must never sync local locks/PID files as if they were distributed locks.

For local staged testing, start with option 2 using separate local roots. For a durable remote design, move toward option
1 or a coordinator-owned ProjectSpec transaction model.

## Staged Architecture

### Phase 0: Document Identity And Execution Assumptions

No behavior change.

- Record that `project_name`, storage key, display name, remote identity, and checkout path are separate concepts.
- Add tests or fixtures that demonstrate the current duplicate-risk cases:
  - `#gh:owner/repo` versus `#gh:alias`;
  - same repo on two checkout paths;
  - same repo from a local checkout and a GitHub ref;
  - same basename under two GitHub owners.
- Define machine identity: stable `host_id`, display hostname, and optional Apollo host label.

### Phase 1: Local Execution Provider Boundary

Introduce the execution-provider shape while keeping local behavior unchanged.

- Add a local provider that wraps today's claim, workspace directory, spawn, and PID transfer logic.
- Add a remote-ready process handle in artifacts and/or `RUNNING`, with `host_id` populated by the local machine.
- Keep local PID support for compatibility, but make new call sites use the handle.
- Keep all tests on the current machine.

Acceptance check: existing local agent launch behavior is unchanged, but the recorded run metadata can represent
`host_id + pid` instead of just `pid`.

### Phase 2: Canonical Project Identity And Alias Index

Make identity stable before remote hosts can create duplicate records.

- Add provider remote identity metadata for GitHub projects.
- Resolve `#gh:owner/repo` through the remote-identity index before creating ProjectSpecs.
- Use explicit aliases for short names and ambiguity resolution.
- Add owner-aware GitHub workspace-name detection.
- Treat `WORKSPACE_DIR` as a host-local path, not identity.
- Keep a migration command separate from launch.

Acceptance checks:

- `#gh:bob`, `#gh:bob-cli`, and `#gh:bbugyi200/bob-cli` route to one canonical project when configured that way.
- two same-named repos under different owners create two independent project records.
- short `#gh:repo` with multiple owners fails with an ambiguity error unless an alias exists.

### Phase 3: Host-Scoped Workspace Store Simulation

Still no real remote transport.

- Create two local "hosts" with different workspace roots and machine ids.
- Materialize the same canonical project on each fake host.
- Store workspace leases as `(host_id, canonical_project_id, workspace_num)`.
- Keep the control host as the only workspace-number allocator.
- Ensure sibling repos are resolved through project identity and host materialization, not through the control host's
  absolute paths.

Acceptance checks:

- launching on fake host A and fake host B uses different checkout paths without creating duplicate ProjectSpecs;
- artifact metadata records the selected host;
- stale local PID checks do not misclassify a remote/fake-host process.

### Phase 4: Artifact And Log Mirroring

Make the artifact path remote-ready while still running on one machine.

- Let the fake remote runner write artifacts under a host-local root.
- Mirror the run directory back to the control SASE project artifact tree.
- Store the remote artifact root, mirrored artifact root, and sync status.
- Stream live output through an execution-provider interface rather than assuming a local file path.

Acceptance checks:

- the TUI/revive/status path can read mirrored artifacts;
- incomplete/stale remote runs are visible;
- heavy host diagnostic logs are not mirrored by default.

### Phase 5: Apollo Loopback Adapter

Add an Apollo adapter that still targets localhost or a local subprocess service.

- Use the real Apollo request/response shape if available.
- Start the runner through the Apollo adapter.
- Exercise host capability preflight.
- Exercise kill/status/heartbeat through Apollo instead of local PID checks.

Acceptance checks:

- a launch through the Apollo adapter produces the same completed artifact shape as the local provider;
- kill/status goes through the Apollo handle;
- local provider and Apollo-loopback provider can run side by side.

### Phase 6: True Remote Execution

Run on another machine.

- Apollo selects a remote host or honors an explicit host.
- The remote host materializes the workspace from provider remote identity.
- Credentials are checked on the remote host.
- The remote runner writes artifacts locally and mirrors/streams them back.
- The control host owns or coordinates workspace claims.

Acceptance checks:

- GitHub project launch from a clean remote host clones/fetches by `owner/repo`;
- no duplicate ProjectSpec is created for the same GitHub repo;
- completed artifacts appear on the control host with host metadata;
- remote kill/status/heartbeat works;
- local-only projects fail clearly before launch.

### Phase 7: Distributed Coordination Hardening

Only after true remote execution is useful.

- Replace local file locks and local PID assumptions with leases and fencing tokens where cross-host correctness matters.
- Add stale-lease recovery.
- Add host health and capacity scheduling.
- Add explicit credential and capability audit output.
- Add cleanup commands for abandoned remote workspaces and orphaned artifact mirrors.

This is the point where Apollo could become the same "tiny coordinator" recommended by the multi-machine sync research:
agent-name leases, workspace claims, process handles, heartbeats, and stale-run adjudication.

## Test Plan For Local-First Validation

The first useful test suite does not need a real remote machine.

- Alias and identity unit tests:
  - alias ref canonicalization still happens before launch/xprompt/artifact writes;
  - slash refs normalize through provider remote identity;
  - duplicate aliases and alias/project-name collisions are rejected;
  - same-named GitHub repos remain independent.
- Workspace materialization tests:
  - fake host A and fake host B materialize the same canonical project under different roots;
  - local bare repos without a remote are rejected for non-local execution;
  - `cd` projects require explicit local-only or path mapping behavior.
- Launch-provider tests:
  - local provider returns `host_id + pid`;
  - loopback Apollo provider returns the same process-handle shape;
  - claim transfer and release use process handles rather than raw local PIDs.
- Artifact tests:
  - remote/fake-host artifact directory mirrors to the control project artifact tree;
  - incomplete runs show `host_id`, last heartbeat, and sync status;
  - heavy diagnostic logs remain host-local.
- End-to-end local simulation:
  - run one agent through local provider and one through loopback Apollo on fake hosts;
  - both use the same canonical GitHub project id;
  - no duplicate ProjectSpec or branch map is created;
  - both completed artifacts are discoverable from the control host.

## Design Recommendations

1. Treat Apollo as an execution provider, not as a workspace provider.

   Workspace providers already know how to parse `#gh`, `#git`, and `#cd` refs. Apollo should choose where and how the
   resolved work runs.

2. Remote-run the whole SASE runner.

   Running individual commands remotely from a local runner would make cwd, env, provider auth, signal handling, and
   artifact finalization harder than starting the runner on the target host.

3. Keep workspace numbers global per canonical project for the first version.

   Add `host_id` to displays and handles, but avoid per-host workspace-number namespaces until the UI and retry model
   need it.

4. Make canonical project identity a prerequisite for true remote GitHub execution.

   Without a remote-identity index, Apollo will make the existing duplicate-project problem easier to trigger.

5. Keep credentials on the execution host.

   Apollo should schedule based on capabilities and preflight checks. Secret forwarding should be explicit future work,
   not a hidden side effect.

6. Do not sync workspace checkouts or runtime locks.

   Materialize source from VCS remotes. Mirror append-mostly artifacts. Keep local logs, PIDs, locks, and workspaces
   host-local.

7. Prefer a bridge that mirrors a minimal SASE home subset before redesigning ProjectSpec transactions.

   A serialized project snapshot is cleaner long term, but a mirrored subset lets the current runner execute remotely
   sooner. The bridge must not treat file-synced locks as distributed locks.

## Open Questions

1. What is Apollo's actual API surface?

   The SASE boundary needs host selection, command start, log streaming, status, kill, file/artifact transfer, and
   capability preflight. If Apollo only provides raw command execution, SASE must build the lease/artifact layer itself.

2. Who owns the authoritative workspace claim during remote execution?

   The recommended first version is "control host owns claims." A later Apollo coordinator could own claims with
   leases/fencing tokens.

3. How should the remote runner read ProjectSpec state?

   Mirrored ProjectSpec files are the shortest bridge. Serialized launch/project snapshots are safer long term.

4. What is the canonical identity for local-only bare repos?

   They should probably be local-only until the user publishes a remote or declares a host-local identity. Treating equal
   local path basenames on two hosts as one repo would be unsafe.

5. How should sibling repos work on remote hosts?

   Sibling resolution currently uses local paths and workspace numbers. Remote execution should resolve siblings through
   canonical project identity and host-local materialization, with path-based siblings remaining local-only unless a
   host mapping exists.

6. How much completed artifact history should migrations rewrite?

   Current research suggests completed artifacts can remain historical, while active/resumable runs need a stricter
   migration policy. Remote handles add another embedded identity to consider.

## Bottom Line

Apollo can make SASE agents remote-capable if SASE first separates "what project is this?" from "where is this checkout
on this machine?" Project aliases are the ergonomic front door, but provider-normalized project identity is the
correctness primitive. The safest architecture is a staged execution-provider boundary: local provider first, loopback
Apollo second, host-scoped workspace simulation third, then true remote execution once GitHub identity, process handles,
artifact mirroring, and credential preflight are in place.
