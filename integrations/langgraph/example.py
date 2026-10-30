"""LangGraph + Veilgate: a two-agent graph where every boundary goes through Veilgate.

    pip install langgraph langchain-openai httpx
    export VEILGATE_URL=http://localhost:8080
    export UPSTREAM_BASE_URL=https://api.tokenfactory.nebius.com/v1/ NEBIUS_API_KEY=... NEBIUS_MODEL_NANO=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
    python -m integrations.langgraph.example

The pattern is the same for any framework. Wrap each boundary with one Veilgate call and use what comes back:
  prompt     -> send the RETURNED text to the model (it holds tokens, never the real values)
  completion -> use the RETURNED text as the model's answer
  tool_call  -> if it returns False, do not run the tool
  tool_result-> hand the RETURNED text to the agent
Then open the dashboard: the whole run is one trace.
"""

import asyncio
import os
import time
import uuid
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from integrations.http_only.client import Veilgate

MODEL = os.environ["NEBIUS_MODEL_NANO"]
vg = Veilgate(os.environ.get("VEILGATE_URL", "http://localhost:8080"), user_id="alice")
llm = ChatOpenAI(base_url=os.environ["UPSTREAM_BASE_URL"], api_key=os.environ["NEBIUS_API_KEY"], model=MODEL, max_tokens=600)


class State(TypedDict):
    sid: str       # one id for the whole run: it becomes the trace
    question: str
    record: str
    answer: str


async def governed_llm(agent: str, sid: str, text: str, parent: str | None = None) -> str:
    """One model call with Veilgate on both sides."""
    safe_prompt = await vg.prompt(agent, sid, text, parent, MODEL)       # 1. mask before the model sees it
    t0 = time.perf_counter()
    out = await llm.ainvoke(safe_prompt)                                   # 2. the model only sees tokens
    use = out.usage_metadata or {}
    return await vg.completion(agent, sid, str(out.content), parent, use.get("input_tokens", 0), use.get("output_tokens", 0),
                               (time.perf_counter() - t0) * 1000, MODEL)   # 3. check what came back, record usage


def lookup_patient(mrn: str) -> str:  # your real tool; it returns real data
    return "Rahul Verma, DOB 1984-03-12, SSN 123-45-6789, phone +91 98765 43210, type 2 diabetes."


async def researcher(state: State) -> dict:
    sid = state["sid"]
    allowed = await vg.tool_call("researcher", sid, "lookup_patient", {"mrn": "MRN-884213"}, "medium", ["lookup_patient"], parent="planner")
    if not allowed:
        return {"record": "(tool call denied by Veilgate)"}
    safe_result = await vg.tool_result("researcher", sid, "lookup_patient", lookup_patient("MRN-884213"), parent="planner")
    return {"record": safe_result}   # tokens, not the real SSN


async def planner(state: State) -> dict:
    sid = state["sid"]
    await governed_llm("planner", sid, state["question"])          # the planner thinks about the (masked) question
    summary = await governed_llm("researcher", sid, f"Summarise this record in two lines: {state['record']}", parent="planner")
    return {"answer": summary}


graph = StateGraph(State)
graph.add_node("researcher", researcher)
graph.add_node("planner", planner)
graph.add_edge(START, "researcher")
graph.add_edge("researcher", "planner")
graph.add_edge("planner", END)
app = graph.compile()


async def main() -> None:
    sid = str(uuid.uuid4())
    result = await app.ainvoke({"sid": sid, "question": "Prepare a discharge note for Rahul Verma, MRN-884213, phone 98765 43210.", "record": "", "answer": ""})
    await vg.end("planner", sid, {"framework": "langgraph"})
    print("answer:", result["answer"][:300])
    print(f"trace:  {os.environ.get('VEILGATE_URL', 'http://localhost:8080')}/app/#/traces/{sid}")
    await vg.aclose()


if __name__ == "__main__":
    asyncio.run(main())
