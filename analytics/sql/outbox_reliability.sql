-- Daily transactional-outbox delivery health by event type.
-- Retry-limit incidents use the same durable threshold as the operator snapshot: attempts >= 5.

SELECT
    created_at::date AS event_date,
    event_type,
    COUNT(*) AS total_events,
    COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published_events,
    COUNT(*) FILTER (WHERE published_at IS NULL) AS unpublished_events,
    COUNT(*) FILTER (
        WHERE published_at IS NULL AND attempts >= 5
    ) AS retry_limit_events,
    ROUND(
        AVG(EXTRACT(EPOCH FROM (published_at - created_at)))
            FILTER (WHERE published_at IS NOT NULL)::numeric,
        3
    ) AS average_publish_latency_seconds,
    ROUND(
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (published_at - created_at))
        ) FILTER (WHERE published_at IS NOT NULL)::numeric,
        3
    ) AS p95_publish_latency_seconds,
    MAX(attempts) AS max_attempts
FROM outbox_events
GROUP BY created_at::date, event_type
ORDER BY event_date, event_type;
