from datetime import timedelta
from unittest.mock import Mock

import pytest
from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.observability.backlog import OutboxBacklogCollector
from app.infra.observability.metrics import Metrics
from app.workers import outbox_worker
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from tests.integration.database.test_outbox_persistence import create

pytestmark = pytest.mark.integration


def samples(collector):
    return {
        sample.name: sample.value
        for family in collector.collect()
        for sample in family.samples
    }


def test_backlog_includes_delayed_retries_and_omits_failed_collection(
    db_session,
    integration_engine,
):
    create(db_session)
    db_session.commit()
    row = db_session.scalar(select(OutboxEventModel))
    row.created_at -= timedelta(minutes=10)
    row.next_attempt_at += timedelta(hours=1)
    db_session.commit()
    collector = OutboxBacklogCollector(sessionmaker(integration_engine))
    values = samples(collector)
    assert values["freight_outbox_pending"] == 1
    assert values["freight_outbox_oldest_pending_age_seconds"] >= 600
    assert values["freight_outbox_collection_success"] == 1
    broken = Mock(side_effect=OperationalError("secret", {}, Exception("password")))
    assert samples(OutboxBacklogCollector(broken)) == {
        "freight_outbox_collection_success": 0,
    }
    row.published_at = row.created_at
    db_session.commit()
    values = samples(collector)
    assert values["freight_outbox_pending"] == 0
    assert values["freight_outbox_oldest_pending_age_seconds"] == 0


def test_confirmation_is_not_counted_as_committed_on_database_failure(
    db_session,
    integration_engine,
    monkeypatch,
    caplog,
):
    create(db_session)
    db_session.commit()
    metrics = Metrics()
    monkeypatch.setattr(outbox_worker, "worker_metrics", metrics)

    class FailingSession(Session):
        pass

    def fail(session):
        raise OperationalError("COMMIT", {}, Exception("secret"))

    event.listen(FailingSession, "before_commit", fail)
    with pytest.raises(OperationalError):
        outbox_worker.publish_one(
            sessionmaker(integration_engine, class_=FailingSession),
            Mock(),
            retry_delay=timedelta(seconds=5),
        )
    assert (
        metrics.registry.get_sample_value(
            "freight_outbox_total", {"outcome": "broker_confirmed"}
        )
        == 1
    )
    assert (
        metrics.registry.get_sample_value(
            "freight_outbox_total", {"outcome": "published_committed"}
        )
        == 0
    )
    assert (
        metrics.registry.get_sample_value(
            "freight_outbox_total", {"outcome": "transaction_failed"}
        )
        == 1
    )
    with Session(integration_engine) as observer:
        assert observer.scalar(select(OutboxEventModel)).published_at is None
    publisher = Mock()
    outbox_worker.publish_one(
        sessionmaker(integration_engine), publisher, retry_delay=timedelta(seconds=5)
    )
    assert publisher.publish.call_args.args[0].correlation_id == str(
        publisher.publish.call_args.args[0].message_id
    )
    assert (
        metrics.registry.get_sample_value(
            "freight_outbox_total", {"outcome": "published_committed"}
        )
        == 1
    )
