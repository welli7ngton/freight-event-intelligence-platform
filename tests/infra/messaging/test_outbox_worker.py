from threading import Event
from unittest.mock import Mock

from app.infra.config import OutboxSettings
from app.workers import outbox_worker
from sqlalchemy.exc import OperationalError


def test_worker_recovers_after_database_failure_and_can_stop(monkeypatch):
    stop = Event()
    calls = []
    factory, publisher = Mock(), Mock()

    def process(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise OperationalError("SELECT", {}, Exception("offline"))
        stop.set()
        return True

    monkeypatch.setattr(outbox_worker, "publish_one", process)
    outbox_worker.run(
        factory,
        publisher,
        settings=OutboxSettings("exchange", "queue", 0.001, 0.001, 1),
        stop=stop,
    )
    assert calls == [(factory, publisher), (factory, publisher)]
