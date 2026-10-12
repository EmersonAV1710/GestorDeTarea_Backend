BEGIN;
CREATE TABLE IF NOT EXISTS revoked_tokens (token_hash VARCHAR(64) PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL);
CREATE INDEX IF NOT EXISTS ix_revoked_tokens_expires_at ON revoked_tokens(expires_at);
CREATE TABLE IF NOT EXISTS request_limits (key VARCHAR(64) PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 1, expires_at TIMESTAMPTZ NOT NULL);
CREATE INDEX IF NOT EXISTS ix_request_limits_expires_at ON request_limits(expires_at);
COMMIT;
