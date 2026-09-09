import os
from collections.abc import Generator
from pathlib import Path

import pika
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from tests.factories.repositories import (
    InMemoryShipmentEventRepository,
    InMemoryShipmentRepository,
)
from tests.factories.shipment import make_event, make_shipment

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/freight_events_test",
)
TEST_RABBITMQ_URL = os.getenv(
    "TEST_RABBITMQ_URL",
    "amqp://guest:guest@localhost:5672/%2F",
)


def _validate_test_database_url(database_url: str) -> None:
    database_name = make_url(database_url).database
    if database_name != "freight_events_test":
        raise RuntimeError(
            "TEST_DATABASE_URL must target the isolated 'freight_events_test' database."
        )


@pytest.fixture(scope="session")
def integration_engine() -> Generator[Engine, None, None]:
    _validate_test_database_url(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    try:
        with engine.connect():
            pass
    except Exception:
        engine.dispose()
        pytest.fail(
            "PostgreSQL de integração indisponível. Execute "
            "'docker compose up -d postgres-test' e confira TEST_DATABASE_URL."
        )

    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(project_root / "alembic.ini"))
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.upgrade(alembic_config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def rabbitmq_url() -> str:
    parameters = pika.URLParameters(TEST_RABBITMQ_URL)
    try:
        connection = pika.BlockingConnection(parameters)
    except pika.exceptions.AMQPConnectionError:
        pytest.fail(
            "RabbitMQ de integraÃ§Ã£o indisponÃ­vel. Execute "
            "'docker compose up -d rabbitmq' e confira TEST_RABBITMQ_URL."
        )
    else:
        connection.close()
    return TEST_RABBITMQ_URL


@pytest.fixture
def db_session(integration_engine: Engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    with session_factory() as session:
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    with integration_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE shipment_events, shipments RESTART IDENTITY CASCADE")
        )


@pytest.fixture
def shipment():
    return make_shipment()


@pytest.fixture
def shipment_event(shipment):
    return make_event(shipment=shipment)


@pytest.fixture
def in_memory_repositories():
    return InMemoryShipmentRepository(), InMemoryShipmentEventRepository()
