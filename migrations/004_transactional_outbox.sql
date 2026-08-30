CREATE TABLE outbox_events (
    id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    locked_at TIMESTAMPTZ
);

CREATE INDEX outbox_events_unpublished_idx
    ON outbox_events (created_at)
    WHERE published_at IS NULL;

CREATE TABLE consumed_events (
    consumer_name TEXT NOT NULL,
    event_id TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (consumer_name, event_id)
);
