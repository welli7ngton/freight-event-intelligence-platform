from types import SimpleNamespace
from unittest.mock import Mock

import pika
import pytest
from app.infra.config import get_outbox_settings
from app.infra.messaging.outbox import _Publication


@pytest.mark.parametrize(
    "ack, returned, expected",
    [
        (True, False, None),
        (False, False, pika.exceptions.NackError),
        (True, True, pika.exceptions.UnroutableError),
    ],
)
def test_confirmation_is_success_only_when_acknowledged_and_routed(
    ack, returned, expected
):
    publisher = Mock()
    attempt = _Publication(publisher, Mock())
    if returned:
        attempt.on_returned(None, None, None, b"body")
    attempt.on_confirmation(
        SimpleNamespace(method=pika.spec.Basic.Ack() if ack else pika.spec.Basic.Nack())
    )
    assert attempt.confirmed is (expected is None)
    if expected:
        assert isinstance(attempt.error, expected)
    publisher._connection_factory.return_value.close.assert_called_once()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_outbox_wait_is_rejected(monkeypatch, value):
    monkeypatch.setenv("OUTBOX_PUBLISH_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError):
        get_outbox_settings()


def test_outbound_topology_cannot_alias_ingestion(monkeypatch):
    monkeypatch.setenv("OUTBOX_QUEUE", "freight.shipment-event-ingestion")
    monkeypatch.setenv("RABBITMQ_QUEUE", "freight.shipment-event-ingestion")
    with pytest.raises(ValueError, match="separate"):
        get_outbox_settings()
