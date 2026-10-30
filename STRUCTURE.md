# Folder structure: veilgate

```
veilgate/
├── README.md                  (you will add)
├── STRUCTURE.md               this file
├── .env.example               every setting, placeholders only (copy to .env, never commit)
├── .gitignore
├── .github/
│   └── workflows/             CI: lint, tests, run migrations + smoke test on a scratch database
├── config/                    non-secret defaults (ports, log levels, feature switches)
├── secrets/                   local development keys only; git-ignored, the folder itself is kept
│
├── db/
│   ├── migrations/            numbered, forward-only SQL: 0001_init.sql, 0002_..., never edited after release
│   ├── seeds/                 catalog data (always) and demo data (development only)
│   └── tests/                 SQL tests (smoke_test.sql) run against a scratch database
│
├── src/                       the governance service
│   ├── api/                   HTTP layer: reverse-proxy routes, the five hooks, admin API
│   ├── core/                  config loading, logging, errors, shared types
│   ├── gateway/               model gateway (provider routing) and tool gateway (the gate)
│   ├── detection/             identifier detection (patterns, validators, NER)
│   ├── vault/                 tokenizer, encryption, key-manager interface, known-value scan
│   ├── policy/                decision client for fn_authorize*, decision cache
│   ├── authority/             agent runs, score ledger, delegation cap, session verdict
│   ├── audit/                 events, receipts, vault access log writers
│   ├── repositories/          the only code that runs SQL
│   └── services/              use-case logic that ties the above together
│
├── integrations/              how other frameworks attach
│   ├── langchain/             callback handler + tool/model wrappers
│   ├── langgraph/             graph adapter (node name = agent)
│   ├── http_only/             contract and examples for any other framework
│   └── examples/              demo agents
│
├── dashboard/                 frontend
│   ├── src/
│   └── public/
│
├── tests/
│   ├── unit/                  no database, no network
│   ├── integration/           real database, fake provider
│   ├── e2e/                   full flow incl. the organizers' bench
│   └── fixtures/              sample records, sample prompts
│
├── scripts/
│   ├── dev/                   run locally, reset data, create a demo tenant
│   ├── db/                    migrate, create the scratch database, dump / restore
│   ├── bench/                 latency and load benchmarks
│   └── ops/                   emergency tools (e.g. free a jammed database)
│
├── deploy/
│   ├── docker/                Dockerfiles
│   └── compose/               local multi-service setup
│
└── docs/
    └── adr/                   one short file per decision (0001-token-style.md, ...); the design docs go here
```

## Rules this layout enforces
- **Migrations run once, from `scripts/db` or CI, never from the application** (the v1 lesson that froze the shared database).
- **Only `src/repositories` runs SQL**; everything else calls it.
- **`src/gateway` is the only place tools run and models are called**; agents never reach either directly.
- **Nothing secret is committed**: `.env`, `secrets/*` and `*.key` are git-ignored; `.env.example` holds placeholders.
- **Ports are fixed in one place**: governance 8080, organizers' apps 8000.
- **Tests mirror `src/`**; the database tests live next to the database in `db/tests`.
