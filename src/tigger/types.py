from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class TrustLevel(str, Enum):
    ALWAYS = "always"
    READONLY = "readonly"


@dataclass(frozen=True)
class ModelConfig:
    """Per-model sampling overrides. None means use global default."""
    temperature: float | None = None
    max_tokens: int | None = None
    context_limit: int | None = None
    top_p: float | None = None
    thinking: bool | None = None


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    models: list[str] | dict[str, ModelConfig] = field(default_factory=list)

    @property
    def model_names(self) -> list[str]:
        if isinstance(self.models, dict):
            return list(self.models.keys())
        return self.models


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = "local"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    active_provider: str = ""
    context_limit: int = 8192
    max_tokens: int = 2048
    temperature: float = 0.7
    permission_mode: str = "allow"   # ask | allow | bypass
    mode: str = "ask"                # ask | plan
    max_depth: int = 4
    max_retries: int = 2
    bash_safe_prefixes: list[str] = field(default_factory=list)
    rtk: bool = False


@dataclass
class ToolCallRecord:
    call_id: str
    name: str
    args: dict


@dataclass
class Message:
    role: str                               # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_call_id: str | None = None         # for role="tool"
    name: str | None = None                 # for role="tool"


@dataclass
class AssistantMessage:
    """Raw response from the provider before it's stored as a Message."""
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict                        # JSON Schema object
    func: Callable[[dict], str]
    read_only: bool = False


@dataclass
class RunContext:
    config: Config
    messages: list[Message]
    system_prompt: str
    depth: int = 0
    allowed_tools: list[str] | None = None  # None = all tools
    turn: int = 0
    trust_level: TrustLevel = TrustLevel.READONLY


# ── Events yielded by the agent loop ──────────────────────────────────────

@dataclass
class TextChunk:
    content: str


@dataclass
class ToolStartEvent:
    call_id: str
    name: str
    args: dict


@dataclass
class ToolEndEvent:
    call_id: str
    name: str
    output: str
    error: bool = False
    permitted: bool = True


@dataclass
class PermissionEvent:
    call_id: str
    name: str
    args: dict
    granted: bool = False


@dataclass
class TurnDoneEvent:
    input_tokens: int
    output_tokens: int


@dataclass
class ThinkingEvent:
    """Yielded before a subsequent model call so the UI can show a spinner."""
    pass
