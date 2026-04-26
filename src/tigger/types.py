from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class TrustLevel(StrEnum):
    ALWAYS = "always"
    READONLY = "readonly"


# Default Config values — single source of truth, referenced by both
# the Config dataclass and load_config().
DEFAULT_CONTEXT_LIMIT = 128000
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_RETRIES = 2
DEFAULT_TEMPERATURE = 0.7
DEFAULT_READ_TIMEOUT = 1800  # seconds; max gap between streamed SSE chunks


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
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    permission_mode: str = "allow"   # ask | allow | bypass
    mode: str = "act"                # act | plan | custom modes
    max_depth: int = DEFAULT_MAX_DEPTH
    max_retries: int = DEFAULT_MAX_RETRIES
    bash_safe_prefixes: list[str] = field(default_factory=list)
    rtk: bool = False
    read_timeout: int = DEFAULT_READ_TIMEOUT


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
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict                        # JSON Schema object
    func: Callable[[dict], str]
    read_only: bool = False
    tier: str = "eager"                     # "eager" | "lazy" | "disabled"


@dataclass
class ModeRef:
    name: str
    body: str                                       # prompt fragment appended to system prompt
    source_path: pathlib.Path | None = None


@dataclass
class RunContext:
    config: Config
    messages: list[Message]
    system_prompt: str
    depth: int = 0
    allowed_tools: list[str] | None = None  # None = all tools
    turn: int = 0
    trust_level: TrustLevel = TrustLevel.READONLY
    modes: list[ModeRef] = field(default_factory=list)


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
class ToolResult:
    """Outcome of a single ToolRegistry.execute() call."""
    output: str
    error: bool = False


@dataclass
class ToolEndEvent:
    call_id: str
    name: str
    output: str
    error: bool = False
    permitted: bool = True


@dataclass
class PermissionRequest:
    """Request the consumer to authorize a tool call. The loop awaits a bool
    answer via the ``permission_callback`` passed to ``run()``."""
    call_id: str
    name: str
    args: dict


@dataclass
class TurnDoneEvent:
    input_tokens: int
    output_tokens: int


@dataclass
class ThinkingEvent:
    """Yielded before a subsequent model call so the UI can show a spinner."""
    pass
