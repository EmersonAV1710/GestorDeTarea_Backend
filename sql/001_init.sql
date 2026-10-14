CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS courses (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, code TEXT, term TEXT, is_active BOOLEAN NOT NULL DEFAULT true, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,name));
CREATE TABLE IF NOT EXISTS documents (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, filename TEXT NOT NULL, content_hash VARCHAR(64), draft_proposals JSON, is_confirmed BOOLEAN NOT NULL DEFAULT false, UNIQUE(user_id,content_hash), status TEXT NOT NULL DEFAULT 'uploaded' CHECK(status IN ('uploaded','analyzed','failed')), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS activities (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, document_id UUID REFERENCES documents(id) ON DELETE SET NULL, title TEXT NOT NULL, activity_type VARCHAR(20) NOT NULL DEFAULT 'otro', description TEXT NOT NULL DEFAULT '', date_warning_reason TEXT NOT NULL DEFAULT '', due_date DATE, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed')), review_required BOOLEAN NOT NULL DEFAULT false, year_unconfirmed BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_courses_user ON courses(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_user_course ON documents(user_id,course_id);
CREATE INDEX IF NOT EXISTS idx_activities_user_due ON activities(user_id,due_date);
CREATE INDEX IF NOT EXISTS idx_activities_user_course ON activities(user_id,course_id);

BEGIN;
CREATE TABLE IF NOT EXISTS revoked_tokens (token_hash VARCHAR(64) PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL);
CREATE INDEX IF NOT EXISTS ix_revoked_tokens_expires_at ON revoked_tokens(expires_at);
CREATE TABLE IF NOT EXISTS request_limits (key VARCHAR(64) PRIMARY KEY, requests INTEGER NOT NULL DEFAULT 1, expires_at TIMESTAMPTZ NOT NULL);
CREATE INDEX IF NOT EXISTS ix_request_limits_expires_at ON request_limits(expires_at);
COMMIT;
