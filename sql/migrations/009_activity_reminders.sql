CREATE TABLE IF NOT EXISTS activity_reminders (
    activity_id UUID NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    due_date DATE NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (activity_id, due_date)
);
