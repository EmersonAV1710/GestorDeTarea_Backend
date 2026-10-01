CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS courses (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, code TEXT, term TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id,name));
CREATE TABLE IF NOT EXISTS documents (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, filename TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'uploaded' CHECK(status IN ('uploaded','analyzed','failed')), created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS activities (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, document_id UUID REFERENCES documents(id) ON DELETE SET NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', due_date DATE, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed')), review_required BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_courses_user ON courses(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_user_course ON documents(user_id,course_id);
CREATE INDEX IF NOT EXISTS idx_activities_user_due ON activities(user_id,due_date);
CREATE INDEX IF NOT EXISTS idx_activities_user_course ON activities(user_id,course_id);
