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
DEFAULT_MAX_TOKENS = 0  # 0 = omit param, let provider use its full output budget
DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_RETRIES = 2
DEFAULT_TEMPERATURE = 0.7
DEFAULT_READ_TIMEOUT = 0  # 0 = no read timeout (recommended for local models)


@dataclass(frozen=True)
class ModelConfig:
    """Per-model sampling overrides. None means use global default."""
    model: str | None = None          # wire id sent to provider; defaults to dict key
    name: str | None = None           # human-readable display label
    temperature: float | None = None
    max_tokens: int | None = None
    context_limit: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    repetition_penalty: float | None = None
    chat_template_kwargs: dict | None = None
    thinking: bool | None = None
    # Suppress sending the OpenAI `tools=[...]` array on the wire. Required
    # for gemma quants from unsloth/bartowski whose stock LM Studio chat
    # templates can't render tool definitions and reject the request with
    # "Cannot call something that is not a function: got UndefinedValue".
    # Model becomes chat-only inside tigger (no agent loop) — same behaviour
    # plain chat clients get for free by never sending tools.
    disable_tools: bool | None = None


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
    model: str                       # wire id sent to provider
    api_key: str = "local"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    active_provider: str = ""
    model_slug: str = ""             # dict key for the active model (defaults to model)
    model_name: str = ""             # display label (falls back to slug)
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    permission_mode: str = "allow"   # ask | allow | bypass
    mode: str = "act"                # act | plan | custom modes
    max_depth: int = DEFAULT_MAX_DEPTH
    max_retries: int = DEFAULT_MAX_RETRIES
    bash_safe_prefixes: list[str] = field(default_factory=list)
    rtk: bool = False
    # Default per-call output budget (chars) for `write.content` and
    # `edit.new_string`/`old_string` when the active skill does not set
    # its own. 0 disables the gate. Skills opt in by declaring
    # `output_budget` in their YAML frontmatter.
    output_budget_default: int = 0
    read_timeout: int = DEFAULT_READ_TIMEOUT
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    repetition_penalty: float | None = None
    chat_template_kwargs: dict = field(default_factory=dict)
    # Resolved per-active-model toggle. True → loop.py sends `tools=[]` so
    # models with broken chat templates (gemma unsloth/bartowski quants on
    # LM Studio) can run as chat-only. Set per-model in config.json.
    disable_tools: bool = False
    # Optional text appended to the resolved system.md (after memory).
    # Lets a project add a few lines of context without copy-pasting the
    # full bundled prompt. Empty/None means no addition.
    system_prompt_extra: str | None = None


@dataclass
class ToolCallRecord:
    call_id: str
    name: str
    args: dict
    # Set when the streamed arguments JSON failed to parse — typically because
    # the response hit max_tokens mid-tool-call and the JSON was truncated.
    parse_error_bytes: int | None = None


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
    finish_reason: str = ""  # "stop" | "length" | "tool_calls" | ""


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict                        # JSON Schema object
    func: Callable[[dict], str]
    read_only: bool = False
    tier: str = "eager"                     # "eager" | "lazy" | "disabled"
    # Per-tool override for the byte cap applied to tool output. `None` falls
    # back to the registry's default (32KB). `read` overrides this upward
    # because the user explicitly requested a file and paging through it in
    # 32KB chunks creates an N-round-trip cost that grows quadratically with
    # context size on each turn.
    max_output_bytes: int | None = None


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
    # Per-call output budget (chars) for write/edit content fields. None
    # means inherit from `config.output_budget_default`. 0 disables the
    # gate. Set in `loop.run_forked` from the active skill's frontmatter.
    output_budget: int | None = None
    # Per-skill chat_template_kwargs override (e.g. {"enable_thinking": False}).
    # Merged on top of `config.chat_template_kwargs` in `loop.run`. Useful for
    # skills whose work is generative (long single writes) and would otherwise
    # waste minutes on reasoning tokens that never reach the file.
    chat_template_kwargs: dict | None = None
    # When True, the agent loop breaks immediately after a successful `write`
    # tool call. Prevents post-write recovery loops where the model second-
    # guesses its own large output, retries, or re-reads to "verify" — a
    # failure mode observed on local Qwen with the architecture-diagram skill.
    stop_after_write: bool = False


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


@dataclass
class StreamProgress:
    """Streaming-progress signal: chars produced by the model since the last event.

    Counts reasoning + tool-call argument deltas that aren't surfaced as TextChunk,
    so the UI can show a live token estimate during tool-heavy turns.
    """
    chars: int
