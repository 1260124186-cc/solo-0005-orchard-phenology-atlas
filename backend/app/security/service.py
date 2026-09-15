"""基于能力与资源范围的本地授权。"""

from __future__ import annotations

from datetime import datetime, timezone

from ..errors import DomainError
from ..persistence.database import Database


class AuthorizationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def require(
        self,
        *,
        actor_id: str,
        capability: str,
        resource_kind: str,
        resource_id: str | None,
    ) -> None:
        if not actor_id or actor_id == "anonymous":
            raise DomainError(
                "authentication_required",
                "请求缺少有效的 X-Actor-Id",
                401,
            )
        now = _now()
        scope = resource_id or "*"
        with self.database.read_connection() as connection:
            actor = connection.execute(
                "SELECT status FROM actors WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if actor is None or actor["status"] != "active":
                raise DomainError(
                    "actor_unavailable",
                    "操作者不存在或已停用",
                    401,
                    {"actor_id": actor_id},
                )
            grant = connection.execute(
                """
                SELECT 1
                FROM access_grants
                WHERE actor_id = ?
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND (capability = ? OR capability = '*')
                  AND (resource_kind = ? OR resource_kind = '*')
                  AND (resource_id = ? OR resource_id = '*' OR resource_id = ?)
                LIMIT 1
                """,
                (
                    actor_id,
                    now,
                    capability,
                    resource_kind,
                    scope,
                    scope,
                ),
            ).fetchone()
        if grant is None:
            raise DomainError(
                "forbidden",
                "当前操作者没有执行此操作的权限",
                403,
                {
                    "actor_id": actor_id,
                    "capability": capability,
                    "resource_kind": resource_kind,
                    "resource_id": resource_id,
                },
            )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
