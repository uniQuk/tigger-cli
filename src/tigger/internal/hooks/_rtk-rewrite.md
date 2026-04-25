---
name: _rtk-rewrite
event: PreToolUse
matcher: bash
action: transform
args_match:
  command: "^(?!rtk )"
---
command: rtk {command}
