-- Daily posted ledger flows by currency.
-- Debit and credit totals should match for durable posted transactions.
-- A non-zero difference is an analytical control signal, not an automatic repair instruction.

SELECT
    le.created_at::date AS posting_date,
    le.currency,
    COUNT(DISTINCT le.transaction_id) AS ledger_transactions,
    COUNT(*) AS ledger_entries,
    SUM(le.amount) FILTER (WHERE le.side = 'debit') AS debit_amount_minor,
    SUM(le.amount) FILTER (WHERE le.side = 'credit') AS credit_amount_minor,
    COALESCE(SUM(le.amount) FILTER (WHERE le.side = 'debit'), 0)
        - COALESCE(SUM(le.amount) FILTER (WHERE le.side = 'credit'), 0)
        AS debit_credit_difference_minor
FROM ledger_entries AS le
GROUP BY le.created_at::date, le.currency
ORDER BY posting_date, le.currency;
