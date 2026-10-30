"""GuardRailBench hook endpoints: POST /api/v1/<hook>. They never raise to the caller.

On an internal error a hook fails closed: text is redacted by the pure detector, tool calls are denied.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from src.core.config import get_settings
from src.detection import detect
from src.services import hooks as svc

log = structlog.get_logger(__name__)


async def _hook_key(x_veilgate_key: str | None = Header(default=None)) -> None:
    """If HOOK_API_KEY is configured, agents must present it. Empty means open (local development)."""
    required = get_settings().hook_api_key
    if required and x_veilgate_key != required:
        raise HTTPException(401, "missing or wrong X-Veilgate-Key")


hooks_router = APIRouter(prefix="/api/v1", tags=["hooks"], dependencies=[Depends(_hook_key)])


class Identity(BaseModel):
    user_id: str
    agent_id: str
    session_id: str
    parent_agent_id: str | None = None


def _redact(text: str) -> str:
    out, pos = [], 0
    for e in detect(text):
        out += [text[pos:e.start], f"[{e.type}]"]
        pos = e.end
    return "".join(out) + text[pos:]


async def _run(body: Identity, fn, *args):
    async with svc.session_factory() as db:
        ctx = await svc.open_ctx(db, body.user_id, body.agent_id, body.session_id, body.parent_agent_id, getattr(body, "model", None))
        result = await fn(ctx, *args)
        await db.commit()
        return result


class PromptIn(Identity):
    prompt: str = ""
    model: str | None = None


@hooks_router.post("/on_prompt_received")
async def on_prompt_received(body: PromptIn) -> dict[str, Any]:
    try:
        return {"prompt": await _run(body, svc.on_prompt_received, body.prompt)}
    except Exception as exc:  # noqa: BLE001 - fail closed
        log.error("hook.failed", hook="on_prompt_received", error=str(exc))
        return {"prompt": _redact(body.prompt)}


class CompletionIn(Identity):
    completion: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0
    model: str | None = None


@hooks_router.post("/on_completion_received")
async def on_completion_received(body: CompletionIn) -> dict[str, Any]:
    try:
        text = await _run(body, svc.on_completion_received, body.completion, body.prompt_tokens, body.completion_tokens, body.latency_ms)
        return {"completion": text}
    except Exception as exc:  # noqa: BLE001
        log.error("hook.failed", hook="on_completion_received", error=str(exc))
        return {"completion": _redact(body.completion)}


class ToolCallIn(Identity):
    tool_name: str
    tool_args: Any = None
    tool_risk: str = "medium"
    agent_allowed_tools: list[str] | None = Field(default=None)


@hooks_router.post("/on_tool_call")
async def on_tool_call(body: ToolCallIn) -> dict[str, Any]:
    try:
        allow = await _run(body, svc.on_tool_call, body.tool_name, body.tool_args, body.tool_risk, body.agent_allowed_tools)
        return {"allow": allow}
    except Exception as exc:  # noqa: BLE001
        log.error("hook.failed", hook="on_tool_call", error=str(exc))
        return {"allow": False}


class ToolResultIn(Identity):
    tool_name: str
    result: str = ""
    tool_succeeded: bool = True
    latency_ms: float = 0


@hooks_router.post("/on_tool_result")
async def on_tool_result(body: ToolResultIn) -> dict[str, Any]:
    try:
        return {"result": await _run(body, svc.on_tool_result, body.tool_name, body.result, body.tool_succeeded, body.latency_ms)}
    except Exception as exc:  # noqa: BLE001
        log.error("hook.failed", hook="on_tool_result", error=str(exc))
        return {"result": _redact(str(body.result))}


class SessionEndIn(Identity):
    summary: dict[str, Any] = Field(default_factory=dict)


@hooks_router.post("/on_session_end")
async def on_session_end(body: SessionEndIn) -> dict[str, Any]:
    try:
        await _run(body, svc.on_session_end, body.summary)
    except Exception as exc:  # noqa: BLE001
        log.error("hook.failed", hook="on_session_end", error=str(exc))
    return {"ok": True}
