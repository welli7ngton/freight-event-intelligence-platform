import os
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server


class Metrics:
    """One registry per process (or isolated application in tests)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.http_requests = Counter(
            "freight_http_requests_total",
            "Completed HTTP requests",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "freight_http_request_duration_seconds",
            "HTTP operation duration",
            ("method", "route"),
            registry=self.registry,
        )
        self.ingestion = Counter(
            "freight_ingestion_total",
            "Ingestion observations, not unique events",
            ("outcome",),
            registry=self.registry,
        )
        self.ingestion_duration = Histogram(
            "freight_ingestion_duration_seconds",
            "Delivery processing duration",
            registry=self.registry,
        )
        self.outbox = Counter(
            "freight_outbox_total",
            "Outbox observations, not unique notifications",
            ("outcome",),
            registry=self.registry,
        )
        self.outbox_duration = Histogram(
            "freight_outbox_publish_duration_seconds",
            "Broker publication duration",
            ("outcome",),
            registry=self.registry,
        )
        for outcome in (
            "committed",
            "processing_failed",
            "retry_publish_returned",
            "dlq_publish_returned",
            "republish_failed",
            "ack_failed",
            "acked",
        ):
            self.ingestion.labels(outcome)
        for outcome in (
            "broker_confirmed",
            "publish_failed",
            "published_committed",
            "retry_committed",
            "transaction_failed",
        ):
            self.outbox.labels(outcome)


worker_metrics = Metrics()


@contextmanager
def metrics_server(metrics: Metrics, port_variable: str, default_port: int):
    port = int(os.getenv(port_variable, str(default_port)))
    if not 1 <= port <= 65535:
        raise ValueError(f"{port_variable} must be between 1 and 65535")
    server, thread = start_http_server(
        port, addr=os.getenv("METRICS_HOST", "127.0.0.1"), registry=metrics.registry
    )
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
