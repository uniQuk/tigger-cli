"""Shared YAML frontmatter parsing utilities."""
from __future__ import annotations
import re


def parse_blocks(text: str) -> list[dict]:
    import yaml
    blocks = []
    parts = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    i = 1
    while i + 1 < len(parts):
        fm_text = parts[i].strip()
        body = parts[i + 1].strip()
        if fm_text:
            try:
                fm = yaml.safe_load(fm_text)
                if isinstance(fm, dict):
                    blocks.append({"fm": fm, "body": body})
            except Exception:
                pass
        i += 2
    return blocks


def parse_single(text: str) -> dict | None:
    """Parse a single frontmatter document.

    Only the first --- pair is treated as frontmatter. Everything after
    the closing --- is body, even if it contains more --- lines (e.g.
    YAML examples inside code blocks).
    """
    import yaml
    m = re.match(r"^---\s*\n(.*?\n)---\s*$", text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return None
    fm_text = m.group(1).strip()
    body = text[m.end():].strip()
    if not fm_text:
        return None
    try:
        fm = yaml.safe_load(fm_text)
        if isinstance(fm, dict):
            return {"fm": fm, "body": body}
    except Exception:
        pass
    return None
