-- Pre-create the application role with LOGIN.
-- schema.sql creates guardrail_app as NOLOGIN (IF NOT EXISTS), so this runs first to
-- give it a password the application can connect with; schema.sql then skips it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'guardrail_app') THEN
        CREATE ROLE guardrail_app LOGIN PASSWORD 'apppass';
    END IF;
END $$;
