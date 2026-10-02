DROP INDEX IF EXISTS ix_users_username;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_format_check;
ALTER TABLE users DROP COLUMN IF EXISTS username;
