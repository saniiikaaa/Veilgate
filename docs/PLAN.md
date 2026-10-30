# Veilgate build plan

Hackathon: Nebius x NVIDIA Global AI Hackathon, deadline **30 Oct 2026** (10:00 am PT).
Track: **Best Apps and Agents**. Hard requirements: a runtime call to Nebius Token Factory with an NVIDIA Nemotron model, public repo with an open-source LICENSE, README with setup, a hosted demo URL, and a demo video under 3 minutes.
Judging (equal weights): technical implementation, design, impact, quality of the idea.

What Veilgate is: a governance runtime for LLM agents. It sits on every boundary (user to agent, agent to agent, agent to model, agent to tool), tokenizes sensitive data (HIPAA / DPDP), gates tool calls by an earned authority score, and writes tamper-evident receipts. Everything is **traced**.

## Phases

| # | Phase | Done when |
|---|---|---|
| 1 ✅ | **Engine core**: detector, vault (AES-GCM tokenizer), the five GuardRailBench hooks over the existing Postgres schema | each hook works against the live DB; unit and integration tests pass |
| 2 ✅ | **Authority and gate**: score ledger rules, tool gate, delegation cap, prompt-injection check, external-email denial, session verdict | rogue agent is denied and its score falls; verdict blocks the final answer |
| 3 ✅ | **Tracing API**: one trace graph per session (user, agents, tools, models as nodes; handoffs, tool calls, model calls as edges) plus a flat span timeline, receipts and verify | `GET /api/traces/{session}` returns the graph with decisions and scores on every edge |
| 4 ✅ | **Nemotron on Nebius**: model gateway, LLM judge for injection and ambiguous entities, demo multi-agent app | a demo run makes real Token Factory calls and shows up in the trace. Verified live on Nebius Token Factory with Nemotron Nano, Super and Ultra |
| 5 ✅ | **Dashboard** (light theme): Overview, Traces, Agents, Policies and tools, Receipts | all pages read live data; trace page is the showpiece |
| 6 | **Ship**: LICENSE, README, Dockerfile, deploy on Nebius, demo script, submission text | a stranger can clone, run and see the demo |

## Dashboard rules
Light (white) background, minimal, only what matters. Pages: Overview, Traces, Agents, Policies, Receipts. The Traces page is the showpiece: agent to agent, agent to user, agent to tool and agent to model, each with decision, tokens, latency and score delta.

## Rules for the code
- The application connects as `guardrail_app`; row-level security applies. Set the tenant context on every session.
- Original sensitive text is never stored in `events`; only tokenized text and a hash.
- Never commit secrets. `NEBIUS_API_KEY` comes from the environment.
