---
name: _hookify
triggers:
  - /hookify
context: inline
---
# Create a Hook

Create a markdown hook file that will be evaluated automatically on tool use or session start.

## If no arguments provided

Analyze the recent conversation for patterns that should be prevented or enforced. Look for:
- Commands the user corrected or warned about
- Patterns the user asked you to avoid
- Safety rules that were discussed

Suggest 1-3 hooks based on what you find. For each, show the proposed hook file content and ask which to create.

## If arguments provided

Parse the instruction and create a hook file. Examples:
- `/hookify block rm -rf commands` -> creates a PreToolUse hook blocking dangerous rm
- `/hookify warn before writing to .env files` -> creates a PreToolUse hook warning on .env writes
- `/hookify log all bash commands` -> creates a PostToolUse hook logging bash usage

## Hook File Format

Create the file at `~/.tigger/hooks/<name>.md` (global) with this format:

```
---
name: <descriptive-kebab-name>
event: PreToolUse    # or PostToolUse, SessionStart
matcher: <regex>     # matched against tool name (bash, read, write, edit, glob, grep, web_fetch)
action: block        # or warn, allow
enabled: true
---
<Message shown to the user when this hook fires>
```

## Event Reference

- **PreToolUse**: fires before a tool executes. Use `block` to prevent dangerous operations, `warn` to show a reminder.
- **PostToolUse**: fires after a tool executes. Use `warn` to log or flag operations.
- **SessionStart**: fires when a session begins. Use `warn` to show setup reminders.

## Matcher Examples

- `bash` - matches only bash tool calls
- `write|edit` - matches write or edit tool calls
- `.*` - matches all tool calls (default)
- `bash|write|edit` - matches bash, write, or edit

After creating the hook file, confirm it was written and explain what it will do.

$ARGUMENTS
