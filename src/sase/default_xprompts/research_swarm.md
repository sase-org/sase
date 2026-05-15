---
input:
  - name: prompt
    type: text
---

%g:research {{ prompt }} #research

---

%w %g:research #resume #research/more %m:other

---

%w %g:research #resume #research/image %m:gpt-5.5
