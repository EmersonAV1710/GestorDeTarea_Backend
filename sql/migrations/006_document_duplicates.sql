BEGIN;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN NOT NULL DEFAULT false;
UPDATE documents SET is_confirmed = true WHERE EXISTS (SELECT 1 FROM activities WHERE activities.document_id = documents.id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_user_content_hash ON documents (user_id, content_hash);
COMMIT;
