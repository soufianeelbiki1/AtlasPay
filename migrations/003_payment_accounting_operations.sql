ALTER TABLE payments
    ADD COLUMN authorized_amount BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN captured_amount BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN refunded_amount BIGINT NOT NULL DEFAULT 0;

ALTER TABLE payments
    ADD CONSTRAINT payments_accounting_amounts_valid CHECK (
        authorized_amount >= 0
        AND captured_amount >= 0
        AND refunded_amount >= 0
        AND authorized_amount <= amount
        AND captured_amount <= authorized_amount
        AND refunded_amount <= captured_amount
    );

CREATE TABLE payment_operations (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES payments(id),
    operation_type TEXT NOT NULL CHECK (
        operation_type IN ('authorize', 'capture', 'refund')
    ),
    amount BIGINT NOT NULL CHECK (amount > 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_fingerprint CHAR(64) NOT NULL,
    journal_id TEXT UNIQUE REFERENCES ledger_transactions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX payment_operations_payment_idx
    ON payment_operations (payment_id, created_at);
