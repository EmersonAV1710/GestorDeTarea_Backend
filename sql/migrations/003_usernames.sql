ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;

WITH candidates AS (
    SELECT
        id,
        lower(regexp_replace(split_part(email, '@', 1), '[^a-zA-Z0-9._-]', '', 'g')) AS base,
        row_number() OVER (
            PARTITION BY lower(regexp_replace(split_part(email, '@', 1), '[^a-zA-Z0-9._-]', '', 'g'))
            ORDER BY created_at, id
        ) AS occurrence
    FROM users
    WHERE username IS NULL
)
UPDATE users AS users_to_update
SET username = CASE
    WHEN length(candidates.base) BETWEEN 3 AND 30 AND candidates.occurrence = 1
        THEN candidates.base
    WHEN length(candidates.base) >= 3
        THEN left(candidates.base, 21) || '_' || left(replace(users_to_update.id::text, '-', ''), 8)
    ELSE 'usuario_' || left(replace(users_to_update.id::text, '-', ''), 8)
END
FROM candidates
WHERE users_to_update.id = candidates.id;

ALTER TABLE users ALTER COLUMN username SET NOT NULL;
ALTER TABLE users ADD CONSTRAINT users_username_format_check
    CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,29}$');
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username);
