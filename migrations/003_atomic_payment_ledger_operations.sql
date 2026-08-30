CREATE TABLE payment_operations (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_fingerprint CHAR(64) NOT NULL,
    payment_id TEXT NOT NULL REFERENCES payments(id),
    operation TEXT NOT NULL CHECK (operation IN ('capture', 'refund', 'reversal')),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    journal_transaction_id TEXT NOT NULL UNIQUE REFERENCES ledger_transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX payment_operations_payment_idx
    ON payment_operations (payment_id, created_at);
