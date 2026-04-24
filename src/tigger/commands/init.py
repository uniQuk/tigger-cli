from __future__ import annotations
import pathlib
from tigger.types import RunContext
from tigger._constants import CONFIG_DIR, home_config_dir

_TEMPLATES = {
    "system.md": '''# System Prompt

Customise your system prompt here. This will be prepended to every conversation.
''',
    "hooks.py": '''# Tigger Hooks
# Uncomment and modify to add custom hooks.
#
# def before_bash(tool_call, ctx):
#     """Called before bash tool executes."""
#     return tool_call
#
# def after_bash(event, ctx):
#     """Called after bash tool executes."""
#     return event
''',
}

_DIR_TEMPLATES = {
    "skills": {
        "SKILL.md": '''---
name: example-skill
triggers:
  - /example
context: inline
---
This is an example skill. Replace this with your skill content.
''',
    },
    "agents": {
        "example-agent.md": '''---
name: example-agent
description: Describe when to use this agent
tools:
  - read
  - glob
  - grep
---
You are a helpful agent. Describe your purpose here.
''',
    },
}


def cmd_init(args: str, ctx: RunContext) -> None:
    if "--global" in args:
        tigger_dir = home_config_dir()
    else:
        tigger_dir = pathlib.Path.cwd() / CONFIG_DIR
    tigger_dir.mkdir(parents=True, exist_ok=True)

    created = []
    skipped = []

    for name, content in _TEMPLATES.items():
        path = tigger_dir / name
        if path.exists():
            skipped.append(name)
        else:
            path.write_text(content)
            created.append(name)

    for dirname, files in _DIR_TEMPLATES.items():
        dirpath = tigger_dir / dirname
        dirpath.mkdir(exist_ok=True)
        for name, content in files.items():
            path = dirpath / name
            if path.exists():
                skipped.append(f"{dirname}/{name}")
            else:
                path.write_text(content)
                created.append(f"{dirname}/{name}")

    if created:
        print(f"Scaffolded {tigger_dir}:")
        print(f"  Created: {', '.join(created)}")
    if skipped:
        print(f"  Skipped (already exist): {', '.join(skipped)}")
    if not created and not skipped:
        print("Nothing to do.")
