from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


def test_outbox_upgrade_and_downgrade_preserve_existing_history(
    integration_engine, monkeypatch
):
    # Use a private schema inside the guarded test database, not the live schema.
    schema = f"outbox_migration_{uuid4().hex}"
    with integration_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = integration_engine.url.update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    engine = create_engine(url)
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "8b7c3d2e1f0a")
        shipment_id, event_id = uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO shipments (id, reference_number, origin, destination,
                    carrier, status, created_at, updated_at)
                VALUES (:id, 'MIGRATION', 'Fortaleza', 'Recife', 'A', 'CREATED', now(), now())
            """),
                {"id": shipment_id},
            )
            connection.execute(
                text("""
                INSERT INTO shipment_events (event_id, shipment_id, event_type,
                    source, occurred_at, received_at, payload, processing_status)
                VALUES (:id, :shipment_id, 'SHIPMENT_CREATED', 'platform', now(), now(), '{}', 'APPLIED')
            """),
                {"id": event_id, "shipment_id": shipment_id},
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM outbox_events")) == 0
            assert connection.scalar(text("SELECT count(*) FROM shipment_events")) == 1
        command.downgrade(config, "8b7c3d2e1f0a")
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT to_regclass('outbox_events')")) is None
            )
            assert connection.scalar(text("SELECT count(*) FROM shipment_events")) == 1
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM outbox_events")) == 0
    finally:
        engine.dispose()
        with integration_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
