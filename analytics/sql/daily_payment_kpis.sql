-- Daily payment creation cohorts by currency and current durable status.
-- IMPORTANT: status is the payment's current state, not an event-time authorization funnel.
-- Monetary values remain in currency minor units and currencies are never combined.

SELECT
    created_at::date AS payment_date,
    currency,
    COUNT(*) AS payments_created,
    SUM(amount) AS gross_created_amount_minor,
    ROUND(AVG(amount), 2) AS average_created_amount_minor,
    COUNT(*) FILTER (WHERE status = 'pending') AS pending_payments,
    COUNT(*) FILTER (WHERE status = 'authorized') AS authorized_payments,
    COUNT(*) FILTER (WHERE status = 'captured') AS captured_payments,
    COUNT(*) FILTER (WHERE status = 'refunded') AS refunded_payments,
    COUNT(*) FILTER (WHERE status = 'reversed') AS reversed_payments,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_payments,
    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_payments,
    ROUND(
        COUNT(*) FILTER (WHERE status = 'captured')::numeric / NULLIF(COUNT(*), 0),
        4
    ) AS current_captured_share
FROM payments
GROUP BY created_at::date, currency
ORDER BY payment_date, currency;
