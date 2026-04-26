from __future__ import annotations

import pathlib
import re

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from tigger.skills import SkillDef


class TiggerCompleter(Completer):
    """Inline completion for tigger REPL. Only activates when input starts with '/'."""

    def __init__(
        self,
        commands: dict,
        skills: list[SkillDef],
    ) -> None:
        # Hold references, not snapshots — `/reload-plugins` mutates these
        # containers in place and the completer must reflect the new state.
        self._commands = commands
        self._skills = skills

    def _live_candidates(self) -> list[str]:
        candidates: list[str] = list(self._commands.keys())
        for skill in self._skills:
            for trigger in skill.triggers:
                stripped = trigger.lstrip("/")
                if stripped not in candidates:
                    candidates.append(stripped)
        return candidates

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # Slash command completion
        if text.startswith("/"):
            fragment = text[1:].lower()  # strip leading /
            seen: set[str] = set()
            for candidate in self._live_candidates():
                if fragment in candidate.lower() and candidate not in seen:
                    seen.add(candidate)
                    yield Completion(
                        "/" + candidate,
                        start_position=-len(text),
                    )
            return

        # @file path completion
        at_match = re.search(r"@(\S*)$", text)
        if at_match:
            partial = at_match.group(1)
            base = pathlib.Path(partial) if partial else pathlib.Path(".")
            parent = base.parent if partial and not partial.endswith("/") else base
            prefix = base.name if partial and not partial.endswith("/") else ""
            try:
                for p in parent.iterdir():
                    name = p.name
                    if name.startswith(prefix):
                        suffix = "/" if p.is_dir() else ""
                        completion = str(parent / name) + suffix
                        yield Completion(
                            "@" + completion,
                            start_position=-(len(partial) + 1),  # +1 for @
                        )
            except OSError:
                pass
