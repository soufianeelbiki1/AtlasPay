"""Durable, privacy-conscious network outcome recording."""

from dataclasses import dataclass
from typing import Protocol

import psycopg

from app.network_coordinator import TransactionDisposition
from app.network_routing import IssuerRoute, ReversalReason
from app.network_transport import TransportOutcome


@dataclass(frozen=True, slots=True)
class NetworkObservation:
    route: IssuerRoute
    transport_outcome: TransportOutcome
    disposition: TransactionDisposition | None
    delivery_unknown: bool
    latency_ms: float
    reversal_reason: ReversalReason | None = None

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")


class NetworkObservationWriter(Protocol):
    def record(self, observation: NetworkObservation) -> None: ...


class PostgresNetworkObservationWriter:
    """Persist aggregate-safe network facts without PAN, STAN, RRN, or payload data."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def record(self, observation: NetworkObservation) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO network_observations (
                    route_name,
                    issuer_id,
                    acquirer_id,
                    transport_outcome,
                    disposition,
                    delivery_unknown,
                    latency_ms,
                    reversal_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    observation.route.name,
                    observation.route.issuer_id,
                    observation.route.acquirer_id,
                    observation.transport_outcome.value,
                    observation.disposition.value if observation.disposition is not None else None,
                    observation.delivery_unknown,
                    observation.latency_ms,
                    (
                        observation.reversal_reason.value
                        if observation.reversal_reason is not None
                        else None
                    ),
                ),
            )
