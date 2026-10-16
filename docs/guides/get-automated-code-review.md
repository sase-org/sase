---
title: Get automated code review
description: Review each change automatically and apply the findings you accept.
---

# Get automated code review

This guide reviews a proposed change automatically: matching profiles trigger focused
review agents, and you accept or reject each finding. It assumes changes flow through
reviewable Patches; if there is no Patch yet, create one first.

## Before you start

You need a checkout where `sase` runs and a Patch with at least one commit in a
reviewable status. Reviews run only once the Patch is ready for review and its checks
have finished.

## 1. Add a mentor profile

Declare when review should run in the configuration file. Each profile names the files
it matches and the reviewers it starts:

```yaml
mentor_profiles:
  - profile_name: python_review
    file_globs:
      - "*.py"
    mentors:
      - mentor_name: style_checker
        role: "Python style expert"
        focus_areas:
          - focus_name: style
            description: "Style and naming conventions"
```

Profiles defined next to the project apply to that project only; profiles in the home
configuration apply everywhere unless restricted. See the mentors reference for match
criteria and scoping.

## 2. Confirm the profile matches

Trace which profiles match the Patch and why before waiting for a review:

```bash
sase config mentor-match my_feature
```

The report shows each criterion result. Adjust the globs or diff patterns until the
intended profile matches, then move the Patch to a reviewable status so the review
agents start when capacity allows.

## 3. Review the findings and apply what you accept

Open the review modal for the Patch with `,C`, move between findings, and press `Space`
on the ones to keep. Then press `a` to propose the accepted comments as an amend for
further review, or `A` to commit them directly. Review agents appear under the review
tribe in the agents view, where they can be inspected or stopped like any run.

## If it goes wrong

No review with a matching profile usually means the Patch is not reviewable yet or its
checks have not finished: confirm the status and wait for the checks. For a review agent
that never starts, see [Unstick a queued agent](unstick-queued-agent.md).

## Related

- [Mentors](../reference/automation/mentors.md) — profiles, severities, output format,
  and every key in the review modal.
- [Automation and human checkpoints](../concepts/automation.md) — where automated review
  fits among autonomous outcomes and human checkpoints.
