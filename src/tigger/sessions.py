from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import re
from dataclasses import dataclass

from tigger.types import Message, ToolCallRecord


@dataclass
class SessionInfo:
    path: pathlib.Path
    timestamp: str
    message_count: int


def _message_to_dict(m: Message) -> dict:
    d = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [{"call_id": tc.call_id, "name": tc.name, "args": tc.args} for tc in m.tool_calls]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.name:
        d["name"] = m.name
    return d


def _message_from_dict(d: dict) -> Message:
    tool_calls = []
    for tc in d.get("tool_calls", []):
        tool_calls.append(ToolCallRecord(call_id=tc["call_id"], name=tc["name"], args=tc["args"]))
    return Message(
        role=d["role"],
        content=d["content"],
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


def save_message(session_dir: pathlib.Path, session_id: str, message: Message) -> None:
    """Append a single message to the session file."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / f"{session_id}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(_message_to_dict(message)) + "\n")


def load_session(path: pathlib.Path) -> list[Message]:
    """Load messages from a JSONL session file."""
    messages = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(_message_from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError):
            continue  # skip corrupt lines
    return messages


def list_sessions(session_dir: pathlib.Path) -> list[SessionInfo]:
    """List sessions sorted by recency (newest first)."""
    if not session_dir.exists():
        return []
    sessions = []
    for p in sorted(session_dir.glob("*.jsonl"), reverse=True):
        line_count = sum(1 for line in p.read_text().splitlines() if line.strip())
        sessions.append(SessionInfo(path=p, timestamp=p.stem, message_count=line_count))
    return sessions


def new_session_id() -> str:
    """Generate a timestamp-based session ID."""
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def project_id(project_path: pathlib.Path) -> str:
    """Return a stable, readable project identifier: <basename>-<sha256[:8]>."""
    resolved = str(project_path.resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:8]
    basename = project_path.resolve().name
    # Sanitise basename to filesystem-safe chars
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", basename)
    return f"{safe}-{digest}"


def project_session_dir(global_dir: pathlib.Path, project_path: pathlib.Path) -> pathlib.Path:
    """Return the session directory for a project under the global config dir."""
    return global_dir / "sessions" / project_id(project_path)
