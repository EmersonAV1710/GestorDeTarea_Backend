BEGIN;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS year_unconfirmed BOOLEAN NOT NULL DEFAULT false;
UPDATE activities
SET year_unconfirmed = due_date IS NULL,
    description = trim(regexp_replace(description,
        '[[:space:]]*El año no se especifica explícitamente en el texto, por lo que la fecha debe revisarse\.[[:space:]]*$',
        '', 'i'))
WHERE description ~* 'El año no se especifica explícitamente en el texto, por lo que la fecha debe revisarse\.[[:space:]]*$';
COMMIT;
