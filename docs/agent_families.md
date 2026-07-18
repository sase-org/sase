# Agent Clans, Families, and Tribes

SASE uses three different kinds of agent grouping:

| Concept          | Directive or naming form      | Purpose                                                              |
| ---------------- | ----------------------------- | -------------------------------------------------------------------- |
| **Agent clan**   | `%clan:<name>` / `%c:<name>`  | A named, rootless container for agents that run in parallel          |
| **Agent family** | `%n(parent, suffix)`          | A strictly sequential chain named `<family>--<suffix>`               |
| **Agent tribe**  | `%tribe:<name>` / `%t:<name>` | A user-managed label displayed with an `@` prefix, such as `@review` |

Dot-separated names also define an agent _hood_: `foo.bar` and `foo.baz` are neighbors in hood `foo`. Clans use that
namespace rule deliberately, while dotted names alone do not create clan or family membership.

## Parallel Agent Clans

An agent clan is a container, never an agent. Add the same `%clan:<name>` directive to every member segment in a
multi-agent prompt, and name every member inside the clan's hood:

```text
%name:release.build
%clan:release
Compile the release.
---
%name:release.test
%clan:release
Test the release.
---
%name:release.land
%clan:release
%wait:release.build,release.test
Publish the release after both members finish.
```

The short form is `%c:release`. Clan declarations are colon-only: parenthesized forms and member roles are not
supported. Static names and templates such as `%clan:research.@` work; segments with the same raw template in one batch
resolve to one clan generation. A later launch can join the newest existing clan generation by using its resolved name.

Clan membership is execution-neutral. It does not add waits, change launch order, choose a workspace or model, or
rewrite a member's name. Use `%wait` explicitly wherever ordering is required. `%clan` and the family-attachment form
`%n(parent, suffix)` cannot appear in the same segment.

The clan name is permanently reserved as a container name and cannot also belong to an agent. Each member must be named
`<clan>.<suffix>`; launch planning rejects an out-of-hood name before spawning it. A clan may contain ordinary agents,
workflow steps, and sequential families whose names stay inside the same hood.

`%wait:<clan>` waits for every member of the newest clan generation. An exact member name targets only that member.
Killing or dismissing the synthetic clan row cascades to its live members, while acting on one member leaves the rest of
the clan alone.

ACE renders a clan as a synthetic `⌂` row with rolled-up status counts, `@tribe` labels, and wall-clock runtime. Press
`l` once to reveal direct members and a second time to reveal hidden workflow steps and members of nested families; `h`
collapses one level. Selecting the clan row shows an aggregate `CLAN` header and a navigable `MEMBERS` section. The
runtime is the union of member run intervals, with human-wait windows excluded, so concurrent members are not
double-counted.

### Epic bead-work example

`sase bead work <epic-id>` puts every phase worker and the final land agent in clan `<epic-id>` and tribe `@epic`. For
an epic named `sase-6g`, the generated prompt has this shape:

```text
%name:!sase-6g.1
%clan:sase-6g
%tribe:epic
#bd/work_phase_bead:sase-6g.1
---
%name:!sase-6g.land
%clan:sase-6g
%tribe:epic
%wait:sase-6g.1
#bd/land_epic:sase-6g
```

Phase dependency waits remain explicit; the clan container itself is not a land agent or other executable process.

## Sequential Agent Families

An agent family is a strictly sequential chain. A family is created only when `%n(parent, suffix)` attaches the first
follow-up to an existing agent. At that point SASE renames the original agent with its own `--<role>` suffix and
reserves the bare base name as a pure family container. Generic originals become `<family>--0`; plan proposers use
`<family>--plan`. Because creation requires an attachment, a family always has at least two members.

For example, attaching a reviewer to agent `foo` creates family `foo`, renames the original to `foo--0`, and names the
new member `foo--reviewer`:

```text
%n(foo, reviewer) Review the diff produced by this family.
%n(foo, tester) Run the focused tests and report any failures.
%n(planner, @) #with_feedback:: Add failure handling before coding.
```

The suffix is a bare token: write `%n(foo, reviewer)`, not `%n(foo, --reviewer)`. `%n(foo, @)` allocates the next free
numeric suffix.

Every family member has an `agent_family_role` derived from its suffix:

| Suffix                                         | Role                           | Display behavior                 |
| ---------------------------------------------- | ------------------------------ | -------------------------------- |
| `plan`, `q`, `code`, `epic`, `commit`          | Corresponding built-in role    | Built-in plan-chain status rules |
| Numeric (`@` allocates the next free number)   | Feedback or question round     | Built-in round status rules      |
| Any other word (`reviewer`, `tester`, `audit`) | The suffix itself, an open set | Ordinary RUNNING/DONE statuses   |

Arbitrary suffixes are ordinary family labels, not configured lifecycle hooks. SASE does not discover or execute custom
`kind: agent_family` definitions. Replace a stale definition with an explicit family attachment or an agent-requested
launch.

SASE resolves `parent` to the newest visible matching agent or family member in the current project. If the parent is
still running, the new member appears immediately as WAITING and starts only after that exact parent artifact completes
successfully. If the parent fails, stops, or is killed, the queued member becomes STOPPED and SASE sends a completion
notification.

If the parent is missing, ambiguous, or dismissed, or the composed member name already exists, launch preparation fails
before spawning the member. Collision errors suggest `%n(parent, @)`. `%wait:<family>` and `#fork` references to the
bare family name resolve through the family container; an exact `--<suffix>` name targets one member. A member attached
to an agent already inside a clan inherits that clan membership.

Two bundled xprompts help assemble common follow-up prompt bodies. They build text only; `%n` performs the attachment:

```text
%n(planner, @) #with_feedback:: Add failure handling before coding.
%n(planner, @) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The full directive grammar is documented under [XPrompt directives](xprompt.md#supported-directives).

### Attaching within a multi-agent prompt

A later segment can attach to a statically named parent from an earlier segment:

```text
%n:foo Plan the change.
---
%n(foo, reviewer) Review foo's plan.
```

The attached member waits for the in-batch parent to complete successfully. This lookup supports earlier static names
such as `%n:foo` or `%n(foo)`; template-named and auto-named parents must already have an artifact before they can be
used as attachment targets.

## Agent Tribes

An agent tribe is a user-facing label for related agents across clans and families. Assign one at launch with
`%tribe:<name>` or `%t:<name>`:

```text
%n:api-review %t:review Review the API boundary.
```

ACE displays tribes with an `@` prefix and splits the Agents tab into panels such as `@review` and `@epic`. A synthetic
clan row displays the distinct tribes carried by its members. Manage an existing agent's tribe with:

```bash
sase agent tribe set -n <agent> -t <tribe>
sase agent tribe unset -n <agent>
sase agent tribe list [-n <agent>]
```

The persisted metadata field and store are still named `tag` internally for compatibility; the directive, CLI, and
display terminology are tribe.

## Agent-Initiated Family Launches

User-initiated launches are direct: prompts submitted through normal launch surfaces, including prompts containing
`%n(parent, suffix)`, do not require launch approval.

When a **running agent** requests another launch, SASE creates a typed `LaunchApproval` request and spawns nothing until
a human approves it. Agents use the generated `/sase_run` skill and submit a structured request:

```bash
sase launch request -f launch_request.json -o json
```

The request may contain `%n(parent, suffix)` in its prompt, so the approved launch joins an existing family with any
valid suffix. `launch_preview.md` shows the resolved launch plan before approval. Inside an agent, the request command
waits mechanically and returns one JSON outcome for approval, rejection, feedback, dispatch failure, cancellation, or
timeout; the agent does not poll response files.

Approve or reject from ACE, or use:

```bash
sase launch approve <selector>
sase launch reject <selector> [-f <feedback>]
```

The selector may be a request ID, notification ID, or unique notification prefix. Approval verifies the neutral request
bundle, revalidates and replans the stored prompt in its original working directory, and records host dispatch status in
the write-once response. A multi-slot launch is all-or-nothing. In-flight requests from the legacy launch-request layout
remain answerable during the compatibility window.

For the complete request schema, preview behavior, slot limits, and dispatch rules, see
[Launch Approval](ace.md#launch-approval) and `sase launch request --help`.
