CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL,
    merchant_reference VARCHAR(128) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    request_fingerprint CHAR(64) NOT NULL,
    payment_id TEXT NOT NULL REFERENCES payments(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
