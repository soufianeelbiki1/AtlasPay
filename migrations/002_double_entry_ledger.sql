CREATE TABLE ledger_accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    currency CHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (id, currency)
);

CREATE TABLE ledger_transactions (
    id TEXT PRIMARY KEY,
    reference TEXT NOT NULL,
    currency CHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (id, currency)
);

CREATE TABLE ledger_entries (
    id BIGSERIAL PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('debit', 'credit')),
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (transaction_id, currency)
        REFERENCES ledger_transactions(id, currency),
    FOREIGN KEY (account_id, currency)
        REFERENCES ledger_accounts(id, currency)
);

CREATE INDEX ledger_entries_transaction_idx
    ON ledger_entries (transaction_id);

CREATE INDEX ledger_entries_account_idx
    ON ledger_entries (account_id, created_at);

CREATE OR REPLACE FUNCTION reject_ledger_entry_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ledger entries are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_entries_append_only
BEFORE UPDATE OR DELETE ON ledger_entries
FOR EACH ROW
EXECUTE FUNCTION reject_ledger_entry_mutation();

CREATE OR REPLACE FUNCTION assert_ledger_transaction_balanced()
RETURNS trigger AS $$
DECLARE
    target_transaction_id TEXT;
    debit_total BIGINT;
    credit_total BIGINT;
BEGIN
    target_transaction_id := COALESCE(NEW.transaction_id, OLD.transaction_id);

    SELECT
        COALESCE(SUM(amount) FILTER (WHERE side = 'debit'), 0),
        COALESCE(SUM(amount) FILTER (WHERE side = 'credit'), 0)
    INTO debit_total, credit_total
    FROM ledger_entries
    WHERE transaction_id = target_transaction_id;

    IF debit_total <> credit_total THEN
        RAISE EXCEPTION
            'ledger transaction % is unbalanced: debits %, credits %',
            target_transaction_id, debit_total, credit_total;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_transaction_balanced
AFTER INSERT ON ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION assert_ledger_transaction_balanced();
