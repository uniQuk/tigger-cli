---
name: review
triggers:
  - /review
context: inline
---
# Code Review

Review the code changes systematically:

1. **Scope** — Run `git diff` (or `git diff --staged`) to see what changed.
2. **Correctness** — Check for logic errors, off-by-one mistakes, unhandled edge cases, and missing error handling.
3. **Style** — Verify the changes follow existing project conventions (naming, formatting, patterns).
4. **Tests** — Are new behaviors tested? Are existing tests updated for changed behavior?
5. **Security** — Check for injection risks, hardcoded secrets, unsafe input handling.
6. **Simplicity** — Could any part be simpler without losing functionality?

Provide findings grouped by severity: critical, important, minor.

$ARGUMENTS
