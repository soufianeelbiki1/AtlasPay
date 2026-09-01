-- Java-specific tables are owned by the root migration runner.
-- The outbox_events table is shared with the Python service and is created by
-- migrations/004_transactional_outbox.sql.
CREATE TABLE IF NOT EXISTS authorization_decisions (
    decision_id UUID PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    payment_id VARCHAR(128) NOT NULL,
    issuer_id VARCHAR(128) NOT NULL,
    amount_minor BIGINT NOT NULL,
    currency CHAR(3) NOT NULL,
    status VARCHAR(32) NOT NULL,
    reason VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reconciliation_items (
    item_id UUID PRIMARY KEY,
    payment_id VARCHAR(128) NOT NULL,
    expected_status VARCHAR(32) NOT NULL,
    observed_status VARCHAR(32),
    amount_minor BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reconciliation_results (
    item_id UUID PRIMARY KEY REFERENCES reconciliation_items(item_id),
    payment_id VARCHAR(128) NOT NULL,
    match_status VARCHAR(32) NOT NULL,
    delta_minor BIGINT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reconciliation_items_pending_idx
    ON reconciliation_items (created_at, item_id)
    WHERE processed_at IS NULL;
