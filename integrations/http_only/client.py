"""Plain-HTTP client for the five Veilgate hooks. Works with any agent framework: wrap each boundary with one call.

    vg = Veilgate("http://localhost:8080", user_id="alice")
    safe = await vg.prompt("orchestrator", sid, user_text)        # send `safe` to the model, never the raw text
    reply = await vg.completion("orchestrator", sid, model_reply, model="nvidia/...")
    if await vg.tool_call("data_agent", sid, "lookup_patient", args, "medium", ["lookup_patient"], parent="orchestrator"):
        result = await vg.tool_result("data_agent", sid, "lookup_patient", run_tool(args), parent="orchestrator")
"""

from typing import Any

import httpx


class Veilgate:
    def __init__(self, base_url: str = "http://localhost:8080", user_id: str = "user", timeout: float = 60.0,
                 api_key: str | None = None) -> None:
        self.user_id = user_id
        headers = {"X-Veilgate-Key": api_key} if api_key else {}
        self._http = httpx.AsyncClient(base_url=f"{base_url.rstrip('/')}/api/v1", timeout=timeout, headers=headers)

    async def _post(self, hook: str, agent: str, session: str, parent: str | None, **body: Any) -> dict[str, Any]:
        payload = {"user_id": self.user_id, "agent_id": agent, "session_id": session, "parent_agent_id": parent, **body}
        r = await self._http.post(f"/{hook}", json=payload)
        r.raise_for_status()
        return r.json()

    async def prompt(self, agent: str, session: str, text: str, parent: str | None = None, model: str | None = None) -> str:
        return (await self._post("on_prompt_received", agent, session, parent, prompt=text, model=model))["prompt"]

    async def completion(self, agent: str, session: str, text: str, parent: str | None = None, prompt_tokens: int = 0,
                         completion_tokens: int = 0, latency_ms: float = 0, model: str | None = None) -> str:
        r = await self._post("on_completion_received", agent, session, parent, completion=text, prompt_tokens=prompt_tokens,
                             completion_tokens=completion_tokens, latency_ms=latency_ms, model=model)
        return r["completion"]

    async def tool_call(self, agent: str, session: str, tool: str, args: Any, risk: str, allowed_tools: list[str],
                        parent: str | None = None) -> bool:
        r = await self._post("on_tool_call", agent, session, parent, tool_name=tool, tool_args=args, tool_risk=risk,
                             agent_allowed_tools=allowed_tools)
        return bool(r["allow"])

    async def tool_result(self, agent: str, session: str, tool: str, result: str, ok: bool = True, latency_ms: float = 0,
                          parent: str | None = None) -> str:
        r = await self._post("on_tool_result", agent, session, parent, tool_name=tool, result=result, tool_succeeded=ok,
                             latency_ms=latency_ms)
        return r["result"]

    async def end(self, agent: str, session: str, summary: dict[str, Any] | None = None) -> None:
        await self._post("on_session_end", agent, session, None, summary=summary or {})

    async def aclose(self) -> None:
        await self._http.aclose()
