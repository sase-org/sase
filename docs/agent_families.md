# Agent Families

An **agent family** is a group of related agents that ACE folds under one root entry on the Agents tab. SASE supports
two forms:

- Serial plan-chain families use `--`-separated names such as `foo`, `foo--plan`, `foo--code`, and `foo--reviewer`.
- Parallel families use explicit `%family` directives. Membership does not constrain member names or alter execution.

Dot-separated names such as `foo.bar` are a separate ACE concept: agent _hoods_ and _neighbors_. They do not create
plan-chain family membership.

## Parallel Families with `%family`

In a multi-agent prompt, add `%family:<root-name>` to each member segment. The sibling segment whose `%name` matches
`<root-name>` becomes the root and needs no `%family` directive:

```text
%name:build
%family(release, role=phase)
Compile the release.
---
%name:test
%family(release, role=phase)
Test the release.
---
%name:release
%wait:build,test
Publish the release after both members finish.
```

The colon form, `%family:release`, assigns the default `member` role. The parenthesized form accepts one optional
free-form role token, as in `%family(release, role=tester)`. Static names and templates such as
`%family(research.@.final, role=researcher)` are supported. If no sibling segment has the target name, SASE resolves the
new member against the newest matching family root or exact named agent already on disk.

Parallel membership is execution-neutral: it does not add waits, change launch order, choose a workspace or model, or
rewrite a member's name. Use `%wait` explicitly wherever ordering is required. `%family` and the serial
`%n(parent, suffix)` attachment form cannot be combined in the same segment.

Every parallel member counts toward runner-slot admission. Killing or dismissing the root cascades to its live members,
while killing one member leaves the root and siblings alone. The root row aggregates the whole generation's status and
shows member-state counts. A question or failure in any member is therefore visible even when the family is folded.

Inside a parallel family, a `%wait` or `#fork` reference to the family base resolves to that generation's root agent.
Outside the family, `%wait:<root-name>` waits for the whole family to complete. An exact member name always targets that
member.

### Epic bead-work example

`sase bead work <epic-id>` renders every phase worker as a parallel member of the land agent. For an epic named
`sase-6g`, the generated prompt has this shape:

```text
%name:!sase-6g.1
%family(sase-6g, role=phase)
#bd/work_phase_bead:sase-6g.1
---
%name:!sase-6g
%wait:sase-6g.1
#bd/land_epic:sase-6g
```

The land segment is the root. Phase dependency waits remain explicit, and no per-epic `%group` tag is emitted because
the family root is the grouping surface.

## Family Roles and Suffixes

Every family member has an `agent_family_role` derived from its suffix:

| Suffix                                         | Role                           | Display behavior                 |
| ---------------------------------------------- | ------------------------------ | -------------------------------- |
| `plan`, `q`, `code`, `epic`, `commit`          | Corresponding built-in role    | Built-in plan-chain status rules |
| Numeric (`@` allocates the next free number)   | Feedback or question round     | Built-in round status rules      |
| Any other word (`reviewer`, `tester`, `audit`) | The suffix itself, an open set | Ordinary RUNNING/DONE statuses   |

Arbitrary suffixes are ordinary family labels, not configured lifecycle hooks. SASE does not discover or execute custom
`kind: agent_family` definitions. A stale definition fails with migration guidance when the xprompt catalog is loaded;
replace it with an explicit family attachment or an agent-requested launch.

## Extending a Family by Hand

Use the two-argument `%n(parent, suffix)` directive in an ordinary launch prompt:

```text
%n(foo, reviewer) Review the diff produced by this family.
%n(foo, tester) Run the focused tests and report any failures.
%n(planner, @) #with_feedback:: Add failure handling before coding.
```

The suffix is a bare token: write `%n(foo, reviewer)`, not `%n(foo, --reviewer)`. It may contain letters, numbers, and
underscores. `%n(foo, @)` allocates the next free numeric suffix.

SASE resolves `parent` to the newest visible root agent in the current project, composes the child name as
`<family-base>--<suffix>`, writes the normal family metadata, and removes the directive before the model sees the
prompt. If the parent is still running, the child appears immediately as WAITING and starts after that exact parent
artifact completes successfully. If the parent fails, stops, or is killed, the queued child is cancelled to STOPPED and
SASE sends a completion notification.

If the parent is missing, ambiguous, or dismissed, or the composed child name already exists, launch preparation fails
before spawning the child. Collision errors suggest `%n(parent, @)`.

Two bundled xprompts help assemble common follow-up prompt bodies. They build text only; `%n` performs the attachment:

```text
%n(planner, @) #with_feedback:: Add failure handling before coding.
%n(planner, @) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The full directive grammar is documented under [XPrompt directives](xprompt.md#supported-directives).

## Attaching Within a Multi-Agent Prompt

A later segment can attach to a statically named parent from an earlier segment:

```text
%n:foo Plan the change.
---
%n(foo, reviewer) Review foo's plan.
```

The attached member waits for the in-batch parent to complete successfully. This lookup supports earlier static names
such as `%n:foo` or `%n(foo)`; template-named and auto-named parents must already have an artifact before they can be
used as attachment targets.

## Agent-Initiated Family Launches

User-initiated launches are direct: prompts submitted through normal launch surfaces, including prompts containing
`%n(parent, suffix)`, do not require a launch approval.

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
