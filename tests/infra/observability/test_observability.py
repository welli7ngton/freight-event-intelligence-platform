import asyncio
import json
import logging
import sys
from unittest.mock import Mock
from uuid import UUID

import pika
import pytest
from app.api.application import create_application
from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.infra.messaging import rabbitmq
from app.infra.observability.context import (
    correlation_id,
    current_context,
    observation_context,
)
from app.infra.observability.http import ObservabilityMiddleware
from app.infra.observability.logging import JsonFormatter
from app.infra.observability.metrics import Metrics, metrics_server
from app.infra.observability.publication import ObservedPublisher
from fastapi.testclient import TestClient
from tests.factories.shipment import make_event, make_shipment
from tests.infra.messaging.test_rabbitmq import make_message


@pytest.mark.parametrize("value", [None, "", "bad\nheader", "x" * 65, "á", "../foo"])
def test_invalid_correlation_is_replaced(value):
    assert str(UUID(correlation_id(value)))


def test_logs_allowlist_metadata_and_never_render_exception_secrets():
    try:
        raise ValueError("postgresql://password@host secret-payload")
    except ValueError:
        record = logging.LogRecord(
            "sqlalchemy.engine",
            logging.ERROR,
            "",
            1,
            "SELECT secret-payload %s",
            ("password",),
            sys.exc_info(),
        )
    record.operation = "database_transaction"
    record.outcome = "rolled_back"
    record.payload = "secret-payload"
    with observation_context(correlation_id="request-1"):
        encoded = JsonFormatter().format(record)
    parsed = json.loads(encoded)
    assert parsed["correlation_id"] == "request-1"
    assert parsed["error_type"] == "ValueError"
    assert "password" not in encoded and "secret-payload" not in encoded
    assert current_context() == {}


def test_concurrent_asgi_contexts_are_isolated_and_reset():
    metrics = Metrics()
    seen = {}

    async def exercise():
        both_entered = asyncio.Event()
        count = 0

        async def endpoint(scope, receive, send):
            nonlocal count
            count += 1
            if count == 2:
                both_entered.set()
            await both_entered.wait()
            seen[scope["path"]] = current_context()["correlation_id"]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = ObservabilityMiddleware(endpoint, metrics)

        async def request(name):
            scope = {
                "type": "http",
                "method": "GET",
                "path": name,
                "headers": [(b"x-correlation-id", name.encode())],
            }

            async def send(message):
                pass

            await middleware(scope, None, send)
            assert current_context() == {}

        await asyncio.gather(request("first"), request("second"))

    asyncio.run(exercise())
    assert seen == {"first": "first", "second": "second"}


def test_http_correlation_error_response_and_bounded_metric_labels():
    app = create_application()

    @app.get("/probe/{identity}")
    def probe(identity: str):
        return current_context()

    @app.get("/fail")
    def fail():
        raise RuntimeError("secret")

    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.get(
            "/probe/private-id?secret=hidden", headers={"X-Correlation-ID": "request-1"}
        )
        assert result.json()["correlation_id"] == "request-1"
        assert result.headers["x-correlation-id"] == "request-1"
        assert client.get("/missing/private-id").status_code == 404
        error = client.get("/fail", headers={"X-Correlation-ID": "failure-1"})
        assert error.status_code == 500
        assert error.headers["x-correlation-id"] == "failure-1"
        assert "secret" not in error.text
        metrics = client.get("/metrics").text
    assert 'route="/probe/{identity}"' in metrics
    assert 'route="unmatched"' in metrics
    assert 'status="500"' in metrics
    assert "private-id" not in metrics and "request-1" not in metrics
    assert 'route="/metrics"' not in metrics


def test_retry_and_dlq_preserve_correlation_and_reset_context(monkeypatch):
    metrics = Metrics()
    monkeypatch.setattr(rabbitmq, "worker_metrics", metrics)
    consumer = rabbitmq.RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost/%2F", exchange="unused", queue="unused"
    )
    channel = Mock()
    body = make_message().to_json().encode()
    properties = pika.BasicProperties(
        correlation_id="request-7", message_id="message-7"
    )

    def fail(event):
        assert current_context()["correlation_id"] == "request-7"
        raise TimeoutError("secret")

    for _attempt in range(3):
        consumer.process_delivery(
            channel=channel,
            delivery_tag=1,
            body=body,
            properties=properties,
            handle_event=fail,
        )
        published = channel.basic_publish.call_args.kwargs
        properties = published["properties"]
        assert properties.correlation_id == "request-7"
        assert properties.message_id == "message-7"
        assert published["body"] == body
        assert current_context() == {}
    assert (
        metrics.registry.get_sample_value(
            "freight_ingestion_total", {"outcome": "retry_publish_returned"}
        )
        == 2
    )
    assert (
        metrics.registry.get_sample_value(
            "freight_ingestion_total", {"outcome": "dlq_publish_returned"}
        )
        == 1
    )


@pytest.mark.parametrize("failure", ["publish", "ack"])
def test_delivery_failures_do_not_report_success(monkeypatch, failure):
    metrics = Metrics()
    monkeypatch.setattr(rabbitmq, "worker_metrics", metrics)
    channel = Mock()
    consumer = rabbitmq.RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost/%2F", exchange="unused", queue="unused"
    )
    if failure == "publish":
        channel.basic_publish.side_effect = OSError("offline")
        body = b"invalid"
    else:
        channel.basic_ack.side_effect = OSError("offline")
        body = make_message().to_json().encode()
    with pytest.raises(OSError):
        consumer.process_delivery(
            channel=channel, delivery_tag=1, body=body, handle_event=lambda _: None
        )
    assert (
        metrics.registry.get_sample_value(
            "freight_ingestion_total", {"outcome": "acked"}
        )
        == 0
    )
    if failure == "publish":
        channel.basic_ack.assert_not_called()


def test_interrupted_publisher_is_never_counted_as_confirmed():
    metrics = Metrics()
    publisher = Mock()
    publisher.publish.side_effect = KeyboardInterrupt()
    observed = ObservedPublisher(publisher, metrics)
    with pytest.raises(KeyboardInterrupt):
        observed.publish(
            RecordedEventMessage.from_event(make_event(shipment=make_shipment()))
        )
    assert (
        metrics.registry.get_sample_value(
            "freight_outbox_total", {"outcome": "broker_confirmed"}
        )
        == 0
    )
    assert current_context() == {}


def test_worker_metrics_endpoint_and_shutdown(monkeypatch):
    import socket
    from urllib.request import urlopen

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("TEST_METRICS_PORT", str(port))
    monkeypatch.setenv("METRICS_HOST", "127.0.0.1")
    with metrics_server(Metrics(), "TEST_METRICS_PORT", port):
        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
            assert b"freight_ingestion_total" in response.read()
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
