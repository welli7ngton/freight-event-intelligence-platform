import logging
from datetime import UTC, datetime

from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.observability.logging import observe
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class OutboxBacklogCollector:
    """Independent read sessions never share the relay's locked transaction."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def describe(self):
        for name in ("pending", "oldest_pending_age_seconds", "collection_success"):
            yield GaugeMetricFamily(f"freight_outbox_{name}", "Outbox backlog snapshot")

    def collect(self):
        try:
            with self._session_factory() as session, session.begin():
                session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
                count, oldest = session.execute(
                    select(func.count(), func.min(OutboxEventModel.created_at)).where(
                        OutboxEventModel.published_at.is_(None)
                    )
                ).one()
        except SQLAlchemyError as error:
            observe(
                logger,
                "outbox_collection",
                component="outbox",
                outcome="failed",
                error_type=type(error).__name__,
            )
            yield GaugeMetricFamily(
                "freight_outbox_collection_success", "Backlog query succeeded", value=0
            )
            return
        yield GaugeMetricFamily(
            "freight_outbox_collection_success", "Backlog query succeeded", value=1
        )
        yield GaugeMetricFamily(
            "freight_outbox_pending",
            "All unpublished intents including delayed retries",
            value=count,
        )
        age = max(0, (datetime.now(UTC) - oldest).total_seconds()) if oldest else 0
        yield GaugeMetricFamily(
            "freight_outbox_oldest_pending_age_seconds",
            "Age of oldest pending intent",
            value=age,
        )
