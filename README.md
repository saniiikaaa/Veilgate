# Veilgate

**Governance for AI agents.** Veilgate sits on every hop of an agent system (user, agent, model, tool). It replaces sensitive data (HIPAA and India DPDP) with vault tokens before anything sees it, scores each agent on the authority it earns, denies risky tool calls, blocks prompt injection, and records the whole conversation as a hash-chained, tamper-evident trace you can explore in a dashboard.

Built for the **Nebius x NVIDIA Global AI Hackathon** (track: *Best Apps and Agents*). MIT licensed.

## How we use NVIDIA Nemotron and Nebius

- **Runs on Nebius Token Factory.** Every model call goes through one OpenAI-compatible gateway (`src/gateway/llm.py`) pointed at `https://api.tokenfactory.nebius.com/v1/`.
- **NVIDIA Nemotron models, by tier** (set in `.env`, verified live on Token Factory):
  - `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`: the fast, everyday calls (the demo agents and the detection judge).
  - `nvidia/nemotron-3-super-120b-a12b`: the mid tier.
  - `nvidia/Nemotron-3-Ultra-550b-a55b`: the heavy-reasoning tier.
- **Nemotron as a privacy judge.** After the rules and checksums run, Nemotron reads only the *already-masked* text and flags what is left (for example a name the rules have never seen) and prompt injection in tool outputs. Its answers are never trusted blindly: a returned value must appear word for word in the text.
- **Reasoning-model aware.** The gateway retries with a larger token budget when a reasoning model spends its whole budget thinking.
- **One toggle** in `.env`, `LLM_PROVIDER=nebius`, selects Token Factory. `local` points at any OpenAI-compatible server instead.

Feedback on Token Factory and Nemotron: see `docs/FEEDBACK.md`.

## What was built during the hackathon

Veilgate is an upgrade of an earlier prototype (LLM-Guardrail) and was rebuilt from scratch for this hackathon: a new Postgres schema with row-level security, a vault with AES-GCM tokens, a rebuilt detector with checksum validators and obfuscation handling (zero-width characters, look-alike letters, base64), agent authority scoring with a delegation cap, a tool gate, receipts, a tracing API, and a new dashboard (flow graph, sequence diagram, score history).

## Use it with your own agents

Veilgate is five HTTP calls. Run the API (`uvicorn src.main:app --port 8080`), then wrap each boundary of your agent and use what comes back:

| Call | When | Use the response |
|---|---|---|
| `POST /api/v1/on_prompt_received` | before a model call | send the returned `prompt` to the model (tokens, not real values) |
| `POST /api/v1/on_completion_received` | after a model call | use the returned `completion` |
| `POST /api/v1/on_tool_call` | before a tool runs | if `allow` is false, do not run it |
| `POST /api/v1/on_tool_result` | after a tool runs | hand the returned `result` to the agent |
| `POST /api/v1/on_session_end` | when the run finishes | nothing |

Every call carries `user_id`, `agent_id`, `session_id` (one per run) and `parent_agent_id` (who delegated to this agent). Try it with curl:

```bash
export VEILGATE=http://localhost:8080
curl -s -X POST $VEILGATE/api/v1/on_prompt_received -H 'content-type: application/json' \
  -d '{"user_id":"alice","agent_id":"orchestrator","session_id":"s1","prompt":"SSN 123-45-6789 for Rahul Verma"}'
# {"prompt":"SSN tok_ssn_04f5e7809e73 for tok_name_..."}   <- send THIS to the model
```

A complete LangGraph example (two agents, one tool, real Nemotron calls) is in [`integrations/langgraph/example.py`](integrations/langgraph/example.py); `integrations/http_only/client.py` is the small client it uses, and works the same with LangChain or plain code. Open the dashboard afterwards and the run is one trace.

## Prerequisites

- Python 3.11 or newer
- Docker with Docker Compose (the easiest way to get PostgreSQL 16), or a local PostgreSQL 16

## Quick start (local dev, Docker only for the database)

```bash
# 1. Python environment
uv venv --python 3.11 .venv      # or: python3.11 -m venv .venv
source .venv/bin/activate
uv pip install -e . pytest       # or: pip install -e . pytest

# 2. Config
cp .env.example .env
```

Edit `.env` and replace the `CHANGE_ME` passwords with the ones the migrations create. If port 5432 is already used by another Postgres, pick a free host port (this setup uses 5440) and set `WARDEN_DB_PORT` to match:

```
DATABASE_URL=postgresql://guardrail_app:apppass@localhost:5440/guardrail_v2
MIGRATION_DATABASE_URL=postgresql://guardrail_owner:ownerpass@localhost:5440/guardrail_v2
WARDEN_DB_PORT=5440
```

Default credentials (dev only): owner `guardrail_owner` / `ownerpass`, app `guardrail_app` / `apppass`, database `guardrail_v2`.

```bash
# 3. Start PostgreSQL only
docker compose --env-file .env -f deploy/compose/docker-compose.yml up -d warden-db

# 4. Create the schema and the demo data (the scripts read the environment, not .env)
set -a; . ./.env; set +a
python scripts/db/migrate.py
python scripts/db/seed.py

# 5. Run the API with hot reload (port 8080; `scripts/dev/start.py` needs `PYTHONPATH=.`)
uvicorn src.main:app --reload --port 8080
```

Open:
- http://localhost:8080/docs (Swagger UI)
- http://localhost:8080/healthz (liveness)
- http://localhost:8080/readyz (readiness, checks the DB)
- http://localhost:8080/admin/status

## Run everything in Docker

```bash
docker compose --env-file .env -f deploy/compose/docker-compose.yml up --build -d
```

The development Compose command initializes the local database and seeds it before starting the API. Hosted deployments do not run migrations from the API container.

## Model provider

One toggle in `.env`: `LLM_PROVIDER=nebius` (Nebius Token Factory with NVIDIA Nemotron; needs `NEBIUS_API_KEY`) or `LLM_PROVIDER=local` (a company-hosted OpenAI-compatible model; see the `LOCAL_LLM_*` settings).

## Dashboard

Open http://localhost:8080/ and sign in. Demo logins (from `config/default.yml`, demo only):

| Role | Email | Password | Sees |
|---|---|---|---|
| Admin | `admin@veilgate.demo` | `admin-demo-2026` | every session, plus the Policies page |
| User | `iyer@veilgate.demo` | `iyer-demo-2026` | only their own sessions |

Pages: Overview (needs-attention list, top users), Traces (Flow graph, Sequence diagram, Timeline, Agents & scores with the score-over-time chart, Receipts), Agents, Trust & Tokens (user rating, tokens and violations over time), Users (admin), Test detection (try the detector on any text), Policies (admin). To fill it with sample data: `./scripts/dev/demo_data.sh`.

Agents call `/api/v1/*` (the hooks). Set `HOOK_API_KEY` in `.env` to require an `X-Veilgate-Key` header on them.

## Demo

With the API running: `python -m demo.clinic_demo` (add `--story clean` for the no-attack version, or `--offline` for a scripted stand-in model with no network). It runs three agents through a discharge-summary task with a poisoned search result, an external email and an out-of-scope tool, then prints a link to the trace.

To attach your own agents, use `integrations/http_only/client.py` (five calls, any framework).

## Scoring

All authority and tool-gate numbers live in `config/default.yml` and are synced into the database at startup and by `scripts/db/seed.py`.

## Tests

Tests run against their own database, `guardrail_v2_test` (created on first run), so they never touch the data you demo from.

```bash
pytest tests/unit                 # no database or network needed
pytest tests/integration          # needs the DB running with migrate and seed applied
pytest                            # everything
```

## Database scripts

| Command | What it does |
|---|---|
| `python scripts/db/migrate.py` | Creates the `guardrail_app` role, then applies `db/seeds/schema.sql` (run as the owner role) |
| `python scripts/db/seed.py` | Applies the `db/seeds/0*.sql` files (safe to re-run) |
| `python scripts/db/reset.py` | **Destructive:** drops and recreates the database, then migrates and seeds |
| `psql "$MIGRATION_DATABASE_URL" -f db/tests/smoke_test.sql` | SQL smoke test |

## Configuration

All settings are in `.env`. See `.env.example`. The main ones:

- `GOVERNANCE_PORT`: API port (default 8080)
- `DATABASE_URL`: app connection, as the restricted `guardrail_app` role (RLS applies)
- `MIGRATION_DATABASE_URL`: owner connection, used only by the scripts in `scripts/db`
- `VAULT_KEY_FILE`: dev vault key path (`./secrets/dev.key`, git-ignored)
- `NEBIUS_API_KEY`, `UPSTREAM_BASE_URL`: model provider settings

## Free-tier deployment (Render + Neon)

The API and dashboard are served by the same FastAPI process, so deploy the Docker service to Render rather than splitting the frontend onto Vercel. PostgreSQL is the only required external data service. The included [`render.yaml`](render.yaml) creates a free Render web service and checks `/readyz`; the GitHub Actions workflow runs the test suite against PostgreSQL and builds the image.

```text
GitHub (CI on push/PR)
        |
        v
Render free Docker web service (FastAPI + static dashboard)
        |                     |
        v                     v
Neon PostgreSQL         Nebius Token Factory (optional; may incur model/API usage)
```

### 1. Prepare Neon PostgreSQL

Create a PostgreSQL database and keep its owner connection string private. Run the existing schema and seed scripts once from a trusted local machine. Use a unique random `APP_DB_PASSWORD`; the migration script assigns it to the restricted `guardrail_app` database role. Configure `DATABASE_URL` with that role and password—not the owner account—and use the owner URL only for migrations.

```powershell
$env:MIGRATION_DATABASE_URL = "<Neon owner connection URL>"
$env:APP_DB_PASSWORD = "<unique random password>"
$env:APP_ENV = "production"
python scripts\db\migrate.py
python scripts\db\seed.py
```

In production mode, the seed script creates the configured tenant and reference catalogs without inserting the local demo tenant/tools. Use the provider's SSL-enabled connection strings. The Render service needs only the `guardrail_app` `DATABASE_URL`; do not add `MIGRATION_DATABASE_URL` or database-owner credentials to the running web service.

### 2. Deploy the web service

Push this project to a GitHub repository, then create a Render Blueprint deployment from that repository and select `render.yaml`. Set the prompted secrets in Render:

- `DATABASE_URL`: Neon URL for `guardrail_app`.
- `HOOK_API_KEY`: a long random secret; agents must send it in `X-Veilgate-Key`.
- `VAULT_KEY_HEX` and `AUTH_KEY_HEX`: **different**, stable 32-byte keys encoded as 64 hex characters. Generate each once with `python -c "import secrets; print(secrets.token_hex(32))"` and store them in a password manager. Losing/changing the vault key makes stored values unreadable; changing the auth key invalidates existing sessions.
- `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`: your initial dashboard administrator. Both are required together. Production does not create or expose the demo logins.

After deployment, verify `https://<service>.onrender.com/healthz`, `/readyz`, and `/app/`. Configure an optional custom domain through Render and point its DNS records from Cloudflare as instructed by Render.

`LLM_JUDGE=off` is set in the Blueprint so the app does not make paid model calls by default. If you have Nebius API credit and want the optional second-opinion detector, add `NEBIUS_API_KEY` in Render and change `LLM_JUDGE` to `auto`. The local-model URL in `.env.example` is not a public production endpoint.

The free web tier is appropriate for a demo, not a high-availability or compliance-certified production service: free plans can sleep or impose resource/usage limits. Neon holds durable application data; the encryption and auth keys must remain stable in Render's environment. Upstash Redis, Resend, Cloudinary, Supabase, and Vercel are not used by this code and should not be provisioned.

## Troubleshooting

- **`warden.startup.db_unreachable` in the logs:** Postgres isn't running, or `DATABASE_URL` is wrong. Check `docker ps`.
- **Port 5432 already in use:** set `WARDEN_DB_PORT` (and the ports in the two URLs) in `.env` to a free port.
- **Password authentication failed:** the roles use `apppass` and `ownerpass`, not `CHANGE_ME`.
- **A fresh start is needed:** `docker compose -f deploy/compose/docker-compose.yml down -v`, which also deletes the DB volume.
