---
input:
  - name: prompt
    type: text
---

%g:research {{ prompt }} #research

---

%w %g:research #fork #research/more %m:other

---

%w %g:research #fork #research/image %m:gpt-5.5
