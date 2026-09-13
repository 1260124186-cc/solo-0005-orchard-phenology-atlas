"""轻量路径路由。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..errors import NotFoundError


Handler = Callable[..., object]


@dataclass(slots=True)
class Route:
    method: str
    template: str
    pattern: re.Pattern[str]
    handler: Handler

    def match(self, method: str, path: str) -> dict[str, str] | None:
        if method.upper() != self.method:
            return None
        match = self.pattern.fullmatch(path)
        return match.groupdict() if match else None


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, template: str, handler: Handler) -> None:
        pattern = re.sub(
            r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}",
            r"(?P<\1>[^/]+)",
            template,
        )
        self._routes.append(
            Route(
                method=method.upper(),
                template=template,
                pattern=re.compile(pattern),
                handler=handler,
            )
        )

    def resolve(
        self,
        method: str,
        path: str,
    ) -> tuple[Handler, dict[str, str]]:
        allowed: set[str] = set()
        for route in self._routes:
            if route.pattern.fullmatch(path):
                allowed.add(route.method)
                params = route.match(method, path)
                if params is not None:
                    return route.handler, params
        if allowed:
            raise NotFoundError(
                "接口方法",
                f"{method} {path}，允许 {', '.join(sorted(allowed))}",
            )
        raise NotFoundError("接口", f"{method} {path}")

    @property
    def routes(self) -> tuple[Route, ...]:
        return tuple(self._routes)
