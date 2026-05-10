# Agentic Software Engineering Series

SASE, short for **Structured Agentic Software Engineering**, uses **agentic software engineering** to mean software work
where AI agents operate inside durable engineering systems: plans, work queues, review records, tests, commits,
dependencies, and handoffs. The series explains why that coordination layer matters and how SASE implements it.

The canonical essays live on the [SASE Blog](../blog/index.md). This page is the series hub for readers who want the
launch arc in order, plus the current product guides for topics whose essays are still planned.

## Start Here

If you have not run SASE yet, read the hands-on companion first:
[Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents](../blog/posts/hello-sase-your-first-15-minutes.md). It
walks through install, your first `sase run`, the resulting ChangeSpec in ACE, and the vocabulary used in every post
below.

## Series Track

| Order | Post                                                                                          | Status                                                      |
| ----- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 1     | [Why Coding Agents Need Orchestration](../blog/posts/why-coding-agents-need-orchestration.md) | Published launch essay                                      |
| 2     | ChangeSpecs: Turning Agent Output Into Reviewable Work                                        | Planned; current guide: [ChangeSpecs](../change_spec.md)    |
| 3     | Beads: Dependency-Aware Work Units For Multi-Agent Execution                                  | Planned; current guide: [Beads](../beads.md)                |
| 4     | XPrompts: Reusable Workflows Above One-Off Prompts                                            | Planned; current guide: [XPrompts](../xprompt.md)           |
| 5     | ACE and Axe: Operating Agents From A Durable Control Plane                                    | Planned; current guides: [ACE](../ace.md), [Axe](../axe.md) |

## Reader Paths

Start with the [launch essay](../blog/posts/why-coding-agents-need-orchestration.md) for the motivation. Then move to
the current guides that make each concept concrete:

- [ACE TUI](../ace.md) for the interactive control surface.
- [Spec-Driven Development](../sdd.md) for plans, epics, legends, and executable phase work.
- [ChangeSpecs](../change_spec.md) for reviewable CL/PR-sized work records.
- [Beads](../beads.md) for issue-like work items, dependency ordering, and multi-agent epic execution.
- [XPrompts](../xprompt.md) for reusable prompt templates and workflow packaging.
- [GitHub](https://github.com/sase-org/sase) for source, issues, and implementation details.

## Publishing Notes

The blog is the canonical publishing surface for SASE essays. Series posts should keep stable slugs, include frontmatter
dates and categories, and link back here so readers can continue through the launch track without relying on archive
pages alone.
