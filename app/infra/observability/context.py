import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_context: ContextVar[dict[str, str] | None] = ContextVar(
    "observation_context", default=None
)
_valid_id = re.compile(r"[A-Za-z0-9._-]{1,64}")


def correlation_id(value: str | None = None) -> str:
    return (
        value if isinstance(value, str) and _valid_id.fullmatch(value) else str(uuid4())
    )


def current_context() -> dict[str, str]:
    return dict(_context.get() or {})


@contextmanager
def observation_context(**fields: str) -> Generator[None]:
    token = _context.set({**current_context(), **fields})
    try:
        yield
    finally:
        _context.reset(token)
