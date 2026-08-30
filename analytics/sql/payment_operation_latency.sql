-- Lifecycle-operation timing by day, currency, and operation type.
-- The latency measures durable operation creation time minus payment creation time.
-- It is not issuer/network latency and must not be presented as such.

WITH operation_observations AS (
    SELECT
        o.created_at::date AS operation_date,
        p.currency,
        o.operation,
        EXTRACT(EPOCH FROM (o.created_at - p.created_at)) AS seconds_after_payment_creation
    FROM payment_operations AS o
    JOIN payments AS p ON p.id = o.payment_id
)
SELECT
    operation_date,
    currency,
    operation,
    COUNT(*) AS operation_count,
    ROUND(AVG(seconds_after_payment_creation)::numeric, 3) AS average_seconds_after_creation,
    ROUND(
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY seconds_after_payment_creation)::numeric,
        3
    ) AS p50_seconds_after_creation,
    ROUND(
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY seconds_after_payment_creation)::numeric,
        3
    ) AS p95_seconds_after_creation
FROM operation_observations
GROUP BY operation_date, currency, operation
ORDER BY operation_date, currency, operation;
