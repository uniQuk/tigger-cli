---
name: debug
triggers:
  - /debug
context: inline
---
# Structured Debugging

Follow this systematic debugging methodology:

1. **Identify** — Reproduce the issue. What is the expected vs actual behavior?
2. **Hypothesize** — Form 2-3 hypotheses about the root cause based on the symptoms.
3. **Investigate** — For each hypothesis, identify the files and code paths involved. Use grep and read to trace the execution flow.
4. **Verify** — Test your hypothesis by reading the relevant code, checking logs, or running targeted commands.
5. **Fix** — Apply the minimal fix that addresses the root cause. Prefer surgical edits over rewrites.
6. **Validate** — Run tests to confirm the fix works and hasn't introduced regressions.

Apply this to the following issue:

$ARGUMENTS
