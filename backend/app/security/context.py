"""每个 HTTP 请求共享的不可变运行上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class RequestContext:
    actor_id: str = "anonymous"
    idempotency_key: str | None = None
    request_method: str = ""
    request_path: str = ""
    request_hash: str = ""
    route_template: str = ""


_CURRENT: ContextVar[RequestContext] = ContextVar(
    "orchard_request_context",
    default=RequestContext(),
)


def current_request_context() -> RequestContext:
    return _CURRENT.get()


@contextmanager
def request_scope(context: RequestContext) -> Iterator[None]:
    token: Token[RequestContext] = _CURRENT.set(context)
    try:
        yield
    finally:
        _CURRENT.reset(token)
