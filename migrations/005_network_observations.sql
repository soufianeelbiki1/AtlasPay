CREATE TABLE network_observations (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    route_name TEXT NOT NULL,
    issuer_id TEXT NOT NULL,
    acquirer_id TEXT NOT NULL,
    transport_outcome TEXT NOT NULL CHECK (
        transport_outcome IN ('response', 'timeout', 'failure')
    ),
    disposition TEXT CHECK (
        disposition IS NULL OR disposition IN (
            'accepted', 'mismatched', 'timed_out', 'late', 'duplicate'
        )
    ),
    delivery_unknown BOOLEAN NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL CHECK (latency_ms >= 0),
    reversal_reason TEXT CHECK (
        reversal_reason IS NULL OR reversal_reason IN ('timeout', 'late_response', 'operator')
    )
);

CREATE INDEX idx_network_observations_recorded_at
    ON network_observations (recorded_at DESC);

CREATE INDEX idx_network_observations_route_recorded_at
    ON network_observations (route_name, recorded_at DESC);
