import json
import logging
import os
import sys
from datetime import UTC, datetime

from app.infra.observability.context import current_context

FIELDS = frozenset(
    {
        "component",
        "operation",
        "outcome",
        "duration_seconds",
        "correlation_id",
        "event_id",
        "shipment_id",
        "message_id",
        "error_type",
        "method",
        "route",
        "status_code",
        "attempt",
    }
)


class JsonFormatter(logging.Formatter):
    def __init__(self, component: str = "unknown") -> None:
        super().__init__()
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        fields = {**current_context(), **record.__dict__}
        result = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "operation": "library_log",
            "component": self.component,
        }
        result.update({name: fields[name] for name in FIELDS if name in fields})
        if record.exc_info and record.exc_info[0]:
            result["error_type"] = record.exc_info[0].__name__
        # getMessage()/formatException() can expose SQL parameters or credentials.
        return json.dumps(result, default=str, separators=(",", ":"))


def configure_logging(component: str = "api") -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid LOG_LEVEL")
    root = logging.getLogger()
    handler = next(
        (h for h in root.handlers if getattr(h, "_freight_json", False)), None
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler._freight_json = True
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter(component))
    root.setLevel(level)
    # Uvicorn configures its own handlers before application startup.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def observe(logger: logging.Logger, operation: str, **fields) -> None:
    level = logging.WARNING if fields.get("error_type") else logging.INFO
    logger.log(level, operation, extra={"operation": operation, **fields})
