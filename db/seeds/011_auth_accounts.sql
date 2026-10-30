-- Dashboard logins. Not tenant-scoped by row-level security: a login looks the account up before any tenant is known.
CREATE TABLE IF NOT EXISTS auth_accounts (
    principal_id  uuid PRIMARY KEY REFERENCES users (principal_id) ON DELETE CASCADE,
    tenant_id     uuid NOT NULL REFERENCES tenants(id),
    email         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role          text NOT NULL CHECK (role IN ('admin', 'user')),
    created_at    timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_accounts TO guardrail_app;
