---
plan: sdd/plans/202603/fast_mentor_review_1.md
---
The `,m` keymap works perfectly right now, but because we need access to the file versions on the corresponding
ChangeSpec's branch, we currently claim a workspace and checkout the branch there. The problem is that this is VERY
slow. Can you help me plan a way to make the Mentor Review panel load up WAY faster?
