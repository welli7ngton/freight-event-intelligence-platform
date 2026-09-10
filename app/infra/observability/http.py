import logging
from time import monotonic

from app.infra.observability.context import correlation_id, observation_context
from app.infra.observability.logging import observe
from app.infra.observability.metrics import Metrics
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app, self.metrics = app, metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identity = correlation_id(Headers(scope=scope).get("x-correlation-id"))
        scope.setdefault("state", {})["correlation_id"] = identity
        status = 500
        error_type = None
        started = monotonic()

        async def send_response(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Correlation-ID"] = identity
            await send(message)

        with observation_context(correlation_id=identity, component="api"):
            try:
                await self.app(scope, receive, send_response)
            except Exception as error:
                error_type = type(error).__name__
                raise
            finally:
                route = getattr(scope.get("route"), "path", "unmatched")
                method = scope["method"] if scope["method"] in METHODS else "OTHER"
                elapsed = monotonic() - started
                if route != "/metrics":
                    self.metrics.http_requests.labels(method, route, str(status)).inc()
                    self.metrics.http_duration.labels(method, route).observe(elapsed)
                    observe(
                        logger,
                        "http_request",
                        method=method,
                        route=route,
                        status_code=status,
                        duration_seconds=elapsed,
                        outcome="failed"
                        if error_type or status >= 500
                        else "completed",
                        error_type=error_type,
                    )
