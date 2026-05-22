---
description: Launch a small research swarm for a user-provided topic.
input:
  - name: prompt
    type: text
    description: Research topic or question for the swarm to investigate.
---

%g:research {{ prompt }} #research

---

%w %g:research #fork #research/more %m:other

---

%w %g:research #fork #research/image %m:gpt-5.5
