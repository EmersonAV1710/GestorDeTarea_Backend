BEGIN;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS date_warning_reason TEXT NOT NULL DEFAULT '';

-- Mueve los avisos de fechas alternativas de registros anteriores a su propio campo.
UPDATE activities
SET date_warning_reason = trim(substring(description FROM
        '(?i)(Fechas? alternativas? entre[^.!?]*[.!?]?)[[:space:]]*$')),
    description = trim(regexp_replace(description,
        '[[:space:]]*Fechas? alternativas? entre[^.!?]*[.!?]?[[:space:]]*$', '', 'i'))
WHERE due_date IS NULL
  AND date_warning_reason = ''
  AND description ~* 'Fechas? alternativas? entre[^.!?]*[.!?]?[[:space:]]*$';

UPDATE activities
SET date_warning_reason = trim(substring(description FROM
        '(?i)(La fecha (depende|varía)[^.!?]*[.!?]?)[[:space:]]*$')),
    description = trim(regexp_replace(description,
        '[[:space:]]*La fecha (depende|varía)[^.!?]*[.!?]?[[:space:]]*$', '', 'i'))
WHERE due_date IS NULL
  AND date_warning_reason = ''
  AND description ~* 'La fecha (depende|varía)[^.!?]*[.!?]?[[:space:]]*$';
COMMIT;
