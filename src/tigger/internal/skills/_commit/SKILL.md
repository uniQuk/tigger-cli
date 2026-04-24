---
name: _commit
triggers:
  - /_commit
context: inline
---
# Conventional Commit

Create a git commit following conventional commit format:

1. Run `git status` and `git diff --staged` to understand what changed.
2. Classify the change: feat, fix, refactor, docs, test, chore, style, perf, ci, build.
3. Identify the scope (module or component affected).
4. Write a concise commit message: `<type>(<scope>): <description>`
   - Use imperative mood ("add" not "added")
   - Keep the subject line under 72 characters
   - Add a body if the "why" isn't obvious from the subject
5. Stage the relevant files (prefer specific files over `git add .`).
6. Create the commit.

$ARGUMENTS
